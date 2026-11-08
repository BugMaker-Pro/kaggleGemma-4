"""Synthetic fixtures exercise plumbing only; they are not model experiment results."""
import argparse
import contextlib
import io
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.feedback_pilot import (CONFIG, code_excerpts, paired_requests, parse_queries,
                                       rank_queries, validate_pair_order)
from experiments.query_pilot import TaskInput, canonical, digest, stable_search
from tools.run_feedback_pilot import (build_index, evaluate, model_files, retrieve,
                                     validate_responses, validate_retrieval)


class FeedbackPilotTests(unittest.TestCase):
    def setUp(self):
        self.task = TaskInput("task", "o/r", "abc", "conversion loses timezone")
        self.files = {"core.py": 'def convert(value):\n    """Convert timezone."""\n    return value\n'}
        self.candidates = [{"id": "core.convert", "file": "core.py", "lineno": 1, "end_lineno": 3}]
        self.excerpts = code_excerpts(self.files, self.candidates)
        self.requests = paired_requests(self.task, self.excerpts)

    def fixture(self):
        manifest = {"manifest_sha256": "synthetic_manifest", "model_sha256": "synthetic_model",
                    "input_token_counts": {r["request_sha256"]: 100 for r in self.requests}}
        responses = []
        for request in self.requests:
            responses.append({"instance_id": "task", "arm": request["arm"],
                              "manifest_sha256": "synthetic_manifest", "model_sha256": "synthetic_model",
                              "request_sha256": request["request_sha256"], "input_tokens": 100, "output_tokens": 12,
                              "model_calls": 1, "status": "ok", "raw_output": '{"queries":["convert","timezone"]}',
                              "queries": ["convert", "timezone"], "seconds": 0})
        original, scored = stable_search(build_index(self.files), self.task.problem_statement, 200)
        trace = {"instance_id": "task", "repo": "o/r", "base_commit": "abc", "status": "ok",
                 "snapshot_content_sha256": digest(sorted(self.files.items())),
                 "actions": {"original": {"query": self.task.problem_statement, "candidates": original,
                                          "cost": {"scored_documents": scored}}}}
        return manifest, responses, trace

    def test_preplanned_never_sees_code_or_candidate_names(self):
        pre, feedback = self.requests
        self.assertEqual(pre["code_chars_exposed"], 0)
        self.assertNotIn("core.convert", pre["messages"][0]["content"])
        self.assertIn("core.convert", feedback["messages"][0]["content"])
        for request in self.requests:
            self.assertNotIn("patch", set(request))
        validate_pair_order(self.requests, ["task"])

    def test_issue_clipping_is_identical_between_arms(self):
        rows = paired_requests(TaskInput("task", "o/r", "abc", "x"*7000), self.excerpts)
        for row in rows:
            self.assertTrue(row["issue_truncated"])
            self.assertEqual(row["issue_chars_exposed"], 6000)

    def test_unicode_offsets_and_truncation(self):
        files = {"core.py": "# 时区\n" + "返回数据\n"*100}
        candidates = [{"id":"core", "file":"core.py", "lineno":2, "end_lineno":101}]
        excerpts = code_excerpts(files, candidates, {**CONFIG, "snippet_chars": 17})
        entry = excerpts[0]
        self.assertEqual(entry["text"], files["core.py"][entry["start_char"]:entry["end_char"]])
        self.assertEqual(len(entry["text"]), 17)
        self.assertTrue(entry["truncated"])

    def test_missing_source_or_bad_range_fails(self):
        with self.assertRaises(ValueError):
            code_excerpts({}, self.candidates)
        with self.assertRaises(ValueError):
            code_excerpts(self.files, [{**self.candidates[0], "lineno": 0}])
        with self.assertRaises(ValueError):
            paired_requests(self.task, self.excerpts*6)

    def test_strict_json_and_no_silent_repair(self):
        self.assertEqual(parse_queries('{"queries":["convert", "timezone"]}'), ["convert", "timezone"])
        invalid = ['[]', '{}', '{"queries":["x"]}', '{"queries":["convert","convert"]}',
                   '{"queries":["the", "timezone"]}', '{"queries":["convert", 2]}',
                   '{"queries":["convert","timezone"], "patch":"x"}', 'not json',
                   json.dumps({"queries":["a"*1001,"timezone"]})]
        for raw in invalid:
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                parse_queries(raw)

    def test_request_tamper_and_missing_pair_rejected(self):
        changed = copy.deepcopy(self.requests)
        changed[0]["messages"][0]["content"] += "additional code"
        with self.assertRaises(ValueError):
            validate_pair_order(changed, ["task"])
        with self.assertRaises(ValueError):
            validate_pair_order(self.requests[:1], ["task"])

    def test_model_usage_and_response_provenance(self):
        manifest, responses, _ = self.fixture()
        validate_responses(responses, self.requests, manifest)
        for field, value in (("output_tokens",257), ("model_calls",2), ("model_sha256","different"),
                             ("input_tokens",99), ("queries",["secret_target","timezone"])):
            changed=copy.deepcopy(responses)
            changed[0][field]=value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_responses(changed,self.requests,manifest)

    def test_unknown_output_cost_retained_for_generation_failure(self):
        manifest, responses, _ = self.fixture()
        responses[0].update(status="generation_error",queries=[],output_tokens=None,raw_output="",error="synthetic failure")
        validate_responses(responses,self.requests,manifest)
        responses[0]["queries"]=["secret"]
        with self.assertRaises(ValueError):
            validate_responses(responses,self.requests,manifest)

    def test_original_only_fallback_has_same_ranking(self):
        original=[{"id":"a","score":2.0},{"id":"b","score":1.0}]
        self.assertEqual(rank_queries(original,[]),["a","b"])
        with self.assertRaises(ValueError):
            rank_queries(original,[[{"id":"c","score":1.0}]])

    def test_encoder_rejected_before_weight_loading(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"config.json").write_text(json.dumps({"architectures":["BertModel"]}),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"causal chat"):
                model_files(root)

    def test_synthetic_retrieval_and_offline_evaluation_end_to_end(self):
        manifest,responses,trace=self.fixture()
        # One arm fails to generate: it must remain in the paired denominator.
        responses[1].update(status="invalid_output",queries=[],raw_output="not json",error="synthetic parse failure")
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            repos=root/"repos"
            snapshot=repos/"task"
            snapshot.mkdir(parents=True)
            (snapshot/"core.py").write_text(self.files["core.py"],encoding="utf-8")
            with (root/"responses.jsonl").open("w",encoding="utf-8") as stream:
                for response in responses:
                    stream.write(canonical(response)+"\n")
            gold={"instance_id":"task","repo":"o/r","base_commit":"abc","files":[
                {"path":"core.py","language":"python","symbols":[{"qualname":"convert"},{"qualname":"missing"}]}]}
            (root/"gold.jsonl").write_text(canonical(gold)+"\n",encoding="utf-8")
            args=argparse.Namespace(run_dir=root,repos=repos,gold=root/"gold.jsonl")
            with patch("tools.run_feedback_pilot.load_run",return_value=(manifest,self.requests,[trace])), contextlib.redirect_stdout(io.StringIO()):
                retrieve(args)
                rows=[json.loads(line) for line in (root/"retrieval.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual(rows[0]["retrieval_calls"],3)
                self.assertEqual(rows[1]["retrieval_calls"],1)
                validate_retrieval(rows[0],responses[0],trace,manifest)
                tampered=copy.deepcopy(rows[0])
                tampered["scored_documents"]+=1
                with self.assertRaises(ValueError):
                    validate_retrieval(tampered,responses[0],trace,manifest)
                evaluate(args)
            summary=json.loads((root/"summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["scorable_tasks"],1)
            self.assertEqual(summary["fallbacks"]["feedback"],1)
            self.assertEqual(summary["means"]["preplanned"]["coverage"],0.5)
            self.assertEqual(summary["means"]["feedback"]["coverage"],0.5)
            self.assertIsNone(summary["descriptive_repo_bootstrap_95"])


if __name__ == "__main__":
    unittest.main()
