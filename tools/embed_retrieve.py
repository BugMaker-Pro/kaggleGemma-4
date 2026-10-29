"""A code-trained bi-encoder over the same candidates.

The cross-encoder in `rerank_model.py` is a general-domain model, and it lost to
sixteen lexical features by a wide margin 鈥?its strongest cue turned out to be
the path and qualname header, which is what BM25 already has. That result says
something about *that* model, not necessarily about semantics, so this repeats
the measurement with a model trained on code retrieval:

  jinaai/jina-embeddings-v2-base-code   (161M, 768-d, ALiBi, code corpus)

Both the issue and each candidate are embedded and compared by cosine. Same pool,
same ten slots, same denominator as every other arm. Nothing is fine-tuned.

    python tools/embed_retrieve.py --limit 50          # smoke test
    python tools/embed_retrieve.py                     # all tasks
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.snapindex import SnapshotIndex  # noqa: E402
from experiments.snapshot import Snapshot  # noqa: E402
from experiments.symbols import python_symbols  # noqa: E402

MAX_ISSUE = 1200
MAX_SYMBOL = 800


def qualname_of(node_id: str, path: str) -> str:
    module = path[:-3].replace("/", ".").replace(".__init__", "")
    prefix = module + "."
    return node_id[len(prefix):] if node_id.startswith(prefix) else node_id.rsplit(".", 1)[-1]


def source_of(symbols, source: str, qualname: str) -> str:
    for symbol in symbols:
        if symbol.qualname == qualname:
            lines = source.splitlines()
            return "\n".join(lines[symbol.lineno - 1:(symbol.end_lineno or symbol.lineno)])
    return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_full.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--model", default=str(ROOT / "models" / "jina-code"))
    ap.add_argument("--out", default=str(ROOT / "data" / "embed_retrieval.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)

    import torch  # noqa: PLC0415
    from transformers import AutoModel, AutoTokenizer  # noqa: PLC0415

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModel.from_pretrained(args.model,
                                      torch_dtype=torch.float16).to(device).eval()
    print(f"device {device}", flush=True)

    tasks = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    if args.limit:
        tasks = tasks[: args.limit]
    meta = {row["instance_id"]: row for row in
            (json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip())}
    for task in tasks:
        row = meta.get(task["instance_id"], {})
        task["problem_statement"] = row.get("problem_statement") or ""
        task["base_commit"] = row.get("base_commit") or ""

    index = SnapshotIndex(args.repos)
    work: queue.Queue = queue.Queue(maxsize=64)

    def produce(worker: int):
        for position, task in enumerate(tasks):
            if position % args.workers != worker:
                continue
            path = index.path_for(task)
            if path is None:
                continue
            ids = task["ids"]
            files = sorted({task["files"][i] for i in range(len(ids)) if task["files"][i]})
            with Snapshot(path) as snap:
                texts = snap.subset_text(files)
            cache: dict[str, list] = {}
            documents = []
            for i in range(len(ids)):
                path_i = task["files"][i]
                if path_i not in cache:
                    cache[path_i] = python_symbols(texts.get(path_i) or "")
                body = source_of(cache[path_i], texts.get(path_i) or "",
                                 qualname_of(ids[i], path_i))
                documents.append(f"{path_i} :: {ids[i]}\n{body[:MAX_SYMBOL]}")
            work.put((task, documents))
        work.put(None)

    threads = [threading.Thread(target=produce, args=(worker,), daemon=True)
               for worker in range(args.workers)]
    for thread in threads:
        thread.start()

    def encode(batch, is_query: bool):
        if is_query:
            batch = ["Represent this query for retrieving code: " + text for text in batch]
        encoded = tokenizer(batch, padding=True, truncation=True, max_length=512,
                            return_tensors="pt").to(device)
        with torch.no_grad():
            output = model(**encoded).last_hidden_state[:, 0]
        return torch.nn.functional.normalize(output.float(), dim=-1)

    out = Path(args.out)
    finished = 0
    scored = 0
    started = time.time()
    with out.open("w", encoding="utf-8") as fh:
        while True:
            item = work.get()
            if item is None:
                finished += 1
                if finished >= args.workers:
                    break
                continue
            task, documents = item
            if not documents:
                continue
            issue = task["problem_statement"][:MAX_ISSUE]
            query = encode([issue], True)
            scores: list[float] = []
            for start in range(0, len(documents), args.batch):
                block = encode(documents[start:start + args.batch], False)
                scores.extend((block @ query.T).view(-1).cpu().tolist())
            order = sorted(range(len(scores)), key=lambda i: -scores[i])
            fh.write(json.dumps({
                "instance_id": task["instance_id"],
                "candidates": order,
                "scores": [round(scores[i], 4) for i in order],
            }) + "\n")
            fh.flush()
            scored += 1
            if scored % 20 == 0:
                rate = scored / (time.time() - started)
                print(f"  {scored}/{len(tasks)}  {rate:.1f} task/s  "
                      f"eta {(len(tasks) - scored) / max(rate, 1e-9) / 60:.1f} min", flush=True)

    print(f"\ntasks {scored}  {time.time() - started:.0f}s  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

