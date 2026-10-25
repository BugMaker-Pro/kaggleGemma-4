"""Print the ablation tables from data/ablation.jsonl.

    python tools/analyse_ablation.py
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


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def mean(values) -> float:
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else float("nan")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "ablation.jsonl"))
    args = ap.parse_args(argv)

    rows = [row for row in load(Path(args.rows)) if row.get("gold_nodes")]
    print(f"rows with gold symbols: {len(rows)}")

    print("\n== pool size sensitivity ==")
    print(f"{'pool':>6s} {'pool recall':>12s}")
    for size in sorted(rows[0]["pool_recall"], key=int):
        print(f"{size:>6s} {mean(r['pool_recall'][size] for r in rows):12.3f}")

    print("\n== headroom: is the gold symbol within k hops of the top-n seeds? ==")
    seeds = sorted({key.split("h")[0] for key in rows[0]["headroom"]},
                   key=lambda s: int(s[1:]))
    print(f"{'seeds':>6s} {'1 hop':>8s} {'2 hops':>8s}")
    for seed in seeds:
        one = mean(r["headroom"].get(f"{seed}h1") for r in rows)
        two = mean(r["headroom"].get(f"{seed}h2") for r in rows)
        print(f"{seed[1:]:>6s} {one:8.3f} {two:8.3f}")

    print("\n== text recall@10 vs. the two conditions for a graph gain ==")
    text10 = mean(r["text"]["10"] for r in rows)
    print(f"text recall@10: {text10:.3f}")

    miss_pool = [r for r in rows if r["pool_recall"]["500"] == 0.0]
    miss_but_adjacent = [r for r in miss_pool if r["headroom"].get("s5h1", 0) > 0]
    print(f"tasks whose gold symbols never enter the top-500 pool: {len(miss_pool)} "
          f"({len(miss_pool) / len(rows):.1%})")
    print(f"  of those, still one hop from a top-5 seed: {len(miss_but_adjacent)} "
          f"({len(miss_but_adjacent) / max(len(miss_pool), 1):.1%})  <- the graph's only win case")

    print("\n== expansion arms at rank 10 ==")
    print(f"{'arm':>18s} {'r@10':>7s} {'delta':>8s} {'95% CI':>18s} {'W/L':>8s} {'p':>6s}")
    for key in ("1", "3", "5", "10"):
        deltas = [r["open_h1"][key] - r["text"]["10"] for r in rows if key in r["open_h1"]]
        wins = sum(1 for d in deltas if d > 0)
        losses = sum(1 for d in deltas if d < 0)
        lo, hi = bootstrap_ci(deltas)
        print(f"{'open_h1 s=' + key:>18s} {mean(r['open_h1'][key] for r in rows):7.3f} "
              f"{mean(deltas):+8.3f} {str((round(lo, 3), round(hi, 3))):>18s} "
              f"{wins:3d}/{losses:3d} {sign_test(wins, losses):6.3f}")

    for key in ("s5h2", "s10h2"):
        deltas = [r["open_multi_hop"][key] - r["text"]["10"] for r in rows
                  if key in r["open_multi_hop"]]
        wins = sum(1 for d in deltas if d > 0)
        losses = sum(1 for d in deltas if d < 0)
        lo, hi = bootstrap_ci(deltas)
        print(f"{'open_h2 ' + key:>18s} "
              f"{mean(r['open_multi_hop'][key] for r in rows):7.3f} "
              f"{mean(deltas):+8.3f} {str((round(lo, 3), round(hi, 3))):>18s} "
              f"{wins:3d}/{losses:3d} {sign_test(wins, losses):6.3f}")

    print("\n== fusion weight sensitivity ==")
    print(f"{'weight':>7s} {'r@1':>7s} {'r@5':>7s} {'r@10':>7s} {'delta r@10':>11s}")
    for weight in sorted(rows[0]["fuse_weight"], key=float):
        r1 = mean(r["fuse_weight"][weight]["recall@1"] for r in rows)
        r5 = mean(r["fuse_weight"][weight]["recall@5"] for r in rows)
        r10 = mean(r["fuse_weight"][weight]["recall@10"] for r in rows)
        print(f"{weight:>7s} {r1:7.3f} {r5:7.3f} {r10:7.3f} {r10 - text10:+11.3f}")

    print("\n== per repo: text vs best expansion (s=5, 1 hop) ==")
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row.get("repo", "?"), []).append(row)
    print(f"{'repo':28s} {'n':>3s} {'text@10':>8s} {'open@10':>8s} {'head (s5h1)':>12s}")
    for repo, group in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"{repo:28s} {len(group):3d} "
              f"{mean(r['text']['10'] for r in group):8.3f} "
              f"{mean(r['open_h1']['5'] for r in group):8.3f} "
              f"{mean(r['headroom'].get('s5h1', 0) for r in group):12.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
