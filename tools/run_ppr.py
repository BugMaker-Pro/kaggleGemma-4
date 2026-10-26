"""Second pass: diffusion arm, full rank lists, and the conversion diagnostic.

`run_experiment.py` answers "does one-hop expansion help". This pass answers the
two questions a reviewer will ask about that answer:

1. *Did you try a real graph ranking?* Yes — personalised PageRank from the same
   five lexical seeds, plus a text/diffusion blend. Same pool, same budget.
2. *If reach is not the constraint, what is?* For every task we record where each
   gold symbol lands in every arm's full ranking, and the composition of the
   one-hop ball: how big it is, how many gold symbols it contains, and where
   those gold symbols sit. Conversion is then a number, not an assertion.

Output rows are self-contained (top-50 per arm + gold ranks), so the recall@k
curves and the conversion table are computed offline without rebuilding graphs.

    python tools/run_ppr.py --jobs 6 --out data/experiment_v3.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.buildgraph import build_graph, read_snapshot  # noqa: E402
from experiments.gold import DictSnapshot, build_record  # noqa: E402
from experiments.ppr import blend, ppr, ranked  # noqa: E402
from experiments.retrieve import (  # noqa: E402
    BM25, adjacency, ball, context_chars, document_text, expand_round_robin, fuse,
    recall_at,
)
from experiments.snapindex import SnapshotIndex  # noqa: E402
from tools.run_experiment import (  # noqa: E402
    FUSE_WEIGHT, PRECISE_RESOLUTIONS, file_recall_at, target_ids,
)

_INDEX: SnapshotIndex | None = None
_POOL = 200
_KEEP = 50          # how much of each ranking is written out
_PPR_RESTART = 0.15


def _init(repos: str, pool: int = 200) -> None:
    global _INDEX, _POOL
    _INDEX = SnapshotIndex(repos)
    _POOL = pool


def _ranks(order: list[str], targets: list[str]) -> dict[str, int]:
    """1-based position of each gold node in a ranking; 0 when absent."""
    where = {node_id: i + 1 for i, node_id in enumerate(order)}
    return {node_id: where.get(node_id, 0) for node_id in targets}


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
    gold, unresolved = target_ids(record, set(nodes))

    row: dict = {
        "instance_id": task["instance_id"],
        "repo": task.get("repo", ""),
        "graph_nodes": stats["nodes"],
        "graph_edges": stats["edges"],
        "files": stats["files"],
        "edge_states": dict(Counter(e.get("resolution", "?") for e in graph.edges)),
        "gold_nodes": gold,
        "gold_unresolved": unresolved[:20],
        "seconds": 0.0,
    }
    if not gold:
        row["seconds"] = round(time.time() - started, 2)
        return row

    docs = {node_id: document_text(node) for node_id, node in nodes.items()}
    bm25 = BM25(docs)
    query = task.get("problem_statement") or ""
    pool = bm25.search(query, _POOL)
    pool_ids = [node_id for node_id, _ in pool]
    neighbours = adjacency({"edges": graph.edges})
    precise = adjacency({"edges": graph.edges}, PRECISE_RESOLUTIONS)

    targets = list(dict.fromkeys(gold))
    target_set = set(targets)

    # Full text ranking, so a gold symbol's rank is known even when it is far
    # outside any pool we would pay for.
    text_full = [node_id for node_id, _ in bm25.search(query, len(docs))]

    seeds = pool_ids[:5]
    diffusion = ppr(neighbours, seeds, restart=_PPR_RESTART)
    ppr_order = ranked(diffusion)

    orderings: dict[str, list[str]] = {
        "text": text_full,
        "graph_rerank": [],
        "graph_open": expand_round_robin(pool_ids, neighbours, k=_POOL, seeds=5),
        "graph_open2": _open_two_hops(pool_ids, neighbours, k=_POOL),
        "graph_fuse": fuse(pool, neighbours, k=_KEEP, seeds=5, weight=FUSE_WEIGHT),
        "graph_fuse_precise": fuse(pool, precise, k=_KEEP, seeds=5, weight=FUSE_WEIGHT),
        "graph_ppr": ppr_order,
        "graph_ppr_text": blend(pool, diffusion, weight=0.5, limit=_KEEP),
    }

    # rerank keeps the pool and only reorders it, exactly as in run_experiment.
    seeds_set = set(seeds)
    orderings["graph_rerank"] = _rerank_order(pool, neighbours, seeds_set)
    files_of = {node_id: node.get("file", "") for node_id, node in nodes.items()}
    gold_files = _gold_files(record)

    arms: dict[str, dict] = {}
    for name, order in orderings.items():
        arms[name] = {
            "top": order[:_KEEP],
            "recall@1": recall_at(order, target_set, 1),
            "recall@5": recall_at(order, target_set, 5),
            "recall@10": recall_at(order, target_set, 10),
            # The list handed over must have exactly k entries: `file_recall_at`
            # counts distinct files until it has seen k of them, so a longer list
            # silently reports file recall at the same symbol budget as k is not.
            "file_recall@5": file_recall_at(order[:5], files_of, gold_files, 5),
            "file_recall@10": file_recall_at(order[:10], files_of, gold_files, 10),
            "chars@10": context_chars(order[:10], nodes),
            "gold_rank": _ranks(order, targets),
        }
    row["arms"] = arms
    row["pool_recall"] = recall_at(pool_ids, target_set, len(pool_ids))

    # --- conversion diagnostic -------------------------------------------
    ball1 = {node for seed in seeds for node in neighbours.get(seed, set())}
    ball2 = {node for node in ball1 for node in neighbours.get(node, set())}
    ball2 -= ball1 | seeds_set
    gold1 = [node for node in targets if node in ball1 and node not in seeds_set]
    gold2 = [node for node in targets if node in ball2 and node not in ball1
             and node not in seeds_set]
    cheapest = []
    for node in gold1:
        # Where the best graph arm puts a gold symbol the text pool missed.
        cheapest.append(arms["graph_ppr"]["gold_rank"].get(node, 0))
    row["ball"] = {
        "size1": len(ball1), "size2": len(ball2),
        "gold1": len(gold1), "gold2": len(gold2),
        "neighbours_per_seed": sum(len(neighbours.get(s, ())) for s in seeds) / max(len(seeds), 1),
        "gold1_ppr_rank": cheapest,
        "text_rank": _ranks(text_full, targets),
    }
    row["oracle@10"] = min(len(target_set & (set(pool_ids) | ball1)), 10) / len(target_set)
    row["seconds"] = round(time.time() - started, 2)
    return row


def _open_two_hops(pool_ids: list[str], neighbours: dict[str, set[str]], k: int) -> list[str]:
    """Five seeds, then the two-hop ball nearest-first, then the text tail.

    `expand_ball` is not used here: it treats its first argument as the seed list,
    so passing the pool returns the pool unchanged. Slots are filled from the
    distance-ordered ball and only padded from text once the ball is exhausted,
    which keeps the arm honestly "graph first".
    """
    seeds = pool_ids[:5]
    out = list(seeds)
    seen = set(out)
    for node_id, _distance in sorted(ball(seeds, neighbours, hops=2), key=lambda kv: kv[1]):
        if len(out) >= k:
            break
        if node_id in seen:
            continue
        out.append(node_id)
        seen.add(node_id)
    for node_id in pool_ids[5:]:
        if len(out) >= k:
            break
        if node_id in seen:
            continue
        out.append(node_id)
        seen.add(node_id)
    return out[:k]


def _rerank_order(pool: list[tuple[str, float]], neighbours: dict[str, set[str]],
                  seeds_set: set[str]) -> list[str]:
    reachable: set[str] = set()
    for node_id, _ in pool[:5]:
        reachable |= neighbours.get(node_id, set())
    ordered = sorted(pool, key=lambda kv: (kv[0] in reachable, kv[1]), reverse=True)
    return [node_id for node_id, _ in ordered]


def _gold_files(record: dict) -> set[str]:
    return {entry["path"] for entry in record.get("files", [])
            if entry.get("language") == "python"}


ARMS = ("text", "graph_rerank", "graph_open", "graph_open2", "graph_fuse",
        "graph_fuse_precise", "graph_ppr", "graph_ppr_text")


def summarise(rows: list[dict]) -> dict:
    scored = [row for row in rows if row.get("arms")]

    def mean(values):
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 4) if values else None

    out: dict = {"tasks": len(rows), "scored": len(scored)}
    for arm in ARMS:
        out[arm] = {
            metric: mean(row["arms"][arm][metric] for row in scored)
            for metric in ("recall@1", "recall@5", "recall@10",
                           "file_recall@5", "file_recall@10")
        }
    out["pool_recall"] = mean(row.get("pool_recall") for row in scored)
    out["oracle@10"] = mean(row.get("oracle@10") for row in scored)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_lite.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--out", default=str(ROOT / "data" / "experiment_v3.jsonl"))
    ap.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1))
    ap.add_argument("--pool", type=int, default=200)
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
        max_workers=args.jobs, initializer=_init, initargs=(args.repos, args.pool)
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
    summary["failures"] = failures
    summary["seconds"] = round(time.time() - started, 1)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
