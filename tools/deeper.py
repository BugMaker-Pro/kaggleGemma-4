"""Paired deltas at an arbitrary k, for arms whose advantage grows deeper in the list.

The paper's budget is ten slots, but the curves keep climbing past it, so the
question "does reranking help if you can afford twenty?" needs its own number.

    python tools/deeper.py --k 20
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

ARMS = ("graph_rerank", "graph_open", "graph_open2", "graph_fuse", "graph_ppr")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "experiment_v3.jsonl"))
    ap.add_argument("--k", type=int, default=20)
    args = ap.parse_args(argv)

    rows = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8")
            if line.strip()]
    rows = [row for row in rows if row.get("arms")]
    k = args.k
    print(f"paired at k = {k}, tasks = {len(rows)}")
    print(f"{'arm':18s}{'text':>8s}{'graph':>8s}{'delta':>8s}{'95% CI':>20s}{'W/L/T':>12s}{'p':>7s}")
    base = []
    for row in rows:
        top = set(row["arms"]["text"]["top"][:k])
        gold = set(row["gold_nodes"])
        base.append(len(top & gold) / len(gold))
    for arm in ARMS:
        deltas, wins, losses, ties = [], 0, 0, 0
        values = []
        for row, text_recall in zip(rows, base):
            top = set(row["arms"][arm]["top"][:k])
            gold = set(row["gold_nodes"])
            value = len(top & gold) / len(gold)
            values.append(value)
            delta = value - text_recall
            deltas.append(delta)
            if delta > 0:
                wins += 1
            elif delta < 0:
                losses += 1
            else:
                ties += 1
        lo, hi = bootstrap_ci(deltas)
        print(f"{arm:18s}{statistics.fmean(base):8.3f}{statistics.fmean(values):8.3f}"
              f"{statistics.fmean(deltas):+8.3f}{(round(lo, 3), round(hi, 3))!s:>20s}"
              f"{wins:5d}/{losses:3d}/{ties:3d}{sign_test(wins, losses):7.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
