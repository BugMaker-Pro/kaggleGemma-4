"""Ablations, all in one pass over the corpus.

The expensive work per task is the graph build and the BM25 index; every
configuration below reuses them. That is the difference between a 27-minute run
and five of them.

    python tools/run_ablation.py --jobs 6
    python tools/analyse_ablation.py

Configurations:
  pool size     60 / 200 / 500        -- how many candidates the ranking sees
  seeds          1 / 3 / 5 / 10       -- how many text hits seed the expansion
  hops           1 / 2                -- how far the graph may reach
  fusion weight  0.25 / 0.5 / 1.0     -- how much a neighbour may inherit
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
from experiments.retrieve import (  # noqa: E402
    BM25, adjacency, ball, document_text, expand_ball, expand_round_robin, fuse,
    recall_at,
)
from experiments.snapindex import SnapshotIndex  # noqa: E402

_INDEX: SnapshotIndex | None = None

POOL_SIZES = (60, 200, 500)
SEED_COUNTS = (1, 3, 5, 10)
HOPS = (1, 2)
WEIGHTS = (0.25, 0.5, 1.0)
BIG_POOL = max(POOL_SIZES)


def _init(repos: str) -> None:
    global _INDEX
    _INDEX = SnapshotIndex(repos)


def _targets(record: dict, node_ids: set[str]) -> list[str]:
    from experiments.coverage import candidate_ids
    from experiments.evalcov import gold_symbols

    out = []
    for path, qualname, _kind in gold_symbols(record):
        hit = next((c for c in candidate_ids(path, qualname) if c in node_ids), None)
        if hit is not None and hit not in out:
            out.append(hit)
    return out


def _work(task: dict) -> dict:
    assert _INDEX is not None
    started = time.time()
    path = _INDEX.path_for(task)
    if path is None:
        return {"instance_id": task["instance_id"], "error": "no_snapshot"}

    files = read_snapshot(path)
    graph, _stats = build_graph(files)
    record = build_record(task, None, snap=DictSnapshot(files))
    gold = _targets(record, set(graph.nodes))
    if not gold:
        return {"instance_id": task["instance_id"], "repo": task.get("repo", ""),
                "gold_nodes": 0}

    bm25 = BM25({node_id: document_text(node) for node_id, node in graph.nodes.items()})
    query = task.get("problem_statement") or ""
    pool = bm25.search(query, BIG_POOL)
    pool_ids = [node_id for node_id, _ in pool]
    neighbours = adjacency({"edges": graph.edges})
    targets = set(gold)

    row = {
        "instance_id": task["instance_id"],
        "repo": task.get("repo", ""),
        "gold_nodes": len(gold),
        "pool_recall": {str(n): recall_at(pool_ids, targets, n) for n in POOL_SIZES},
        "headroom": {},
        "open_multi_hop": {},
        "fuse_weight": {},
        "text": {str(n): recall_at(pool_ids, targets, n) for n in (1, 5, 10)},
    }

    for seeds in SEED_COUNTS:
        seed_ids = pool_ids[:seeds]
        for hops in HOPS:
            reached = {node_id for node_id, _ in ball(seed_ids, neighbours, hops)}
            row["headroom"][f"s{seeds}h{hops}"] = len(targets & reached) / len(targets)
            if hops == 2:
                ids = expand_ball(seed_ids, neighbours, k=10, hops=hops)
                row["open_multi_hop"][f"s{seeds}h{hops}"] = recall_at(ids, targets, 10)

    for weight in WEIGHTS:
        ids = fuse(pool, neighbours, k=10, seeds=5, weight=weight)
        row["fuse_weight"][str(weight)] = {
            "recall@1": recall_at(ids, targets, 1),
            "recall@5": recall_at(ids, targets, 5),
            "recall@10": recall_at(ids, targets, 10),
        }

    row["open_h1"] = {
        str(seeds): recall_at(expand_round_robin(pool_ids, neighbours, k=10, seeds=seeds),
                              targets, 10)
        for seeds in SEED_COUNTS
    }
    row["seconds"] = round(time.time() - started, 2)
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_lite.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--out", default=str(ROOT / "data" / "ablation.jsonl"))
    ap.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    tasks = []
    with open(args.tasks, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                tasks.append(json.loads(line))
    if args.limit:
        tasks = tasks[: args.limit]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    rows: list[dict] = []
    failures = 0

    with out.open("w", encoding="utf-8") as fh, ProcessPoolExecutor(
        max_workers=args.jobs, initializer=_init, initargs=(args.repos,)
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
            if done % 25 == 0 or done == len(tasks):
                rate = done / (time.time() - started)
                print(f"  {done}/{len(tasks)}  {rate:.2f} task/s", flush=True)

    print(json.dumps({"rows": len(rows), "failures": failures,
                      "seconds": round(time.time() - started, 1)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
