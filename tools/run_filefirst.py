"""File-first localisation: use the strong file signal, then rank symbols inside it.

The eight arms in the paper all start from symbol-level BM25 and then let the
graph reorder. None of them uses the fact that the *file* is already found 62.4%
of the time while the symbol is found 27.5% of the time. This pass tests the
obvious remedy a reviewer will ask about: aggregate symbol scores to files, pick
the best few files, spend the whole shortlist inside them.

Arms (all under the same 10-slot budget):

  text          symbol-level BM25, top 10                        (reference)
  ff_k1..k5     files ranked by their best symbol; slots filled round-robin
                across the top k files, symbols ordered by their own score
  ff_graph      top-3 files plus their graph neighbours (files joined by any
                call/inherit/import edge), then the same round-robin fill
  file_oracle   the *gold* file only, symbols ranked by BM25 — the ceiling for
                any file-first method, i.e. stage 1 made perfect

`file_oracle` uses the answer key and is therefore a diagnostic, never an arm.

    python tools/run_filefirst.py --jobs 6 --out data/experiment_ff.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.buildgraph import build_graph, read_snapshot  # noqa: E402
from experiments.gold import DictSnapshot, build_record  # noqa: E402
from experiments.retrieve import (  # noqa: E402
    BM25, context_chars, document_text, recall_at,
)
from experiments.snapindex import SnapshotIndex  # noqa: E402
from tools.run_experiment import file_recall_at, target_ids  # noqa: E402

_INDEX: SnapshotIndex | None = None
_POOL = 200
_SLOTS = 10
_KEEP = 50

ARMS = ("text", "ff_k1", "ff_k2", "ff_k3", "ff_k5", "ff_graph", "file_oracle")


def _init(repos: str, pool: int = 200) -> None:
    global _INDEX, _POOL
    _INDEX = SnapshotIndex(repos)
    _POOL = pool


def _file_scores(ranked: list[tuple[str, float]], files_of: dict[str, str]) -> list[tuple[str, float]]:
    """Best symbol score per file, files sorted by it.

    Max rather than sum on purpose: summing rewards big files, and the question
    is "is this the file that contains the answer", not "how much code is here".
    """
    best: dict[str, float] = {}
    for node_id, score in ranked:
        path = files_of.get(node_id, "")
        if not path:
            continue
        if score > best.get(path, float("-inf")):
            best[path] = score
    return sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))


def _fill(files: list[str], by_file: dict[str, list[str]], ranked_ids: list[str],
          slots: int = _SLOTS) -> list[str]:
    """Round-robin across files, each file's symbols in their own score order."""
    out: list[str] = []
    seen: set[str] = set()
    cursors = {path: 0 for path in files}
    while len(out) < slots:
        progressed = False
        for path in files:
            if len(out) >= slots:
                break
            queue = by_file.get(path, [])
            cursor = cursors[path]
            while cursor < len(queue) and queue[cursor] in seen:
                cursor += 1
            cursors[path] = cursor
            if cursor >= len(queue):
                continue
            out.append(queue[cursor])
            seen.add(queue[cursor])
            cursors[path] = cursor + 1
            progressed = True
        if not progressed:
            break
    for node_id in ranked_ids:          # pad from the global ranking if short
        if len(out) >= slots:
            break
        if node_id in seen:
            continue
        out.append(node_id)
        seen.add(node_id)
    return out[:slots]


def _file_graph(graph, files_of: dict[str, str]) -> dict[str, set[str]]:
    """File-level adjacency: two files are linked by any call/inherit/import edge."""
    neighbours: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        if edge.get("type") not in ("calls", "inherits", "imports"):
            continue
        a = files_of.get(edge.get("source"))
        b = files_of.get(edge.get("target"))
        if not a or not b or a == b:
            continue
        neighbours[a].add(b)
        neighbours[b].add(a)
    return neighbours


