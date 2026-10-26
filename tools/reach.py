"""Reach and conversion diagnostics from the ablation/diffusion JSONL.

    python tools/reach.py data/ablation.jsonl          # per-repo s5h1 / s5h2
    python tools/reach.py data/experiment_v3.jsonl     # ball sizes, conversion
"""

from __future__ import annotations

import collections
import json
import statistics
import sys
from pathlib import Path


def per_repo_reach(rows: list[dict]) -> None:
    by_repo: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        if row.get("headroom"):
            by_repo[row.get("repo", "?")].append(row)
    print(f"{'repository':24s}{'n':>4s}{'s5h1':>8s}{'s5h2':>8s}{'zero':>6s}")
    for repo, entries in sorted(by_repo.items(), key=lambda kv: -len(kv[1])):
        one = [row["headroom"].get("s5h1", 0.0) for row in entries]
        two = [row["headroom"].get("s5h2", 0.0) for row in entries]
        print(f"{repo:24s}{len(entries):4d}{sum(one) / len(one):8.3f}"
              f"{sum(two) / len(two):8.3f}"
              f"{sum(1 for value in one if value == 0):6d}")
    one = [row["headroom"].get("s5h1", 0.0) for row in rows if row.get("headroom")]
    two = [row["headroom"].get("s5h2", 0.0) for row in rows if row.get("headroom")]
    print(f"{'all':24s}{len(one):4d}{sum(one) / len(one):8.3f}{sum(two) / len(two):8.3f}"
          f"{sum(1 for value in one if value == 0):6d}")


def conversion(rows: list[dict]) -> None:
    """The question the paper's mechanism claim rests on.

    For tasks whose gold symbol is one hop from a strong seed (so the graph can
    reach it), where does the best graph arm actually put it?
    """
    scored = [row for row in rows if row.get("ball")]
    sizes = [row["ball"]["size1"] for row in scored]
    golds = [row["ball"]["gold1"] for row in scored]
    print(f"tasks with a ball: {len(scored)}")
    print(f"ball size: median {statistics.median(sizes):.0f} mean {sum(sizes) / len(sizes):.1f}")
    print(f"gold in ball: {sum(golds)} symbols over {sum(1 for g in golds if g)} tasks")
    print(f"they are {sum(golds) / max(sum(sizes), 1):.4%} of ball members")
    reachable = [row for row in scored if row["ball"]["gold1"]]
    print(f"tasks with a reachable gold: {len(reachable)} ({len(reachable) / len(scored):.1%})")
    hit = 0
    ranks = []
    for row in reachable:
        found = [rank for rank in row["ball"]["gold1_ppr_rank"] if rank]
        if found and min(found) <= 10:
            hit += 1
        ranks.extend(found)
    print(f"of those, best graph arm puts one in its top 10: {hit}"
          f" ({hit / max(len(reachable), 1):.1%})")
    if ranks:
        print(f"gold rank under diffusion: median {statistics.median(ranks):.0f}"
              f" max {max(ranks)}")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = Path(argv[0] if argv else "data/ablation.jsonl")
    rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
    if any(row.get("headroom") for row in rows):
        per_repo_reach(rows)
    if any(row.get("ball") for row in rows):
        conversion(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
