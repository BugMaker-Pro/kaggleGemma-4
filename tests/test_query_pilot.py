from __future__ import annotations

import copy
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from experiments.query_pilot import (ACTIONS, TaskInput, allowed_sequences, canonical, digest,
                                    extract_actions, file_hash, load_manifest, merge_actions,
                                    sanitize_task, stable_search)
from experiments.retrieve import BM25
from tools.evaluate_query_pilot import evaluate_row, gold_targets, validate_row
from tools.run_query_pilot import retrieve_task

CONFIG = {"max_supplemental_actions": 2, "max_retrieval_calls": 3,
          "max_scored_documents": 300000, "max_total_query_chars": 28000,
          "candidate_cap": 2, "rrf_k": 60, "final_k": 10,
          "fixed_actions": ["identifiers", "prose"], "issue_char_limit": 20000,
          "query_char_limit": 4000, "max_source_chars": 50000000,
          "max_index_nodes": 100000, "body_lines": 80, "per_action_candidates": 2}


def result(ids, available=True, scored=None):
    return {"candidates": [{"id": key, "score": float(len(ids)-i)} for i, key in enumerate(ids)],
            "available": available, "cost": {"retrieval_calls": int(available),
            "scored_documents": len(ids) if scored is None else scored,
            "query_chars": int(available), "search_seconds": 0.0}}


def results():
    return {"original": result(["a", "b"]), "identifiers": result(["a", "b"]),
            "code": result(["target", "a"]), "prose": result(["b", "a"]),
            "traceback": result([], False)}


