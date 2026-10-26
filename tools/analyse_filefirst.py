"""Paired tests for the file-first arms against symbol-level BM25.

    python tools/analyse_filefirst.py
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

ARMS = ("text", "ff_k1", "ff_k2", "ff_k3", "ff_k5", "ff_graph", "file_oracle")


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def paired(rows: list[dict], arm: str, metric: str) -> dict:
    deltas, wins, losses, ties = [], 0, 0, 0
    for row in rows:
        base = row["arms"]["text"][metric]
        value = row["arms"][arm][metric]
        delta = value - base
        deltas.append(delta)
        if delta > 0:
            wins += 1
        elif delta < 0:
            losses += 1
        else:
            ties += 1
    lo, hi = bootstrap_ci(deltas)
    return {
        "delta": statistics.fmean(deltas),
        "ci": (round(lo, 3), round(hi, 3)),
        "wins": wins, "losses": losses, "ties": ties,
        "p": round(sign_test(wins, losses), 3),
        "graph": statistics.fmean(row["arms"][arm][metric] for row in rows),
        "text": statistics.fmean(row["arms"]["text"][metric] for row in rows),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "experiment_ff.jsonl"))
    args = ap.parse_args(argv)
    rows = [row for row in load(Path(args.rows)) if row.get("arms")]
    print(f"scored tasks: {len(rows)}\n")

    print(f"{'arm':14s}{'r@1':>7s}{'r@5':>7s}{'r@10':>7s}{'f@5':>7s}{'f@10':>7s}{'chars':>8s}")
    for arm in ARMS:
        def mean(metric):
            return statistics.fmean(row["arms"][arm][metric] for row in rows)
        print(f"{arm:14s}{mean('recall@1'):7.3f}{mean('recall@5'):7.3f}"
              f"{mean('recall@10'):7.3f}{mean('file_recall@5'):7.3f}"
              f"{mean('file_recall@10'):7.3f}{mean('chars@10'):8.0f}")

    print("\n== paired against text ==")
    print(f"{'arm':14s}{'metric':10s}{'delta':>8s}{'95% CI':>20s}{'W/L/T':>12s}{'p':>7s}")
    for arm in ARMS[1:]:
        for metric in ("recall@10", "recall@5", "file_recall@10"):
            stats = paired(rows, arm, metric)
            print(f"{arm:14s}{metric:10s}{stats['delta']:+8.3f}"
                  f"{str(stats['ci']):>20s}"
                  f"{stats['wins']:5d}/{stats['losses']:3d}/{stats['ties']:3d}"
                  f"{stats['p']:7.3f}")

    print("\n== where stage 1 stands ==")
    in3 = statistics.fmean(row["stage1"]["gold_in_top3"] for row in rows)
    in5 = statistics.fmean(row["stage1"]["gold_in_top5"] for row in rows)
    print(f"gold file in the top-3 file ranking: {in3:.3f}")
    print(f"gold file in the top-5 file ranking: {in5:.3f}")

    # How much of the gap does the file signal explain?
    text10 = statistics.fmean(row["arms"]["text"]["recall@10"] for row in rows)
    oracle10 = statistics.fmean(row["arms"]["file_oracle"]["recall@10"] for row in rows)
    best = max(ARMS[1:], key=lambda arm: statistics.fmean(
        row["arms"][arm]["recall@10"] for row in rows))
    best10 = statistics.fmean(row["arms"][best]["recall@10"] for row in rows)
    print(f"\ntext r@10 {text10:.3f} -> best file-first ({best}) {best10:.3f} "
          f"-> perfect stage 1 {oracle10:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
