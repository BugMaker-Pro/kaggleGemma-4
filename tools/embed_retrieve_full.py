"""A dense index over the *whole repository*, so the pool can be unioned, not just reranked.

The dense arm in the paper ranks the 200 candidates BM25 already found, so it
cannot rescue a task whose gold symbol BM25 never ranked -- 27.6% of the
benchmark. This builds the other thing: every definition in the snapshot is
embedded and the top K by cosine is written out, so a union pool can be formed
and its ceiling measured.

Document preparation is the slow half (decompress, parse, build docs) and it is
pure Python, so it runs in worker *processes*; encoding stays in the parent, on
the GPU, one task at a time.

    python tools/embed_retrieve_full.py --only-lite --limit 20   # smoke test
    python tools/embed_retrieve_full.py --only-lite              # 300 Lite tasks
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.buildgraph import build_graph, read_snapshot  # noqa: E402
from experiments.snapindex import SnapshotIndex  # noqa: E402

MAX_ISSUE = 1200
MAX_BODY = 800
TOP = 300
_INDEX: SnapshotIndex | None = None
_BODY_CHARS = MAX_BODY


def _init(repos: str, body_chars: int) -> None:
    global _INDEX, _BODY_CHARS
    _INDEX = SnapshotIndex(repos)
    _BODY_CHARS = body_chars


def _body_of(node: dict, files: dict[str, str]) -> str:
    source = files.get(node.get("file", ""))
    if not source:
        return ""
    lines = source.splitlines()
    start = max(node.get("lineno", 1) - 1, 0)
    end = min(node.get("end_lineno") or start + 1, start + 80)
    return "\n".join(lines[start:end])


def _prepare(task: dict) -> dict:
    """Documents for one task. Runs in a worker process."""
    assert _INDEX is not None
    path = _INDEX.path_for(task)
    if path is None:
        return {"instance_id": task["instance_id"], "error": "no_snapshot"}
    files = read_snapshot(path)
    nodes = build_graph(files)[0].nodes
    ids = list(nodes)
    documents = [f"{nodes[node_id].get('file', '')} :: {node_id}\n"
                 f"{_body_of(nodes[node_id], files)[:_BODY_CHARS]}" for node_id in ids]
    return {"instance_id": task["instance_id"], "ids": ids, "documents": documents,
            "pool_ids": task["pool_ids"],
            "statement": (task.get("problem_statement") or "")[:MAX_ISSUE]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_full.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--model", default=str(ROOT / "models" / "bge-small-en-v1.5"))
    ap.add_argument("--out", default=str(ROOT / "data" / "embed_full_index.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--top", type=int, default=TOP)
    ap.add_argument("--max-len", type=int, default=512)
    ap.add_argument("--body-chars", type=int, default=MAX_BODY)
    ap.add_argument("--only-lite", action="store_true",
                    help="restrict to the 300 Lite tasks, for a first read at a tenth of the cost")
    args = ap.parse_args(argv)

    import torch  # noqa: PLC0415
    from transformers import AutoModel, AutoTokenizer  # noqa: PLC0415

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModel.from_pretrained(args.model, dtype=torch.float16).to(device).eval()
    print(f"device {device}", flush=True)

    features = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    meta = {row["instance_id"]: row for row in
            (json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip())}
    lite = set()
    if args.only_lite:
        lite = {json.loads(line)["instance_id"] for line in
                (ROOT / "data" / "swebench_lite.jsonl").open(encoding="utf-8") if line.strip()}
    tasks = []
    for row in features:
        if lite and row["instance_id"] not in lite:
            continue
        task = meta.get(row["instance_id"])
        if task is None:
            continue
        tasks.append({**task, "pool_ids": row["ids"]})
    if args.limit:
        tasks = tasks[: args.limit]
    print(f"tasks to index: {len(tasks)}", flush=True)

    def encode(batch: list[str], is_query: bool):
        if is_query:
            batch = ["Represent this query for retrieving code: " + text for text in batch]
        encoded = tokenizer(batch, padding=True, truncation=True, max_length=args.max_len,
                            return_tensors="pt").to(device)
        with torch.no_grad():
            output = model(**encoded).last_hidden_state[:, 0]
        return torch.nn.functional.normalize(output.float(), dim=-1)

    out = Path(args.out)
    scored = 0
    started = time.time()
    with out.open("w", encoding="utf-8") as fh, ProcessPoolExecutor(
            max_workers=args.workers, initializer=_init,
            initargs=(args.repos, args.body_chars)) as pool:
        futures = [pool.submit(_prepare, task) for task in tasks]
        for future in as_completed(futures):
            item = future.result()
            if "error" in item:
                continue
            ids, documents = item["ids"], item["documents"]
            query = encode([item["statement"]], True)
            scores = torch.empty(len(documents))
            for start in range(0, len(documents), args.batch):
                block = encode(documents[start:start + args.batch], False)
                scores[start:start + len(block)] = (block @ query.T).view(-1).float().cpu()
            k = min(args.top, len(documents))
            values, positions = torch.topk(scores, k)
            kept = [ids[int(position)] for position in positions]
            fh.write(json.dumps({
                "instance_id": item["instance_id"],
                "ids": kept,
                "scores": [round(float(value), 4) for value in values],
                "index_size": len(documents),
                "pool_overlap": len(set(kept) & set(item["pool_ids"])) / max(len(item["pool_ids"]), 1),
            }) + "\n")
            fh.flush()
            scored += 1
            if scored % 10 == 0:
                rate = scored / (time.time() - started)
                print(f"  {scored}/{len(tasks)}  {rate:.2f} task/s  "
                      f"eta {(len(tasks) - scored) / max(rate, 1e-9) / 60:.1f} min", flush=True)

    print(f"\ntasks {scored}  {time.time() - started:.0f}s -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