class QueryPilotTests(unittest.TestCase):
    def test_gold_and_patch_fields_never_cross_boundary(self):
        raw = {"instance_id": "task", "repo": "owner/repo", "base_commit": "abc",
               "problem_statement": "broken parser", "patch": "secret_target",
               "test_patch": "hidden_test", "gold": ["secret_target"], "FAIL_TO_PASS": ["x"]}
        clean = sanitize_task(raw)
        changed = {**raw, "patch": "other", "gold": ["other"]}
        self.assertEqual(clean, sanitize_task(changed))
        self.assertEqual(set(clean), {"instance_id", "repo", "base_commit", "problem_statement"})
        with self.assertRaises(ValueError):
            TaskInput.from_mapping(raw)
        with self.assertRaises(TypeError):
            extract_actions(raw)
        self.assertNotIn("secret_target", canonical(extract_actions(TaskInput.from_mapping(clean))))

    def test_spans_point_to_exact_issue_and_fenced_code_is_not_inline(self):
        issue = '转换失败 \x60pkg.convert\x60\n\x60\x60\x60python\nx = convert(1)\n\x60\x60\x60\nFile "pkg/core.py", line 12, in run'
        task = TaskInput("task", "o/r", "abc", issue)
        evidence = extract_actions(task)["evidence"]
        for span in evidence:
            self.assertEqual(issue[span["start"]:span["end"]], span["text"])
        self.assertEqual([e["text"] for e in evidence if e["kind"] == "inline"], ["pkg.convert"])
        self.assertEqual([e["text"] for e in evidence if e["kind"] == "code"], ["x = convert(1)\n"])

    def test_plain_issue_marks_missing_actions_unavailable(self):
        extracted = extract_actions(TaskInput("task", "o/r", "abc", "conversion loses timezone"))
        self.assertFalse(extracted["actions"]["identifiers"]["available"])
        self.assertFalse(extracted["actions"]["code"]["available"])
        self.assertTrue(extracted["actions"]["prose"]["available"])

    def test_query_limits_keep_valid_offsets(self):
        task = TaskInput("task", "o/r", "abc", "\x60alpha\x60 " * 20)
        data = extract_actions(task, issue_char_limit=15, query_char_limit=3)
        self.assertTrue(data["issue_truncated"])
        self.assertEqual(len(data["actions"]["original"]["query"]), 15)
        self.assertLessEqual(len(data["actions"]["identifiers"]["query"]), 3)
        self.assertTrue(all(span["end"] <= 15 for span in data["evidence"]))

    def test_search_is_stable_and_matches_baseline_scores(self):
        index = BM25({"z": "parser token", "a": "parser token", "b": "token", "c": "none"})
        actual, count = stable_search(index, "token parser token", 10)
        self.assertEqual(count, 3)
        self.assertEqual([row["id"] for row in actual][:2], ["a", "z"])
        expected = dict(index.search("parser token", 10))
        for row in actual:
            self.assertAlmostEqual(row["score"], expected[row["id"]], places=12)

    def test_oracle_cannot_pick_gold_after_truncation(self):
        data = results()
        config = {**CONFIG, "candidate_cap": 1}
        scored = evaluate_row({"status": "ok", "actions": data}, {"target"}, config)
        self.assertEqual(scored["all_menu_union_coverage"], 1.0)
        self.assertEqual(scored["arms"]["oracle"]["coverage"], 0.0)
        self.assertEqual(scored["arms"]["oracle"]["selected_actions"], [])

    def test_oracle_excludes_expensive_action(self):
        data = results()
        data["code"]["cost"]["scored_documents"] = 300001
        feasible = list(allowed_sequences(data, CONFIG))
        self.assertFalse(any("code" in choice for choice in feasible))
        self.assertFalse(any("traceback" in choice for choice in feasible))

    def test_duplicate_candidates_are_rejected(self):
        data = results()
        data["original"] = result(["a", "a"])
        with self.assertRaises(ValueError):
            merge_actions(data, (), 2, 60)

    def test_missing_from_index_gold_stays_in_denominator(self):
        record = {"files": [{"path": "pkg/core.py", "language": "python", "symbols": [
            {"qualname": "present"}, {"qualname": "absent"}]}]}
        targets = gold_targets(record)
        data = {name: result([], False) for name in ACTIONS}
        data["original"] = result(["pkg.core.present"])
        scored = evaluate_row({"status": "ok", "actions": data}, targets, CONFIG)
        self.assertEqual(scored["gold_count"], 2)
        self.assertEqual(scored["arms"]["original"]["coverage"], 0.5)

    def test_failure_is_zero_not_dropped(self):
        scored = evaluate_row({"status": "error", "actions": {}}, {"target"}, CONFIG)
        self.assertTrue(scored["scorable"])
        self.assertEqual(scored["arms"]["fixed"]["coverage"], 0.0)
        self.assertFalse(evaluate_row({"status": "ok"}, set(), CONFIG)["scorable"])

    def test_real_snapshot_trace_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot = Path(folder) / "task"
            snapshot.mkdir()
            (snapshot / "core.py").write_text('def convert(x):\n    """Convert timezone."""\n    return x\n', encoding="utf-8")
            task = TaskInput("task", "owner/repo", "abc", "\x60convert\x60 loses timezone")
            row = retrieve_task(task, Path(folder), CONFIG)
            self.assertEqual(row["status"], "ok", row)
            manifest = {"manifest_sha256": "fingerprint", "config": CONFIG}
            row["manifest_sha256"] = "fingerprint"
            validate_row(row, task, manifest)
            bad = copy.deepcopy(row)
            bad["actions"]["original"]["query"] = "gold target"
            with self.assertRaises(ValueError):
                validate_row(bad, task, manifest)
            bad = copy.deepcopy(row)
            bad["actions"]["original"]["cost"]["query_chars"] = 0
            with self.assertRaises(ValueError):
                validate_row(bad, task, manifest)

    def test_manifest_and_sanitized_inputs_are_fingerprinted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tasks = root / "tasks.jsonl"
            tasks.write_text(canonical(asdict(TaskInput("task", "o/r", "abc", "issue")))+"\n", encoding="utf-8")
            manifest = {"tasks_sha256": file_hash(tasks)}
            manifest["manifest_sha256"] = digest(manifest)
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            load_manifest(root)
            tasks.write_text("changed", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_manifest(root)


if __name__ == "__main__":
    unittest.main()
