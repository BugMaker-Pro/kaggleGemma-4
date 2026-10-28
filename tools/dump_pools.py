"""Stage 1 of the reranker study: dump each task's BM25 pool and its documents.

Reranking needs (query, document) pairs, and building them needs the graph, which
is the expensive part. Splitting it out means the reranker runs once over a flat
file instead of once per worker, and the pools stay inspectable.

Output rows: instance_id, gold_nodes, pool (200 ids with scores), docs (id -> text).

    python tools/dump_pools.py --jobs 6 --out data/pools.jsonl
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
from experiments.gold import DictSnapshot, build_record  # noqa: E402
from experiments.retrieve import BM25, document_text  # noqa: E402
from experiments.snapindex import SnapshotIndex  # noqa: E402
from tools.run_experiment import target_ids  # noqa: E402

_INDEX: SnapshotIndex | None = None
_POOL = 200


def _init(repos: str, pool: int = 200) -> None:
    global _INDEX, _POOL
    _INDEX = SnapshotIndex(repos)
    _POOL = pool


def _work(task: dict) -> dict:
    assert _INDEX is not None
    started = time.time()
    path = _INDEX.path_for(task)
    if path is None:
        return {"instance_id": task["instance_id"], "error": "no_snapshot"}

    files = read_snapshot(path)
    graph, _stats = build_graph(files)
    nodes = graph.nodes
    record = build_record(task, None, snap=DictSnapshot(files))
    gold, _ = target_ids(record, set(nodes))

    files_of = {node_id: node.get("file", "") for node_id, node in nodes.items()}
    gold_files = [entry["path"] for entry in record.get("files", [])
                  if entry.get("language") == "python"]

    docs = {node_id: document_text(node) for node_id, node in nodes.items()}
    bm25 = BM25(docs)
    query = task.get("problem_statement") or ""
    pool = bm25.search(query, _POOL)
    pool_ids = [node_id for node_id, _ in pool]

    return {
        "instance_id": task["instance_id"],
        "repo": task.get("repo", ""),
        "query": query,
        "gold_nodes": gold,
        "gold_files": gold_files,
        "pool": pool_ids,
        "files_of": {node_id: files_of.get(node_id, "") for node_id in pool_ids},
        "docs": {node_id: docs[node_id] for node_id in pool_ids},
        "seconds": round(time.time() - started, 2),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_lite.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--out", default=str(ROOT / "data" / "pools.jsonl"))
    ap.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip()]
    if args.limit:
        tasks = tasks[: args.limit]

    started = time.time()
    rows, failures = [], 0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh, ProcessPoolExecutor(
        max_workers=args.jobs, initializer=_init, initargs=(args.repos, 200)
    ) as pool:
        futures = {pool.submit(_work, task): task for task in tasks}
        for done, future in enumerate(as_completed(futures), 1):
            try:
                row = future.result()
            except Exception as exc:  # noqa: BLE001
                task = futures[future]
                row = {"instance_id": task["instance_id"], "error": f"{type(exc).__name__}: {exc}"}
            if "error" in row:
                failures += 1
                print(f"  FAIL {row['instance_id']}: {row['error']}", flush=True)
            else:
                rows.append(row)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
            if done % 20 == 0 or done == len(tasks):
                rate = done / (time.time() - started)
                print(f"  {done}/{len(tasks)}  {rate:.2f} task/s", flush=True)

    print(f"tasks {len(rows)} failures {failures} "
          f"{round(time.time() - started, 1)}s -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
