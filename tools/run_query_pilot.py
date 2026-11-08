"""Prepare sanitized pilot inputs, then retrieve without reading labels.

python tools/run_query_pilot.py prepare --out experiments/runs/query-pilot-20261102
python tools/run_query_pilot.py run --run-dir experiments/runs/query-pilot-20261102
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.buildgraph import build_graph, read_snapshot
from experiments.query_pilot import (ACTIONS, TaskInput, canonical, digest, extract_actions,
                                    file_hash, load_manifest, sanitize_task, stable_search)
from experiments.retrieve import BM25, document_text
from experiments.snapindex import SnapshotIndex

SOURCES = ["experiments/query_pilot.py", "tools/run_query_pilot.py", "tools/evaluate_query_pilot.py",
           "experiments/retrieve.py", "experiments/buildgraph.py", "experiments/snapshot.py",
           "experiments/snapindex.py", "experiments/symbols.py", "experiments/coverage.py"]


def prepare(args):
    if args.per_repo < 1:
        raise ValueError("per-repo must be positive")
    groups = defaultdict(list)
    seen = set()
    for line in args.tasks.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        task = sanitize_task(json.loads(line))
        if task["instance_id"] in seen:
            raise ValueError("Duplicate task ID")
        seen.add(task["instance_id"])
        groups[task["repo"]].append(task)
    selected = []
    for repo in sorted(groups):
        ordered = sorted(groups[repo], key=lambda row: digest([args.seed, row["instance_id"]]))
        selected.extend(ordered[:args.per_repo])
    if not selected:
        raise ValueError("No tasks")
    source_hashes = {name: file_hash(ROOT / name) for name in SOURCES}
    config = {"actions": list(ACTIONS), "fixed_actions": ["identifiers", "prose"],
              "max_supplemental_actions": 2, "max_retrieval_calls": 3,
              "per_action_candidates": 200, "candidate_cap": 200, "final_k": 10,
              "rrf_k": 60, "issue_char_limit": 20000, "query_char_limit": 4000,
              "max_total_query_chars": 28000, "max_scored_documents": 300000,
              "max_index_nodes": 100000, "max_source_chars": 50000000,
              "body_lines": 80, "model_calls": 0, "retries": 0,
              "feedback_rounds": 0, "cache": "fresh snapshot and index per task",
              "failure_policy": "empty candidates; retain task in coverage denominator if gold exists"}
    args.out.mkdir(parents=True, exist_ok=False)
    task_path = args.out / "tasks.jsonl"
    task_path.write_text("".join(canonical(row) + "\n" for row in selected), encoding="utf-8")
    manifest = {"schema": 1, "stage": "fixed_menu_exploratory_pilot",
                "date": "2026-11-02", "source_tasks_sha256": file_hash(args.tasks),
                "source_tasks_path": str(args.tasks.resolve()),
                "tasks_sha256": file_hash(task_path), "task_ids": [r["instance_id"] for r in selected],
                "selection": {"seed": args.seed, "per_repo": args.per_repo,
                              "rule": "lowest SHA256(seed, instance_id) per repo; no labels or outcomes"},
                "source_hashes": source_hashes, "config": config,
                "evaluation": {"primary": "macro candidate coverage: menu oracle minus fixed identifiers+prose",
                               "oracle_objective": "candidate coverage only; ties by fewer actions then action names",
                               "minimum_worthwhile_coverage_delta": 0.02,
                               "threshold_status": "engineering continuation threshold, not expected improvement",
                               "interval": "paired repository-cluster bootstrap; descriptive only on reused data",
                               "bootstrap_replicates": 2000, "bootstrap_seed": 20261102,
                               "automatic_expansion": False,
                               "multiplicity": "one primary contrast; other contrasts descriptive",
                               "gold_policy": "exact canonical IDs; retain unindexed targets in denominator",
                               "failure_policy": config["failure_policy"]},
                "limits": ["historically used Lite tasks; not an unseen test set",
                           "lexical menu only; no adaptive evidence state",
                           "RRF pilot ranking, not the strongest learned fusion ranker",
                           "all-menu execution is diagnostic and may exceed deployment budget",
                           "source size cap is checked after snapshot read, not a hard IO limit",
                           "no wall-time cutoff; elapsed time reported, not claimed equal"]}
    manifest["manifest_sha256"] = digest(manifest)
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"prepared": str(args.out), "tasks": len(selected),
                      "manifest_sha256": manifest["manifest_sha256"]}, ensure_ascii=False))


def retrieve_task(task, repos, config):
    started = time.perf_counter()
    row = {"instance_id": task.instance_id, "repo": task.repo, "base_commit": task.base_commit,
           "status": "error", "actions": {}}
    try:
        snapshot = SnapshotIndex(repos).path_for({"instance_id": task.instance_id,
                                                 "repo": task.repo, "base_commit": task.base_commit})
        if snapshot is None:
            raise FileNotFoundError("missing_snapshot")
        files = read_snapshot(snapshot)
        row["snapshot_content_sha256"] = digest(sorted(files.items()))
        row["source_chars"] = sum(map(len, files.values()))
        row["source_files"] = len(files)
        if row["source_chars"] > config["max_source_chars"]:
            raise ValueError("source_size_limit")
        graph, _ = build_graph(files)
        row["index_nodes"] = len(graph.nodes)
        if len(graph.nodes) > config["max_index_nodes"]:
            raise ValueError("index_node_limit")
        lines = {path: source.splitlines() for path, source in files.items()}
        docs = {}
        for node_id, node in sorted(graph.nodes.items()):
            start = max(node["lineno"] - 1, 0)
            end = min(node["end_lineno"], start + config["body_lines"])
            docs[node_id] = document_text(node) + "\n" + "\n".join(lines[node["file"]][start:end])
        index = BM25(docs)
        row["index_document_chars"] = sum(map(len, docs.values()))
        row["preprocessing_seconds"] = time.perf_counter() - started
        extracted = extract_actions(task, config["issue_char_limit"], config["query_char_limit"])
        row["evidence"] = extracted["evidence"]
        row["issue_chars_seen"] = extracted["issue_chars_seen"]
        row["issue_truncated"] = extracted["issue_truncated"]
        for action, value in extracted["actions"].items():
            query = value["query"]
            available = value.get("available", True)
            search_start = time.perf_counter()
            candidates, scored = stable_search(index, query, config["per_action_candidates"]) if available else ([], 0)
            for candidate in candidates:
                node = graph.nodes[candidate["id"]]
                candidate.update({"file": node["file"], "lineno": node["lineno"], "end_lineno": node["end_lineno"]})
            row["actions"][action] = {**value, "available": available, "candidates": candidates,
                                       "cost": {"retrieval_calls": int(available), "query_chars": len(query) if available else 0,
                                                "scored_documents": scored,
                                                "search_seconds": time.perf_counter() - search_start}}
        row["status"] = "ok"
    except (OSError, ValueError, SyntaxError) as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
        # Partial action execution is not a comparable completed task.
        row["partial_actions"] = row.pop("actions")
        row["actions"] = {}
    row["total_seconds"] = time.perf_counter() - started
    return row


def run(args):
    manifest = load_manifest(args.run_dir)
    for name, expected in manifest["source_hashes"].items():
        if file_hash(ROOT / name) != expected:
            raise ValueError(f"Source changed since preparation: {name}; prepare a new run")
    tasks = [TaskInput.from_mapping(json.loads(line)) for line in
             (args.run_dir / "tasks.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if [task.instance_id for task in tasks] != manifest["task_ids"]:
        raise ValueError("Task ID list mismatch")
    with (args.run_dir / "trace.jsonl").open("x", encoding="utf-8") as output:
        for number, task in enumerate(tasks, 1):
            row = retrieve_task(task, args.repos, manifest["config"])
            row["manifest_sha256"] = manifest["manifest_sha256"]
            output.write(canonical(row)+"\n")
            output.flush()
            print(f"{number}/{len(tasks)} {task.instance_id} {row['status']} {row['total_seconds']:.1f}s", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--tasks", type=Path, default=ROOT / "data/swebench_lite.jsonl")
    prep.add_argument("--out", type=Path, required=True)
    prep.add_argument("--per-repo", type=int, default=1)
    prep.add_argument("--seed", type=int, default=20261102)
    execute = sub.add_parser("run")
    execute.add_argument("--run-dir", type=Path, required=True)
    execute.add_argument("--repos", type=Path, default=ROOT / "data/repos")
    args = ap.parse_args()
    prepare(args) if args.command == "prepare" else run(args)


if __name__ == "__main__":
    main()
