"""Frozen exploratory retention replay: prepare -> replay (no gold) -> evaluate."""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from experiments.candidate_retention import retain_candidates
from experiments.query_pilot import (ACTIONS, TaskInput, allowed_sequences, arm_cost, canonical,
                                    digest, file_hash, load_manifest)
from tools.evaluate_query_pilot import gold_targets, validate_row


SOURCES = ["experiments/candidate_retention.py", "tools/analyse_candidate_retention.py"]


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def read_parent(directory):
    manifest = load_manifest(directory)
    for name, expected in manifest["source_hashes"].items():
        if file_hash(ROOT / name) != expected:
            raise ValueError(f"Parent source changed: {name}")
    traces = read_rows(directory / "trace.jsonl")
    tasks = [TaskInput.from_mapping(row) for row in read_rows(directory / "tasks.jsonl")]
    expected_ids = manifest["task_ids"]
    if ([row["instance_id"] for row in traces] != expected_ids
            or [task.instance_id for task in tasks] != expected_ids):
        raise ValueError("Incomplete, duplicate or reordered parent inputs")
    for task, row in zip(tasks, traces):
        validate_row(row, task, manifest)
    return manifest, traces


def prepare(args):
    parent, traces = read_parent(args.parent)
    manifest = {"schema": 1, "date": "2026-11-02", "stage": "exploratory_candidate_retention_replay",
                "parent_manifest_sha256": parent["manifest_sha256"],
                "parent_trace_sha256": file_hash(args.parent / "trace.jsonl"),
                "parent_tasks_sha256": parent["tasks_sha256"], "task_ids": parent["task_ids"],
                "source_hashes": {name: file_hash(ROOT / name) for name in SOURCES},
                "config": parent["config"],
                "comparison": {"primary": "fixed actions: round-robin retention minus RRF retention, macro coverage",
                               "fixed_actions": parent["config"]["fixed_actions"],
                               "retention": "one next-unseen candidate per list per round; original then ACTIONS order",
                               "ranking": "full-union RRF scores and ID ties, restricted to retained set",
                               "variants": ["rrf", "round_robin"], "parameter_sweep": False,
                               "candidate_cap": parent["config"]["candidate_cap"],
                               "oracle": "coverage objective; ties fewer actions then action names; secondary only",
                               "interval": "repository bootstrap descriptive 95%; 2000 replicates; seed 20261102",
                               "automatic_expansion": False},
                "limits": ["Same 12 historically used tasks; protocol motivated by observed v1 failures",
                           "Exploratory replay, not confirmation and not an online action selector",
                           "Same cached retrieval work; no new retrieval, LLM or repair calls",
                           "Final ranking is RRF, not the strongest learned ranker",
                           "Source recall is limited to each saved action top 200; deeper ranks are unknown",
                           "Round-robin preserves neither all baseline hits nor all action hits"]}
    manifest["manifest_sha256"] = digest(manifest)
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(canonical({"prepared": str(args.out), "tasks": len(traces), "manifest_sha256": manifest["manifest_sha256"]}))


def load_run(directory, parent_dir):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    fingerprint = manifest.pop("manifest_sha256")
    if digest(manifest) != fingerprint:
        raise ValueError("Replay manifest changed")
    manifest["manifest_sha256"] = fingerprint
    parent, traces = read_parent(parent_dir)
    if (parent["manifest_sha256"] != manifest["parent_manifest_sha256"]
            or file_hash(parent_dir / "trace.jsonl") != manifest["parent_trace_sha256"]
            or parent["tasks_sha256"] != manifest["parent_tasks_sha256"]
            or parent["task_ids"] != manifest["task_ids"]):
        raise ValueError("Parent provenance mismatch")
    for name, expected in manifest["source_hashes"].items():
        if file_hash(ROOT / name) != expected:
            raise ValueError(f"Replay code changed: {name}")
    return manifest, traces


def replay_row(trace, config):
    options = []
    if trace["status"] == "ok":
        for choice in allowed_sequences(trace["actions"], config):
            options.append({"selected_actions": list(choice),
                            "cost": arm_cost(trace["actions"], choice),
                            **retain_candidates(trace["actions"], choice, config["candidate_cap"], config["rrf_k"])})
    return {"instance_id": trace["instance_id"], "repo": trace["repo"], "base_commit": trace["base_commit"],
            "status": trace["status"], "options": options}


