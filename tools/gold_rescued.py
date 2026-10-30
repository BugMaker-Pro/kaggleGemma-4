"""BM25 rank of the repaired gold on the seven tasks the shipped rule dropped."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.buildgraph import module_of  # noqa: E402


def as_id(symbol: str) -> str:
    path, qualname = symbol.split("::", 1)
    return f"{module_of(path)}.{qualname}"


def main() -> int:
    fixed = {row["instance_id"]: row
             for row in (json.loads(line) for line in (ROOT / "data" / "gold_fixed.jsonl").open(encoding="utf-8") if line.strip())}
    rows = [json.loads(line) for line in (ROOT / "data" / "_rescued_feat.jsonl").open(encoding="utf-8") if line.strip()]
    total = 0.0
    for row in rows:
        gold = {as_id(symbol) for symbol in fixed[row["instance_id"]]["gold_c"]}
        ids = row["ids"]
        labels = [1 if node in gold else 0 for node in ids]
        order = sorted(range(len(ids)), key=lambda i: -row["rows"][i][0])
        ranks = [order.index(i) for i in range(len(ids)) if labels[i]]
        best = min(ranks) if ranks else None
        total += (1.0 if best is not None and best < 10 else 0.0) / max(len(gold), 1)
        print(f"{row['instance_id']:34s} gold {len(gold)}  in pool {sum(labels)}  bm25 rank {best}")
    print(f"\nBM25 recall@10 over these {len(rows)}: {total / len(rows):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
