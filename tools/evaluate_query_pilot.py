"""Score frozen query traces offline. This is the only pilot stage reading gold."""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from experiments.coverage import candidate_ids
from experiments.query_pilot import (ACTIONS, TaskInput, allowed_sequences, arm_cost, canonical,
                                    extract_actions, file_hash, load_manifest, merge_actions)


def gold_targets(record):
    """Exact canonical symbols; absent-from-index targets remain in denominator."""
    targets = set()
    for entry in record.get("files", []):
        if entry.get("language") != "python":
            continue
        for symbol in entry.get("symbols", []):
            targets.add(candidate_ids(entry["path"], symbol["qualname"])[0])
    return targets


def validate_row(row, task, manifest):
    if row["manifest_sha256"] != manifest["manifest_sha256"]:
        raise ValueError("Trace belongs to another manifest")
    if any(row[key] != getattr(task, key) for key in ("instance_id", "repo", "base_commit")):
        raise ValueError("Trace task identity mismatch")
    if row["status"] == "error":
        if row["actions"] or not row.get("error"):
            raise ValueError("Malformed failure trace")
        return
    if row["status"] != "ok" or set(row["actions"]) != {"original", *ACTIONS}:
        raise ValueError("Incomplete action trace")
    config = manifest["config"]
    expected = extract_actions(task, config["issue_char_limit"], config["query_char_limit"])
    if row["evidence"] != expected["evidence"]:
        raise ValueError("Evidence differs from sanitized issue")
    for name, result in row["actions"].items():
        query = expected["actions"][name]
        if result["query"] != query["query"] or result["available"] != query.get("available", True):
            raise ValueError("Action query mismatch")
        candidates = result["candidates"]
        ids = [item["id"] for item in candidates]
        if len(ids) > config["per_action_candidates"] or len(ids) != len(set(ids)):
            raise ValueError("Invalid candidate count")
        if any(not math.isfinite(item["score"]) or item["score"] <= 0 for item in candidates):
            raise ValueError("Invalid candidate score")
        if candidates != sorted(candidates, key=lambda item: (-item["score"], item["id"])):
            raise ValueError("Noncanonical action ranking")
        cost = result["cost"]
        if (cost["retrieval_calls"] != int(result["available"])
                or cost["query_chars"] != (len(result["query"]) if result["available"] else 0)
                or not len(candidates) <= cost["scored_documents"] <= row["index_nodes"]):
            raise ValueError("Invalid action accounting")
        if not result["available"] and (candidates or cost["scored_documents"]):
            raise ValueError("Unavailable action produced candidates")
    if row["source_chars"] > config["max_source_chars"] or row["index_nodes"] > config["max_index_nodes"]:
        raise ValueError("Task preprocessing limit exceeded")


def score_order(order, targets, original_top, k):
    hit = set(order) & targets
    top_hit = set(order[:k]) & targets
    return {"coverage": len(hit) / len(targets), "recall_at_10": len(top_hit) / len(targets),
            "coverage_hits": len(hit), "top_hits": len(top_hit),
            "new_top_targets": sorted(top_hit - original_top),
            "lost_top_targets": sorted(original_top - top_hit),
            "candidate_count": len(order)}


def evaluate_row(row, targets, config):
    if not targets:
        return {"scorable": False, "arms": {}}
    if row["status"] != "ok":
        empty = score_order([], targets, set(), config["final_k"])
        return {"scorable": True, "gold_count": len(targets), "failure": True,
                "arms": {key: dict(empty) for key in ("original", "fixed", "oracle")},
                "all_menu_union_coverage": 0.0}
    results = row["actions"]
    feasible = list(allowed_sequences(results, config))
    fixed = tuple(name for name in config["fixed_actions"] if results[name]["available"])
    # Combinations have canonical ACTIONS order.
    fixed = tuple(name for name in ACTIONS if name in fixed)
    if fixed not in feasible or () not in feasible:
        raise ValueError("Frozen baseline exceeds budget")
    orders = {choice: merge_actions(results, choice, config["candidate_cap"], config["rrf_k"])
              for choice in feasible}
    oracle = min(feasible, key=lambda choice: (-len(set(orders[choice]) & targets), len(choice), choice))
    original_top = set(orders[()][:config["final_k"]]) & targets
    arms = {}
    for name, choice in (("original", ()), ("fixed", fixed), ("oracle", oracle)):
        order = orders[choice]
        arms[name] = {**score_order(order, targets, original_top, config["final_k"]),
                      "selected_actions": list(choice), "order": order, "cost": arm_cost(results, choice)}
    union = {item["id"] for result in results.values() for item in result["candidates"]}
    original_pool = set(orders[()])
    return {"scorable": True, "gold_count": len(targets), "failure": False, "arms": arms,
            "original_pool_has_gold": bool(original_pool & targets),
            "fixed_rescues_missing_target": bool((set(orders[fixed]) - original_pool) & targets),
            "oracle_rescues_missing_target": bool((set(orders[oracle]) - original_pool) & targets),
            "all_menu_union_coverage": len(union & targets) / len(targets),
            "all_menu_union_size": len(union),
            "all_menu_diagnostic_cost": arm_cost(results, ACTIONS)}