def replay(args):
    manifest, traces = load_run(args.run_dir, args.parent)
    with (args.run_dir / "replay.jsonl").open("x", encoding="utf-8") as output:
        for trace in traces:
            start = time.perf_counter()
            row = replay_row(trace, manifest["config"])
            row["manifest_sha256"] = manifest["manifest_sha256"]
            row["replay_seconds"] = time.perf_counter() - start
            output.write(canonical(row)+"\n")
    print(canonical({"replayed": len(traces), "new_retrieval_calls": 0, "gold_read": False}))


def position(ids, target):
    return ids.index(target) + 1 if target in ids else None


def target_diagnostics(trace, replayed, targets, config):
    result = []
    for target in sorted(targets):
        ranks = {name: next((i for i, item in enumerate(action["candidates"], 1) if item["id"] == target), None)
                 for name, action in trace["actions"].items()}
        options = []
        for option in replayed["options"]:
            sources = ("original", *option["selected_actions"])
            contributions = {name: 1.0 / (config["rrf_k"] + ranks[name]) if ranks.get(name) else 0.0
                             for name in sources}
            full_rank = position(option["full_rrf"], target)
            options.append({"selected_actions": option["selected_actions"],
                            "union_count": len(option["full_rrf"]), "full_rrf_rank": full_rank,
                            "rrf_contributions": contributions,
                            "rrf_retained_rank": position(option["rrf"], target),
                            "round_robin_admission_rank": position(option["round_robin_admission"], target),
                            "round_robin_retained_rank": position(option["round_robin"], target),
                            "rrf_loss_stage": "not_in_selected_action_returns" if full_rank is None else
                                              ("retained" if full_rank <= config["candidate_cap"] else "fusion_truncation")})
        result.append({"target": target, "per_action_rank": ranks, "options": options})
    return result


def score_replay(trace, replayed, targets, config):
    row = {"instance_id": trace["instance_id"], "repo": trace["repo"], "status": trace["status"],
           "gold_count": len(targets), "scorable": bool(targets), "arms": {}}
    if not targets:
        return row
    original = [item["id"] for item in trace["actions"].get("original", {}).get("candidates", [])]
    original_hits = set(original) & targets
    def metrics(order):
        hits = set(order) & targets
        return {"coverage": len(hits)/len(targets), "recall_at_10": len(set(order[:config["final_k"]]) & targets)/len(targets),
                "new_pool_targets": sorted(hits-original_hits), "lost_pool_targets": sorted(original_hits-hits)}
    row["original"] = metrics(original)
    if trace["status"] != "ok":
        for variant in ("rrf", "round_robin"):
            for policy in ("fixed", "oracle"):
                row["arms"][f"{variant}_{policy}"] = {**metrics([]), "selected_actions": []}
        row["targets"] = []
        return row
    fixed = [name for name in ACTIONS if name in config["fixed_actions"] and trace["actions"][name]["available"]]
    fixed_option = next((option for option in replayed["options"] if option["selected_actions"] == fixed), None)
    if fixed_option is None:
        raise ValueError("Fixed policy violates frozen budget")
    for variant in ("rrf", "round_robin"):
        oracle = min(replayed["options"], key=lambda o: (-len(set(o[variant]) & targets), len(o["selected_actions"]), o["selected_actions"]))
        for policy, option in (("fixed", fixed_option), ("oracle", oracle)):
            row["arms"][f"{variant}_{policy}"] = {**metrics(option[variant]),
                                                  "selected_actions": option["selected_actions"], "cost": option["cost"]}
    row["targets"] = target_diagnostics(trace, replayed, targets, config)
    return row


def interval(rows):
    groups = {}
    for row in rows:
        groups.setdefault(row["repo"], []).append(row["arms"]["round_robin_fixed"]["coverage"] - row["arms"]["rrf_fixed"]["coverage"])
    if len(groups) < 2:
        return None
    rng = random.Random(20261102)
    repos = sorted(groups)
    draws = sorted(statistics.mean(value for repo in rng.choices(repos, k=len(repos)) for value in groups[repo]) for _ in range(2000))
    return [draws[int(.025*(len(draws)-1))], draws[int(.975*(len(draws)-1))]]


