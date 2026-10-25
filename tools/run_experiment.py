"""One pass over a corpus: coverage of the gold symbols, then localisation.

Per task: read the snapshot, rebuild the graph, extract gold symbols, measure
how much of the fix the graph represents, then ask whether the graph changes
where those symbols land in a ranked shortlist.

The localisation arms see exactly the same candidate pool and the same context
budget; the only difference is ordering. That is the comparison the paper needs,
because a graph that wins by retrieving more text has shown nothing.

    python tools/run_experiment.py --jobs 6
    python tools/run_experiment.py --limit 20 --pool 30
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
from experiments.coverage import candidate_ids  # noqa: E402
from experiments.evalcov import aggregate, by_repo, evaluate, gold_symbols  # noqa: E402
from experiments.gold import DictSnapshot, build_record  # noqa: E402
from experiments.retrieve import (  # noqa: E402
    BM25, adjacency, context_chars, document_text, recall_at,
)
from experiments.snapindex import SnapshotIndex  # noqa: E402

_INDEX: SnapshotIndex | None = None


def _init(repos: str) -> None:
    global _INDEX
    _INDEX = SnapshotIndex(repos)


def target_ids(record: dict, node_ids: set[str]) -> tuple[list[str], list[str]]:
    """Gold symbols mapped onto graph nodes; (resolved, unresolved)."""
    resolved, unresolved = [], []
    for path, qualname, _kind in gold_symbols(record):
        hit = next((c for c in candidate_ids(path, qualname) if c in node_ids), None)
        if hit is None:
            unresolved.append(f"{path}:{qualname}")
        elif hit not in resolved:
            resolved.append(hit)
    return resolved, unresolved


def rerank(pool: list[tuple[str, float]], neighbours: dict[str, set[str]],
           seeds: int = 5) -> list[str]:
    """Keep the pool, promote anything one hop from the strongest seeds."""
    seed_ids = [node_id for node_id, _ in pool[:seeds]]
    reachable: set[str] = set()
    for node_id in seed_ids:
        reachable |= neighbours.get(node_id, set())
    ordered = sorted(pool, key=lambda kv: (kv[0] in reachable, kv[1]), reverse=True)
    return [node_id for node_id, _ in ordered]


def _work(task: dict) -> dict:
    assert _INDEX is not None
    started = time.time()
    path = _INDEX.path_for(task)
    if path is None:
        return {"instance_id": task["instance_id"], "repo": task.get("repo", ""),
                "error": "no_snapshot"}

    files = read_snapshot(path)
    graph, stats = build_graph(files)
    nodes = graph.nodes
    record = build_record(task, None, snap=DictSnapshot(files))

    row = evaluate(record, set(nodes))
    row["base_commit"] = task.get("base_commit", "")
    row["graph_nodes"] = stats["nodes"]
    row["graph_edges"] = stats["edges"]
    row["files"] = stats["files"]

    gold_nodes, unresolved = target_ids(record, set(nodes))
    row["gold_nodes"] = len(gold_nodes)
    row["gold_unresolved"] = unresolved[:20]

    if gold_nodes:
        docs = {node_id: document_text(node) for node_id, node in nodes.items()}
        bm25 = BM25(docs)
        query = task.get("problem_statement") or ""
        pool_size = max(10, min(60, len(docs)))
        pool = bm25.search(query, pool_size)
        pool_ids = [node_id for node_id, _ in pool]
        neighbours = adjacency({"edges": graph.edges})
        graph_ids = rerank(pool, neighbours)

        targets = set(gold_nodes)
        row["pool_recall"] = recall_at(pool_ids, targets, len(pool_ids))
        row["arms"] = {
            "text": {
                "recall@1": recall_at(pool_ids, targets, 1),
                "recall@5": recall_at(pool_ids, targets, 5),
                "recall@10": recall_at(pool_ids, targets, 10),
                "chars@10": context_chars(pool_ids[:10], nodes),
            },
            "graph": {
                "recall@1": recall_at(graph_ids, targets, 1),
                "recall@5": recall_at(graph_ids, targets, 5),
                "recall@10": recall_at(graph_ids, targets, 10),
                "chars@10": context_chars(graph_ids[:10], nodes),
            },
        }
        reachable: set[str] = set()
        for node_id in pool_ids[:5]:
            reachable |= neighbours.get(node_id, set())
        row["graph_headroom"] = len(targets & reachable) / len(targets)

    row["seconds"] = round(time.time() - started, 2)
    return row


def summarise(rows: list[dict]) -> dict:
    def mean(values):
        values = [v for v in values if v is not None]
        return sum(values) / len(values) if values else None

    arms = {"text": {}, "graph": {}}
    for arm in arms:
        for metric in ("recall@1", "recall@5", "recall@10", "chars@10"):
            arms[arm][metric] = mean(
                row["arms"][arm][metric] for row in rows if "arms" in row
            )
    return {
        "tasks": len(rows),
        "tasks_scored": sum(1 for row in rows if "arms" in row),
        "graph_headroom": mean(row.get("graph_headroom") for row in rows),
        "pool_recall": mean(row.get("pool_recall") for row in rows),
        "arms": arms,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_lite.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--out", default=str(ROOT / "data" / "experiment.jsonl"))
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

    started = time.time()
    rows: list[dict] = []
    failures = 0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w", encoding="utf-8") as fh, ProcessPoolExecutor(
        max_workers=args.jobs, initializer=_init, initargs=(args.repos,)
    ) as pool:
        futures = {pool.submit(_work, task): task for task in tasks}
        for done, future in enumerate(as_completed(futures), 1):
            try:
                row = future.result()
            except Exception as exc:  # noqa: BLE001
                task = futures[future]
                row = {"instance_id": task["instance_id"],
                       "error": f"{type(exc).__name__}: {exc}"}
            if "error" in row:
                failures += 1
                print(f"  FAIL {row['instance_id']}: {row['error']}", flush=True)
            else:
                rows.append(row)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
            if done % 10 == 0 or done == len(tasks):
                elapsed = time.time() - started
                rate = done / elapsed
                print(f"  {done}/{len(tasks)}  {rate:.2f} task/s  "
                      f"eta {(len(tasks) - done) / max(rate, 1e-9) / 60:.1f} min",
                      flush=True)

    with out.open("w", encoding="utf-8") as fh:
        for row in sorted(rows, key=lambda r: r["instance_id"]):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = summarise(rows)
    summary.update(aggregate(rows))
    summary["failures"] = failures
    summary["seconds"] = round(time.time() - started, 1)
    print(json.dumps(summary, indent=2))
    for repo, stats in by_repo(rows).items():
        cov = stats["coverage"]
        print(f"  {repo:28s} n={stats['tasks_with_gold']:3d}  "
              f"coverage={'n/a' if cov is None else f'{cov:.3f}'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
