"""Score the dense retriever against BM25 and the learned ranker, paired.

`tools/embed_retrieve.py` writes one line per task with the pool candidates in
cosine order. This turns that into the same numbers every other arm reports --
symbol and file recall@10 with the task's whole gold set as denominator -- and
pairs it with BM25 and with the 16-feature ranker on the same tasks.

    python tools/analyse_embed.py
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


def load(path: Path) -> dict[str, dict]:
    return {row["instance_id"]: row for row in
            (json.loads(line) for line in path.open(encoding="utf-8") if line.strip())}


def recall(order: list[int], labels: list[int], total: int, k: int = 10) -> float:
    if not total:
        return 0.0
    return sum(1 for index in order[:k] if labels[index]) / total


def file_recall(order: list[int], files: list[str], gold_files: list[str], k: int = 10) -> float:
    if not gold_files:
        return 0.0
    seen = []
    for index in order[:k]:
        name = files[index]
        if name and name not in seen:
            seen.append(name)
    return len(set(seen) & set(gold_files)) / len(gold_files)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--embed", default=str(ROOT / "data" / "embed_retrieval.jsonl"))
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
    ap.add_argument("--orders", default=str(ROOT / "data" / "combo_ltr_orders_full.jsonl"))
    args = ap.parse_args(argv)

    embed = load(Path(args.embed))
    rows = load(Path(args.rows))
    orders = load(Path(args.orders)) if Path(args.orders).exists() else {}

    tasks = [iid for iid in embed if iid in rows]
    arms: dict[str, list[float]] = {name: [] for name in ("cosine", "bm25", "ltr")}
    files_arm: dict[str, list[float]] = {name: [] for name in ("cosine", "bm25", "ltr")}
    for iid in tasks:
        row = rows[iid]
        labels, total = row["labels"], row.get("gold_total") or 0
        gold_files = row.get("gold_files") or []
        files = row["files"]
        cosine = embed[iid]["candidates"]
        bm25 = sorted(range(len(labels)), key=lambda i: -row["rows"][i][0])
        ltr = orders.get(iid, {}).get("orders", {}).get("ltr", bm25)
        for name, order in (("cosine", cosine), ("bm25", bm25), ("ltr", ltr)):
            arms[name].append(recall(order, labels, total))
            files_arm[name].append(file_recall(order, files, gold_files))

    print(f"tasks {len(tasks)}")
    for name in ("bm25", "ltr", "cosine"):
        symbol = statistics.fmean(arms[name])
        file = statistics.fmean(files_arm[name])
        print(f"  {name:7s} symbol {symbol:.4f}  file {file:.4f}  gap {file / symbol:.2f}x")

    for base, label in (("bm25", "cosine - bm25"), ("ltr", "cosine - ltr")):
        deltas = [a - b for a, b in zip(arms["cosine"], arms[base])]
        wins = sum(1 for d in deltas if d > 1e-9)
        losses = sum(1 for d in deltas if d < -1e-9)
        lo, hi = bootstrap_ci(deltas)
        print(f"  {label:14s} {statistics.fmean(deltas):+.4f}  CI ({lo:+.3f},{hi:+.3f})  "
              f"W/L {wins}/{losses}  p={sign_test(wins, losses):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
