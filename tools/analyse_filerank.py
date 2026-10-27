"""Paired tests for the file-ranking arms.

    python tools/analyse_filerank.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.analyse import bootstrap_ci, sign_test  # noqa: E402

ARMS = ("text", "fr_max", "fr_sum3", "fr_path", "fr_ppr", "fr_borda",
        "fr_borda_k2", "fr_borda_mix")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "experiment_fr.jsonl"))
    args = ap.parse_args(argv)
    rows = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8")
            if line.strip()]
    rows = [row for row in rows if row.get("arms")]
    print(f"scored tasks: {len(rows)}\n")

    print(f"{'arm':14s}{'r@1':>7s}{'r@5':>7s}{'r@10':>7s}{'f@10':>7s}{'chars':>8s}")
    for arm in ARMS:
        def mean(metric):
            return statistics.fmean(row["arms"][arm][metric] for row in rows)
        print(f"{arm:14s}{mean('recall@1'):7.3f}{mean('recall@5'):7.3f}"
              f"{mean('recall@10'):7.3f}{mean('file_recall@10'):7.3f}"
              f"{mean('chars@10'):8.0f}")

    print("\n== paired against text ==")
    print(f"{'arm':14s}{'metric':10s}{'delta':>8s}{'95% CI':>20s}{'W/L/T':>12s}{'p':>7s}")
    for arm in ARMS[1:]:
        deltas, wins, losses, ties = [], 0, 0, 0
        for row in rows:
            delta = row["arms"][arm]["recall@10"] - row["arms"]["text"]["recall@10"]
            deltas.append(delta)
            if delta > 0:
                wins += 1
            elif delta < 0:
                losses += 1
            else:
                ties += 1
        lo, hi = bootstrap_ci(deltas)
        print(f"{arm:14s}{'recall@10':10s}{statistics.fmean(deltas):+8.3f}"
              f"{(round(lo, 3), round(hi, 3))!s:>20s}"
              f"{wins:5d}/{losses:3d}/{ties:3d}{sign_test(wins, losses):7.3f}")

    print("\n== stage 1: how well does each signal rank the gold file ==")
    print(f"{'signal':8s}{'top1':>7s}{'top3':>7s}{'mrr':>7s}")
    for signal in ("max", "sum3", "path", "ppr", "borda"):
        top1 = statistics.fmean(row["stage1"][signal]["top1"] for row in rows)
        top3 = statistics.fmean(row["stage1"][signal]["top3"] for row in rows)
        mrr = statistics.fmean(row["stage1"][signal]["rr"] for row in rows)
        print(f"{signal:8s}{top1:7.3f}{top3:7.3f}{mrr:7.3f}")

    print("\n== conditional on the gold file being ranked first ==")
    subset = [row for row in rows if row["stage1"]["borda"]["top1"]]
    print(f"tasks: {len(subset)}")
    for arm in ("text", "fr_max", "fr_borda"):
        value = statistics.fmean(row["arms"][arm]["recall@10"] for row in subset)
        print(f"  {arm:10s} r@10 {value:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
