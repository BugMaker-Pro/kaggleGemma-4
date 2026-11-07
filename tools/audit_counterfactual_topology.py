"""Audit saved contrastive-topology rankings against frozen contexts."""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPRESENTATIONS = ("metadata", "body", "dense")
ARMS = ("base", "real", "denoised", "scored")


def read(path):
    return [json.loads(line) for line in Path(path).open(encoding="utf-8") if line.strip()]


def close(left, right, tolerance=1e-12):
    return abs(left - right) <= tolerance


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", default=ROOT / "data/contrastive_topology_scores.jsonl")
    parser.add_argument("--context", default=ROOT / "data/graph_controls_context.jsonl")
    args = parser.parse_args(argv)
    contexts = {row["instance_id"]: row for row in read(args.context)}
    rows = read(args.rows)
    expected = {(instance_id, representation) for instance_id in contexts
                for representation in REPRESENTATIONS}
    actual = {(row["instance_id"], row["representation"]) for row in rows}
    if len(rows) != len(actual) or actual != expected:
        raise ValueError("duplicate or incomplete result population")
    checks = 0
    for row in rows:
        context = contexts[row["instance_id"]]
        for arm in ARMS:
            order = row[arm + "_top10"]
            if len(order) != 10 or len(set(order)) != 10 or any(i < 0 or i >= len(context["ids"]) for i in order):
                raise ValueError(f"invalid shortlist: {row['instance_id']} {row['representation']} {arm}")
            symbol = sum(context["labels"][candidate] for candidate in order) / context["gold_total"]
            gold_files = set(context.get("gold_files") or [])
            files = {context["files"][candidate] for candidate in order}
            file_score = len(files & gold_files) / len(gold_files) if gold_files else 0.0
            if not close(symbol, row[arm + "_symbol"]) or not close(file_score, row[arm + "_file"]):
                raise ValueError(f"metric mismatch: {row['instance_id']} {row['representation']} {arm}")
            checks += 2
    summary = {}
    for representation in REPRESENTATIONS:
        subset = [row for row in rows if row["representation"] == representation]
        summary[representation] = {arm: statistics.fmean(row[arm + "_symbol"] for row in subset)
                                   for arm in ARMS}
    if round(summary["body"]["base"], 4) != 0.3171 or round(summary["body"]["denoised"], 4) != 0.3195:
        raise ValueError("published body-denoising result changed")
    print(f"{len(contexts)} tasks; {len(rows)} representation rows; {checks} metric checks")
    for representation in REPRESENTATIONS:
        print(representation, " ".join(f"{arm}={summary[representation][arm]:.4f}" for arm in ARMS))
    print("0 failures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
