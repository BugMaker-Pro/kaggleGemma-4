"""Third view: the model only reorders the ranker's shortlist, then re-scores.

Reranking all 200 pool candidates asks a natural-language cross-encoder to rank
Python source against a bug report from scratch, which is not what it was trained
for. The standard pipeline is narrower: the cheap ranker proposes thirty, the
model reorders them. That is what this measures, at several shortlist widths.

    python tools/analyse_shortlist.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.analyse import bootstrap_ci, sign_test  # noqa: E402

K = 10
WIDTHS = (10, 20, 30, 50, 100)


def recall(order, labels, total) -> float:
    if not total:
        return 0.0
    return sum(1 for index in order[:K] if index < len(labels) and labels[index]) / total


def main() -> int:
    tasks = {row["instance_id"]: row for row in
             (json.loads(line) for line in (ROOT / "data" / "features_full.jsonl").open(encoding="utf-8") if line.strip())}
    model = {row["instance_id"]: row for row in
             (json.loads(line) for line in (ROOT / "data" / "rerank_full_1024.jsonl").open(encoding="utf-8") if line.strip())}
    orders = {row["instance_id"]: row for row in
              (json.loads(line) for line in (ROOT / "data" / "combo_ltr_orders_full.jsonl").open(encoding="utf-8") if line.strip())}

    model_score = {key: dict(zip(row["candidates"], row["scores"])) for key, row in model.items()}
    base, shortlisted = {}, {width: {} for width in WIDTHS}
    for instance_id, task in tasks.items():
        if instance_id not in model or instance_id not in orders:
            continue
        labels = task["labels"]
        total = task.get("gold_total") or sum(labels)
        if not total:
            continue
        ranker = orders[instance_id]["orders"]["ltr"]
        base[instance_id] = recall(ranker, labels, total)
        for width in WIDTHS:
            head = ranker[:width]
            reordered = sorted(head, key=lambda index: -model_score[instance_id].get(index, -1e9))
            shortlisted[width][instance_id] = recall(reordered, labels, total)

    keys = sorted(base)
    print(f"tasks {len(keys)}")
    print(f"{'ranker':22s}{statistics.fmean(base.values()):.3f}")
    for width in WIDTHS:
        deltas = [shortlisted[width][key] - base[key] for key in keys]
        wins = sum(1 for value in deltas if value > 0)
        losses = sum(1 for value in deltas if value < 0)
        lo, hi = bootstrap_ci(deltas)
        print(f"model over ranker top-{width:<4d}{statistics.fmean(shortlisted[width].values()):10.3f}"
              f"   delta {statistics.fmean(deltas):+.3f} ({lo:+.3f},{hi:+.3f}) "
              f"W/L {wins}/{losses} p={sign_test(wins, losses):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

