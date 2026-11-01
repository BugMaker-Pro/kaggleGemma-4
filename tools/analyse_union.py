"""What does a whole-repository dense index buy: pool coverage, ceiling, and a fused ranking.

`embed_retrieve_full.py` embeds every definition in the snapshot and keeps the top
300 by cosine. This compares three pools on the same tasks:

  bm25    the 200 candidates the paper ranks
  dense   the 300 a dense index over the whole repository finds
  union   bm25 + the dense top 200

and reports the gold-in-pool rate (the ceiling a reranker cannot pass), the
oracle recall at ten, and what a plain 50/50 score fusion reaches.

    python tools/analyse_union.py
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

DENSE_TOP = 200


def load(path: Path) -> dict[str, dict]:
    return {row["instance_id"]: row for row in
            (json.loads(line) for line in path.open(encoding="utf-8") if line.strip())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--embed", default=str(ROOT / "data" / "embed_full_lite.jsonl"))
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
    args = ap.parse_args(argv)

    embed = load(Path(args.embed))
    rows = load(Path(args.rows))
    tasks = [iid for iid in embed if iid in rows]
    print(f"tasks {len(tasks)}")

    stats: dict[str, list[float]] = {key: [] for key in
                                     ("bm25_hit", "dense_hit", "union_hit",
                                      "bm25_oracle", "union_oracle",
                                      "fusion", "cosine_union", "bm25_union")}
    skipped = 0
    for iid in tasks:
        row, dense = rows[iid], embed[iid]
        total = row.get("gold_total") or 0
        if not total:
            skipped += 1
            continue
        ids, labels = row["ids"], row["labels"]
        index = {node_id: position for position, node_id in enumerate(ids)}
        gold = {node_id for node_id, label in zip(ids, labels) if label}
        pool = set(ids)
        dense_ids = dense["ids"][:DENSE_TOP]
        union = pool | set(dense_ids)

        stats["bm25_hit"].append(1.0 if gold & pool else 0.0)
        stats["dense_hit"].append(1.0 if gold & set(dense_ids) else 0.0)
        stats["union_hit"].append(1.0 if gold & union else 0.0)
        stats["bm25_oracle"].append(min(len(gold & pool), 10) / total)
        stats["union_oracle"].append(min(len(gold & union), 10) / total)

        bm25_raw = {node_id: row["rows"][index[node_id]][0] for node_id in ids}
        cosine = {node_id: score for node_id, score in zip(dense["ids"], dense["scores"])}
        best_bm25 = max(bm25_raw.values()) or 1.0
        best_cos = max(cosine.values()) or 1.0
        fused = {node_id: 0.5 * (bm25_raw.get(node_id, 0.0) / best_bm25)
                 + 0.5 * (cosine.get(node_id, 0.0) / best_cos) for node_id in union}
        for name, values in (("fusion", fused), ("cosine_union", cosine), ("bm25_union", bm25_raw)):
            order = sorted(values, key=lambda node_id: -values[node_id])[:10]
            stats[name].append(sum(1 for node_id in order if node_id in gold) / total)

    for name in ("bm25_hit", "dense_hit", "union_hit",
                 "bm25_oracle", "union_oracle", "bm25_union", "cosine_union", "fusion"):
        print(f"  {name:14s} {statistics.fmean(stats[name]):.4f}")

    for name in ("cosine_union", "fusion"):
        deltas = [a - b for a, b in zip(stats[name], stats["bm25_union"])]
        wins = sum(1 for d in deltas if d > 1e-9)
        losses = sum(1 for d in deltas if d < -1e-9)
        lo, hi = bootstrap_ci(deltas)
        print(f"  {name} - bm25_union {statistics.fmean(deltas):+.4f}  "
              f"CI ({lo:+.3f},{hi:+.3f})  W/L {wins}/{losses}  p={sign_test(wins, losses):.4f}")
    if skipped:
        print(f"  (skipped {skipped} tasks without a gold count)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