def _arm(order: list[str], targets: set[str], gold_files: set[str],
         nodes: dict[str, dict], files_of: dict[str, str]) -> dict:
    top = order[:_KEEP]
    return {
        "top": top,
        "recall@1": recall_at(order, targets, 1),
        "recall@5": recall_at(order, targets, 5),
        "recall@10": recall_at(order, targets, 10),
        "file_recall@5": file_recall_at(order[:5], files_of, gold_files, 5),
        "file_recall@10": file_recall_at(order[:10], files_of, gold_files, 10),
        "chars@10": context_chars(order[:10], nodes),
    }


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
    gold, unresolved = target_ids(record, set(nodes))

    row: dict = {
        "instance_id": task["instance_id"],
        "repo": task.get("repo", ""),
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
    ranked = bm25.search(query, len(docs))
    ranked_ids = [node_id for node_id, _ in ranked]
    files_of = {node_id: node.get("file", "") for node_id, node in nodes.items()}
    gold_files = {entry["path"] for entry in record.get("files", [])
                  if entry.get("language") == "python"}
    targets = set(gold)

    by_file: dict[str, list[str]] = defaultdict(list)
    for node_id in ranked_ids:
        by_file[files_of.get(node_id, "")].append(node_id)

    file_order = [path for path, _score in _file_scores(ranked, files_of)]
    arms: dict[str, dict] = {}
    arms["text"] = _arm(ranked_ids, targets, gold_files, nodes, files_of)
    for k in (1, 2, 3, 5):
        selected = file_order[:k]
        order = _fill(selected, by_file, ranked_ids)
        order += [n for n in ranked_ids if n not in set(order)]   # full ordering
        arms[f"ff_k{k}"] = _arm(order, targets, gold_files, nodes, files_of)

    file_adj = _file_graph(graph, files_of)
    selected = list(file_order[:3])
    extra = sorted({n for path in selected for n in file_adj.get(path, ())
                    if n not in selected},
                   key=lambda p: (file_order.index(p) if p in file_order else 10 ** 6, p))
    order = _fill(selected + extra[:3], by_file, ranked_ids)
    order += [n for n in ranked_ids if n not in set(order)]
    arms["ff_graph"] = _arm(order, targets, gold_files, nodes, files_of)

    # Diagnostic, not an arm: stage 1 made perfect, gold file(s) only.
    oracle_ids = [n for n in ranked_ids if files_of.get(n) in gold_files]
    arms["file_oracle"] = _arm(oracle_ids or ranked_ids, targets, gold_files,
                               nodes, files_of)

    row["arms"] = arms
    row["stage1"] = {
        f"gold_file_rank_{k}": next(
            (i + 1 for i, path in enumerate(file_order) if path in gold_files), 0)
        for k in (3, 5)
    }
    row["stage1"]["gold_in_top3"] = 1.0 if any(p in gold_files for p in file_order[:3]) else 0.0
    row["stage1"]["gold_in_top5"] = 1.0 if any(p in gold_files for p in file_order[:5]) else 0.0
    row["seconds"] = round(time.time() - started, 2)
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_lite.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--out", default=str(ROOT / "data" / "experiment_ff.jsonl"))
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

    scored = [row for row in rows if row.get("arms")]
    print(f"\ntasks {len(rows)}  scored {len(scored)}  failures {failures}  "
          f"{round(time.time() - started, 1)}s")
    header = f"{'arm':14s}{'r@1':>7s}{'r@5':>7s}{'r@10':>7s}{'file@10':>9s}{'chars':>8s}"
    print(header)
    for arm in ARMS:
        def mean(metric):
            return sum(row["arms"][arm][metric] for row in scored) / len(scored)
        print(f"{arm:14s}{mean('recall@1'):7.3f}{mean('recall@5'):7.3f}"
              f"{mean('recall@10'):7.3f}{mean('file_recall@10'):9.3f}"
              f"{mean('chars@10'):8.0f}")
    in3 = sum(row["stage1"]["gold_in_top3"] for row in scored) / len(scored)
    in5 = sum(row["stage1"]["gold_in_top5"] for row in scored) / len(scored)
    print(f"\nstage 1 (file ranking): gold file in top-3 {in3:.3f}, top-5 {in5:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
