"""What a semantic reranker buys on the same pool, the same ten slots.

Reads the ordering the cross-encoder produced (tools/rerank_model.py) and scores
it exactly like every other arm: task gold total as the denominator, recall@10,
per-task paired differences, bootstrap interval and sign test.

Also reports the two numbers that decide whether the remaining gap is semantic:

  oracle@10   the best any reranker of this pool could do
  by bucket   the gain on tasks whose issue quotes source, names a path, or
              states nothing — the last group is 74% of the benchmark and the
              cheap features move it by five points

    python tools/analyse_rerank.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.analyse import bootstrap_ci, sign_test  # noqa: E402

K = 10


def recall(order, labels, total) -> float:
    if not total:
        return 0.0
    return sum(1 for index in order[:K] if index < len(labels) and labels[index]) / total


def file_recall(order, files, gold_files) -> float:
    if not gold_files:
        return float("nan")
    seen = []
    for index in order[:K]:
        path = files[index] if index < len(files) else ""
        if path and path not in seen:
            seen.append(path)
    return len(set(seen) & set(gold_files)) / len(set(gold_files))


def bucket_of(task: dict) -> str:
    rows, labels = task["rows"], task["labels"]
    for index, label in enumerate(labels):
        if label and rows[index][3]:
            return "quotes"
    for index, label in enumerate(labels):
        if label and (rows[index][4] or rows[index][6] or rows[index][8]):
            return "names"
    return "neither"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
    ap.add_argument("--model", default=str(ROOT / "data" / "rerank_model.jsonl"))
    ap.add_argument("--orders", default=str(ROOT / "data" / "combo_ltr_orders_full.jsonl"))
    args = ap.parse_args(argv)

    tasks = {row["instance_id"]: row for row in
             (json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip())}
    model = {row["instance_id"]: row["candidates"] for row in
             (json.loads(line) for line in Path(args.model).open(encoding="utf-8") if line.strip())}
    orders = {row["instance_id"]: row for row in
              (json.loads(line) for line in Path(args.orders).open(encoding="utf-8") if line.strip())}

    arms = ("bm25", "ranker", "model", "oracle")
    scores: dict[str, dict[str, float]] = {arm: {} for arm in arms}
    file_scores: dict[str, list[float]] = defaultdict(list)
    groups: dict[str, list[str]] = defaultdict(list)

    for instance_id, task in tasks.items():
        if instance_id not in model or instance_id not in orders:
            continue
        labels = task["labels"]
        total = task.get("gold_total") or sum(labels)
        if not total:
            continue
        pool = list(range(len(labels)))
        scores["bm25"][instance_id] = recall(pool, labels, total)
        scores["ranker"][instance_id] = recall(orders[instance_id]["orders"]["ltr"], labels, total)
        scores["model"][instance_id] = recall(model[instance_id], labels, total)
        scores["oracle"][instance_id] = recall(pool, labels, total)
        gold_files = task.get("gold_files") or []
        if gold_files:
            for arm, order in (("ranker", orders[instance_id]["orders"]["ltr"]),
                               ("model", model[instance_id])):
                value = file_recall(order, task["files"], gold_files)
                if value == value:
                    file_scores[arm].append(value)
        groups[bucket_of(task)].append(instance_id)

    print(f"tasks {len(scores['model'])}\n")
    print(f"{'arm':10s}{'symbol r@10':>13s}{'file r@10':>12s}")
    for arm in ("bm25", "ranker", "model"):
        file_value = statistics.fmean(file_scores[arm]) if file_scores[arm] else float("nan")
        print(f"{arm:10s}{statistics.fmean(scores[arm].values()):13.3f}{file_value:12.3f}")
    ceiling = []
    for instance_id, task in tasks.items():
        if instance_id not in model:
            continue
        labels = task["labels"]
        total = task.get("gold_total") or sum(labels)
        if not total:
            continue
        ceiling.append(min(1.0, sum(labels) / total))
    print(f"{'oracle@10':10s}{statistics.fmean(ceiling):13.3f}")

    keys = sorted(scores["model"])
    for left, right in (("model", "ranker"), ("model", "bm25")):
        deltas = [scores[left][key] - scores[right][key] for key in keys]
        wins = sum(1 for value in deltas if value > 0)
        losses = sum(1 for value in deltas if value < 0)
        lo, hi = bootstrap_ci(deltas)
        print(f"{left} - {right}: {statistics.fmean(deltas):+.3f}  CI ({lo:+.3f},{hi:+.3f})  "
              f"W/L {wins}/{losses}  p={sign_test(wins, losses):.4f}")

    print(f"\n{'bucket':10s}{'n':>6s}{'bm25':>8s}{'ranker':>9s}{'model':>8s}{'m-r':>8s}")
    for name in ("quotes", "names", "neither"):
        ids = groups.get(name, [])
        if not ids:
            continue
        row = [statistics.fmean(scores[arm][key] for key in ids) for arm in ("bm25", "ranker", "model")]
        print(f"{name:10s}{len(ids):6d}{row[0]:8.3f}{row[1]:9.3f}{row[2]:8.3f}{row[2] - row[1]:+8.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
