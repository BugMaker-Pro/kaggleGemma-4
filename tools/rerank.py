"""Stage 2: rerank each BM25 pool with a cross-encoder, then measure both.

The paper's open question is whether a stronger *ranking* would give the graph
room. This reranks the same 200 candidates with a 22M-parameter cross-encoder
(no retrieval change, no new candidates) and reports symbol and file recall for
the BM25 order, the reranked order, and a file-vote mix on top of the reranked
order.

    python tools/rerank.py --pools data/pools.jsonl --out data/reranked.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import torch  # noqa: E402
from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402

MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def recall(order: list[str], gold: set[str], k: int) -> float:
    return len(set(order[:k]) & gold) / len(gold) if gold else float("nan")


def file_recall(order: list[str], files_of: dict[str, str], gold_files: set[str],
                k: int) -> float:
    if not gold_files:
        return float("nan")
    seen: list[str] = []
    for node_id in order:
        path = files_of.get(node_id, "")
        if path and path not in seen:
            seen.append(path)
        if len(seen) >= k:
            break
    return len(set(seen[:k]) & gold_files) / len(gold_files)


def file_vote(order: list[str], files_of: dict[str, str]) -> list[str]:
    """Rank files by their best reranked symbol, then five slots deep, five spread."""
    best: dict[str, int] = {}
    for position, node_id in enumerate(order):
        path = files_of.get(node_id, "")
        if path and path not in best:
            best[path] = position
    top_file = min(best, key=lambda path: best[path]) if best else ""
    deep = [node for node in order if files_of.get(node, "") == top_file][:5]
    out = list(dict.fromkeys(deep))
    seen = set(out)
    for node in order:
        if len(out) >= 10:
            break
        if node not in seen:
            out.append(node)
            seen.add(node)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pools", default=str(ROOT / "data" / "pools.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "data" / "reranked.jsonl"))
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    rows = [json.loads(line) for line in Path(args.pools).open(encoding="utf-8")
            if line.strip() and "pool" in line]
    if args.limit:
        rows = rows[: args.limit]

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(args.model)
    model.eval()
    torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))

    started = time.time()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    totals = {"text@10": [], "ce@10": [], "mix@10": [], "text_f10": [],
              "ce_f10": [], "mix_f10": []}

    with out.open("w", encoding="utf-8") as fh, torch.no_grad():
        for index, row in enumerate(rows, 1):
            pool: list[str] = row["pool"]
            docs: dict[str, str] = row["docs"]
            files_of: dict[str, str] = row["files_of"]
            gold = set(row["gold_nodes"])
            gold_files = set(row["gold_files"])
            query = row["query"]

            scores: list[float] = []
            for start in range(0, len(pool), args.batch):
                chunk = pool[start:start + args.batch]
                pairs = [(query, docs.get(node, "")) for node in chunk]
                inputs = tokenizer([p[0] for p in pairs], [p[1] for p in pairs],
                                   padding=True, truncation=True, max_length=512,
                                   return_tensors="pt")
                logits = model(**inputs).logits.view(-1)
                scores.extend(float(value) for value in logits)

            order = [node for _, node in sorted(zip(scores, pool), key=lambda kv: -kv[0])]
            mix = file_vote(order, files_of)

            totals["text@10"].append(recall(pool, gold, 10))
            totals["ce@10"].append(recall(order, gold, 10))
            totals["mix@10"].append(recall(mix, gold, 10))
            totals["text_f10"].append(file_recall(pool, files_of, gold_files, 10))
            totals["ce_f10"].append(file_recall(order, files_of, gold_files, 10))
            totals["mix_f10"].append(file_recall(mix, files_of, gold_files, 10))

            fh.write(json.dumps({
                "instance_id": row["instance_id"], "repo": row.get("repo", ""),
                "gold_nodes": row["gold_nodes"], "gold_files": row["gold_files"],
                "files_of": files_of, "order": order, "mix": mix,
            }, ensure_ascii=False) + "\n")
            fh.flush()

            if index % 20 == 0 or index == len(rows):
                elapsed = time.time() - started
                print(f"  {index}/{len(rows)}  {index / elapsed:.1f} task/s  "
                      f"eta {(len(rows) - index) / max(index / elapsed, 1e-9) / 60:.1f} min",
                      flush=True)

    def mean(values):
        values = [v for v in values if v == v]
        return sum(values) / len(values) if values else float("nan")

    print(f"\ntasks {len(rows)}  {round(time.time() - started, 1)}s")
    print(f"{'ranking':12s}{'symbol@10':>11s}{'file@10':>9s}")
    for name, symbol_key, file_key in (("BM25", "text@10", "text_f10"),
                                       ("cross-enc", "ce@10", "ce_f10"),
                                       ("CE + 5/5", "mix@10", "mix_f10")):
        print(f"{name:12s}{mean(totals[symbol_key]):11.3f}{mean(totals[file_key]):9.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