def evaluate(args):
    manifest, traces = load_run(args.run_dir, args.parent)
    replays = read_rows(args.run_dir / "replay.jsonl")
    if [row["instance_id"] for row in replays] != manifest["task_ids"]:
        raise ValueError("Incomplete or reordered replay")
    # Recompute label-free membership before loading any labels.
    for trace, row in zip(traces, replays):
        if row["manifest_sha256"] != manifest["manifest_sha256"]:
            raise ValueError("Replay manifest mismatch")
        expected = replay_row(trace, manifest["config"])
        if any(row[key] != value for key, value in expected.items()):
            raise ValueError("Replay candidates or costs changed")
    records = read_rows(args.gold)
    gold = {row["instance_id"]: row for row in records}
    if len(gold) != len(records):
        raise ValueError("Duplicate gold IDs")
    scored = []
    for trace, row in zip(traces, replays):
        record = gold.get(trace["instance_id"])
        if record and any(record.get(key) != trace[key] for key in ("repo", "base_commit")):
            raise ValueError("Gold identity mismatch")
        targets = gold_targets(record) if record else set()
        scored.append({**score_replay(trace, row, targets, manifest["config"]),
                       "gold_status": "missing_record" if record is None else ("symbols" if targets else "no_python_symbols")})
    valid = [row for row in scored if row["scorable"]]
    if not valid:
        raise ValueError("No scorable tasks")
    arms = [f"{variant}_{policy}" for variant in ("rrf", "round_robin") for policy in ("fixed", "oracle")]
    means = {arm: {metric: statistics.mean(row["arms"][arm][metric] for row in valid)
                   for metric in ("coverage", "recall_at_10")} for arm in arms}
    summary = {"manifest_sha256": manifest["manifest_sha256"], "replay_sha256": file_hash(args.run_dir / "replay.jsonl"),
               "gold_sha256": file_hash(args.gold), "tasks": len(traces), "scorable_tasks": len(valid),
               "failed_tasks": sum(row["status"] != "ok" for row in traces),
               "missing_gold_records": sum(row["gold_status"] == "missing_record" for row in scored),
               "means": means, "primary_delta": means["round_robin_fixed"]["coverage"]-means["rrf_fixed"]["coverage"],
               "descriptive_repo_bootstrap_95": interval(valid),
               "primary_improved_tasks": [row["instance_id"] for row in valid if row["arms"]["round_robin_fixed"]["coverage"] > row["arms"]["rrf_fixed"]["coverage"]],
               "primary_harmed_tasks": [row["instance_id"] for row in valid if row["arms"]["round_robin_fixed"]["coverage"] < row["arms"]["rrf_fixed"]["coverage"]],
               "new_retrieval_calls": 0, "replay_seconds": sum(row["replay_seconds"] for row in replays),
               "selection_cost_note": "All feasible options replayed for diagnosis; not a deployed selector cost",
               "automatic_expansion": False, "limits": manifest["limits"]}
    with (args.run_dir / "diagnostics.jsonl").open("x", encoding="utf-8") as output:
        for row in scored:
            output.write(canonical(row)+"\n")
    with (args.run_dir / "summary.json").open("x", encoding="utf-8") as output:
        json.dump(summary, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    for command in ("prepare", "replay", "evaluate"):
        parser = sub.add_parser(command)
        parser.add_argument("--parent", type=Path, default=ROOT / "experiments/runs/query-pilot-20261102-v1")
        if command == "prepare":
            parser.add_argument("--out", type=Path, required=True)
        else:
            parser.add_argument("--run-dir", type=Path, required=True)
        if command == "evaluate":
            parser.add_argument("--gold", type=Path, default=ROOT / "data/gold_symbols.jsonl")
    args = ap.parse_args()
    {"prepare": prepare, "replay": replay, "evaluate": evaluate}[args.command](args)


if __name__ == "__main__":
    main()
