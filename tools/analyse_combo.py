"""Paired tests and per-repository breakdown for the combined evidence arms.

    python tools/analyse_combo.py
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.analyse import bootstrap_ci, sign_test  # noqa: E402

ARMS = ("combo", "combo3", "combo_body_first", "combo_nofile",
        "combo_cap", "combo_cap_loose")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "experiment_combo.jsonl"))
    args = ap.parse_args(argv)
    rows = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8")
            if line.strip()]
    rows = [row for row in rows if row.get("arms")]
    print(f"scored tasks: {len(rows)}\n")

    print(f"{'arm':18s}{'r@1':>7s}{'r@5':>7s}{'r@10':>7s}{'delta':>8s}"
          f"{'95% CI':>18s}{'W/L':>9s}{'p':>8s}")
    for arm in ARMS:
        deltas, wins, losses = [], 0, 0
        for row in rows:
            delta = row["arms"][arm]["recall@10"] - row["arms"]["text"]["recall@10"]
            deltas.append(delta)
            wins += delta > 0
            losses += delta < 0
        lo, hi = bootstrap_ci(deltas)
        first = statistics.fmean(row["arms"][arm]["recall@1"] for row in rows)
        fifth = statistics.fmean(row["arms"][arm]["recall@5"] for row in rows)
        tenth = statistics.fmean(row["arms"][arm]["recall@10"] for row in rows)
        print(f"{arm:18s}{first:7.3f}{fifth:7.3f}{tenth:7.3f}"
              f"{statistics.fmean(deltas):+8.3f}{(round(lo, 3), round(hi, 3))!s:>18s}"
              f"{wins:5d}/{losses:3d}{sign_test(wins, losses):8.4f}")

    by_repo: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        by_repo[row["repo"]].append(row)
    print(f"\n{'repository':24s}{'n':>4s}{'text':>7s}{'combo':>7s}{'delta':>8s}")
    for repo, group in sorted(by_repo.items(), key=lambda kv: -len(kv[1])):
        text = statistics.fmean(row["arms"]["text"]["recall@10"] for row in group)
        combo = statistics.fmean(row["arms"]["combo"]["recall@10"] for row in group)
        print(f"{repo:24s}{len(group):4d}{text:7.3f}{combo:7.3f}{combo - text:+8.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
