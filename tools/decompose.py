"""Recall@10 as a product: P(gold file reachable at this breadth) x recovery(depth).

Every allocation of the ten slots sits somewhere on this curve: pick more files
and each file gets fewer slots. If the product is roughly constant across
allocations, then re-arranging the same ten slots cannot help, and the way out
is to raise the first factor (file precision), not the second.

    python tools/decompose.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# arm, the stored stage-1 rank field, how many files that arm is allowed
ARMS = (
    ("ff_k1", "gold_file_rank_3", 1),
    ("ff_k2", "gold_file_rank_3", 2),
    ("ff_k3", "gold_file_rank_3", 3),
    ("ff_k5", "gold_file_rank_5", 5),
)


def recall(row: dict, arm: str, k: int = 10) -> float:
    top = set(row["arms"][arm]["top"][:k])
    gold = set(row["gold_nodes"])
    return len(top & gold) / len(gold)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "experiment_ff.jsonl"))
    args = ap.parse_args(argv)
    rows = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8")
            if line.strip()]
    rows = [row for row in rows if row.get("arms")]

    head = f"{'arm':10s}{'slots/file':>11s}{'P(file found)':>15s}{'recovery':>10s}{'product':>9s}{'measured':>9s}"
    print(head)
    print("-" * len(head))
    for arm, key, files in ARMS:
        subset = [row for row in rows if 1 <= row["stage1"][key] <= files]
        probability = len(subset) / len(rows)
        recovery = statistics.fmean(recall(row, arm) for row in subset)
        measured = statistics.fmean(recall(row, arm) for row in rows)
        print(f"{arm:10s}{10 / files:11.1f}{probability:15.3f}{recovery:10.3f}"
              f"{probability * recovery:9.3f}{measured:9.3f}")

    text_measured = statistics.fmean(recall(row, "text") for row in rows)
    in10 = statistics.fmean(row["arms"]["text"]["file_recall@10"] for row in rows)
    fallback = [row for row in rows if row["arms"]["text"]["file_recall@10"] != 0]
    recovery = statistics.fmean(recall(row, "text") for row in fallback)
    modules = statistics.fmean(
        len({node_id.rsplit(".", 1)[0] for node_id in row["arms"]["text"]["top"][:10]})
        for row in rows)
    print(f"{'text':10s}{10 / modules:11.1f}{in10:15.3f}{recovery:10.3f}"
          f"{in10 * recovery:9.3f}{text_measured:9.3f}   (~{modules:.1f} modules in ten slots)")

    print(f"\nceiling with stage 1 perfect: "
          f"{statistics.fmean(recall(row, 'file_oracle') for row in rows):.3f}")
    ranks = [row["stage1"]["gold_file_rank_3"] for row in rows]
    print(f"gold file ranked first by the file score: "
          f"{sum(1 for r in ranks if r == 1) / len(ranks):.3f}")
    print(f"mean reciprocal rank of the gold file: "
          f"{statistics.fmean(1 / r if r else 0.0 for r in ranks):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
