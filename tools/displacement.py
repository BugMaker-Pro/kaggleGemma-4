"""Gain/loss accounting: what a graph arm adds and what it displaces.

The paper's mechanism claim is an arithmetic one, so it should be an arithmetic
number: of the gold symbols a graph arm finds that text missed, how many does it
actually surface, and how many text hits does it drop to pay for them?

    python tools/displacement.py data/experiment_v3.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ARMS = ("graph_rerank", "graph_open", "graph_open2", "graph_fuse",
        "graph_fuse_precise", "graph_ppr", "graph_ppr_text")


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "experiment_v3.jsonl"))
    ap.add_argument("--k", type=int, default=10)
    args = ap.parse_args(argv)

    rows = [row for row in load(Path(args.rows)) if row.get("arms")]
    k = args.k
    base = {}
    for row in rows:
        top = row["arms"]["text"]["top"][:k]
        base[row["instance_id"]] = (set(top), set(row["gold_nodes"]))

    print(f"budget k = {k}, tasks = {len(rows)}")
    print(f"{'arm':20s}{'gained':>8s}{'lost':>7s}{'tasks +':>9s}{'tasks -':>9s}"
          f"{'net sym':>9s}")
    for arm in ARMS:
        if arm not in rows[0]["arms"]:
            continue
        gained = lost = 0
        plus = minus = 0
        for row in rows:
            top = set(row["arms"][arm]["top"][:k])
            text_top, gold = base[row["instance_id"]]
            gold = gold & (top | text_top)
            add = len((gold & top) - text_top)
            drop = len((gold & text_top) - top)
            gained += add
            lost += drop
            plus += 1 if add > drop else 0
            minus += 1 if drop > add else 0
        print(f"{arm:20s}{gained:8d}{lost:7d}{plus:9d}{minus:9d}{gained - lost:+9d}")

    # Conversion: of the gold symbols only the graph could have reached, how many
    # does the graph actually put in the shortlist?
    reachable = [row for row in rows if row.get("ball") and row["ball"]["gold1"]]
    ranks = [rank for row in reachable for rank in row["ball"]["gold1_ppr_rank"]]
    print(f"\nreachable-by-graph gold symbols: {len(ranks)} over {len(reachable)} tasks")
    print(f"  in diffusion's top {k}: {sum(1 for r in ranks if 0 < r <= k)}")
    print(f"  median rank: {statistics.median(ranks):.0f}")
    print(f"  share of all 354 gold symbols: {len(ranks) / 354:.1%}")
    print(f"  even at perfect conversion this bounds the arm at "
          f"+{len(ranks) / 354:.3f} recall@10")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