def paired_interval(rows, replicates, seed):
    groups = defaultdict(list)
    for row in rows:
        groups[row["repo"]].append(row["arms"]["oracle"]["coverage"] - row["arms"]["fixed"]["coverage"])
    if len(groups) < 2:
        return None
    rng = random.Random(seed)
    repos = sorted(groups)
    draws = []
    for _ in range(replicates):
        values = [value for repo in rng.choices(repos, k=len(repos)) for value in groups[repo]]
        draws.append(statistics.mean(values))
    draws.sort()
    return [draws[int(0.025 * (len(draws)-1))], draws[int(0.975 * (len(draws)-1))]]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--gold", type=Path, default=ROOT / "data/gold_symbols.jsonl")
    args = ap.parse_args()
    manifest = load_manifest(args.run_dir)
    for name, expected in manifest["source_hashes"].items():
        if file_hash(ROOT / name) != expected:
            raise ValueError(f"Source changed since preparation: {name}")
    tasks = [TaskInput.from_mapping(json.loads(line)) for line in
             (args.run_dir / "tasks.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    traces = [json.loads(line) for line in (args.run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if [row["instance_id"] for row in traces] != manifest["task_ids"]:
        raise ValueError("Missing, duplicate, reordered or unexpected trace tasks")
    if [task.instance_id for task in tasks] != manifest["task_ids"]:
        raise ValueError("Task list differs from manifest")
    gold = {}
    for line in args.gold.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            if record["instance_id"] in gold:
                raise ValueError("Duplicate gold ID")
            gold[record["instance_id"]] = record
    scored = []
    for task, row in zip(tasks, traces):
        validate_row(row, task, manifest)
        record = gold.get(task.instance_id)
        if record and any(record.get(key) != getattr(task, key) for key in ("repo", "base_commit")):
            raise ValueError("Gold identity mismatch")
        targets = gold_targets(record) if record else set()
        scored.append({"instance_id": task.instance_id, "repo": task.repo, "status": row["status"],
                       "gold_status": "missing_record" if record is None else ("symbols" if targets else "no_python_symbols"),
                       **evaluate_row(row, targets, manifest["config"])})
    valid = [row for row in scored if row["scorable"]]
    if not valid:
        raise ValueError("No scorable tasks")
    means = {arm: {metric: statistics.mean(row["arms"][arm][metric] for row in valid)
                   for metric in ("coverage", "recall_at_10")}
             for arm in ("original", "fixed", "oracle")}
    evaluation = manifest["evaluation"]
    interval = paired_interval(valid, evaluation["bootstrap_replicates"], evaluation["bootstrap_seed"])
    threshold = evaluation["minimum_worthwhile_coverage_delta"]
    gate = "uncertain"
    if interval is not None and interval[1] < threshold:
        gate = "no_worthwhile_fixed_menu_gap_observed"
    elif interval is not None and interval[0] >= threshold:
        gate = "fixed_menu_gap_warrants_further_development"
    summary = {"manifest_sha256": manifest["manifest_sha256"],
               "trace_sha256": file_hash(args.run_dir / "trace.jsonl"), "gold_sha256": file_hash(args.gold),
               "tasks": len(scored), "scorable_tasks": len(valid),
               "failed_tasks": sum(row["status"] != "ok" for row in traces),
               "missing_gold_records": sum(row["gold_status"] == "missing_record" for row in scored),
               "means": means,
               "primary_delta": means["oracle"]["coverage"] - means["fixed"]["coverage"],
               "descriptive_repo_bootstrap_95": interval, "minimum_worthwhile_delta": threshold,
               "gate": gate, "automatic_expansion": False,
               "all_menu_union_coverage": statistics.mean(row["all_menu_union_coverage"] for row in valid),
               "total_execution_seconds": sum(row["total_seconds"] for row in traces),
               "cost_scope": "trace includes preprocessing and all-menu execution; per-arm search costs are replay estimates",
               "limits": manifest["limits"]}
    # Exclusive creation: never replace a previous evaluation.
    with (args.run_dir / "scores.jsonl").open("x", encoding="utf-8") as stream:
        for row in scored:
            stream.write(canonical(row)+"\n")
    with (args.run_dir / "summary.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
