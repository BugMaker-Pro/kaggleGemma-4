"""Pilot: does the file-vs-symbol gap survive when the symbol's own body is indexed?

The pool in the paper is built from path, qualified name, signature and docstring
and deliberately *not* from the body, so that the graph has something left to do.
That choice was never tested, and it may be doing part of the work the paper
attributes to granularity.

This measures the same 300 tasks twice, with the same pool size and budget:

  body_out   document_text(node)                        (what the paper uses)
  body_in    document_text(node) + first 80 body lines   (the ablation)

Reported per task and paired: symbol recall@10, file recall@10, the ratio, and
how often the gold symbol is in the pool at all.

    python tools/body_ablation.py --limit 300 --jobs 6
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.buildgraph import build_graph, read_snapshot  # noqa: E402
from experiments.gold import DictSnapshot, build_record  # noqa: E402
from experiments.retrieve import BM25, document_text  # noqa: E402
from experiments.snapindex import SnapshotIndex  # noqa: E402
from tools.run_experiment import target_ids  # noqa: E402

BODY_LINES = 80
POOL = 200
K = 10
_INDEX: SnapshotIndex | None = None


def _init(repos: str) -> None:
    global _INDEX
    _INDEX = SnapshotIndex(repos)


def body_text(node: dict, files: dict[str, str], lines: int = BODY_LINES) -> str:
    source = files.get(node.get("file", ""))
    if not source:
        return ""
    all_lines = source.splitlines()
    start = max(node.get("lineno", 1) - 1, 0)
    end = min(node.get("end_lineno") or start + 1, start + lines)
    return "\n".join(all_lines[start:end])


def work(task: dict) -> dict:
    assert _INDEX is not None
    path = _INDEX.path_for(task)
    if path is None:
        return {"instance_id": task["instance_id"], "error": "no_snapshot"}
    files = read_snapshot(path)
    graph, _ = build_graph(files)
    nodes = graph.nodes
    record = build_record(task, None, snap=DictSnapshot(files))
    gold, _ = target_ids(record, set(nodes))
    gold_files = [entry["path"] for entry in record["files"] if entry["language"] == "python"]
    total = sum(len(entry.get("symbols", [])) for entry in record["files"] if entry["language"] == "python")
    if not total:
        return {"instance_id": task["instance_id"], "skipped": True}

    issue = task.get("problem_statement") or ""
    out: dict = {"instance_id": task["instance_id"], "repo": task.get("repo"),
                 "gold_total": total, "gold_files": gold_files, "variant": {}}
    # Control: the same amount of body text, but taken from a *different* symbol.
    # BM25 is bag-of-words, so this separates "this symbol's own body matches the
    # issue" from "any extra vocabulary at all matches the issue".
    order = list(nodes)
    donors = {}
    for position, node_id in enumerate(order):
        node = nodes[node_id]
        for step in range(1, len(order)):
            other = nodes[order[(position + step) % len(order)]]
            if other.get("file") == node.get("file"):
                donors[node_id] = other
                break
        else:
            donors[node_id] = nodes[order[(position + 1) % len(order)]]
    for name, docs in (
        ("body_out", {node_id: document_text(node) for node_id, node in nodes.items()}),
        ("body_in", {node_id: document_text(node) + "\n" + body_text(node, files)
                     for node_id, node in nodes.items()}),
        ("body_noise", {node_id: document_text(node) + "\n" + body_text(donors[node_id], files)
                        for node_id, node in nodes.items()}),
    ):
        bm25 = BM25(docs)
        ranked = bm25.search(issue, POOL)
        pool = [node_id for node_id, _ in ranked]
        files_of = {node_id: node.get("file", "") for node_id, node in nodes.items()}
        top = pool[:K]
        gold_set = set(gold)
        symbol_hits = len(gold_set & set(top))
        seen_files = []
        for node_id in top:
            file_path = files_of.get(node_id, "")
            if file_path and file_path not in seen_files:
                seen_files.append(file_path)
        file_hits = len(set(seen_files) & set(gold_files))
        out["variant"][name] = {
            "symbol": symbol_hits / total,
            "file": (file_hits / len(gold_files)) if gold_files else 0.0,
            "pool_hit": 1.0 if gold_set & set(pool) else 0.0,
            # the budget that matters is what a prompt would carry, so this is
            # the presentation text even when the index also holds the body
            "chars": sum(len(document_text(nodes[node_id])) for node_id in top),
            "index_chars": sum(len(docs[node_id]) for node_id in top),
        }
    return out


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else float("nan")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_lite.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1))
    ap.add_argument("--out", default=str(ROOT / "data" / "body_ablation.jsonl"))
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip()]
    if args.limit:
        tasks = tasks[: args.limit]

    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.jobs, initializer=_init,
                             initargs=(args.repos,)) as pool:
        futures = {pool.submit(work, task): task for task in tasks}
        for done, future in enumerate(as_completed(futures), 1):
            row = future.result()
            if "error" in row or row.get("skipped"):
                continue
            rows.append(row)
            if done % 50 == 0:
                print(f"  {done}/{len(tasks)}", flush=True)

    Path(args.out).write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                              encoding="utf-8")
    print(f"\n{len(rows)} tasks -> {args.out}\n")
    print(f"{'variant':10s} {'symbol':>7s} {'file':>7s} {'ratio':>6s} {'pool':>6s} {'chars':>7s}")
    for name in ("body_out", "body_in", "body_noise"):
        if name not in rows[0]["variant"]:
            continue
        symbol = mean([row["variant"][name]["symbol"] for row in rows])
        file = mean([row["variant"][name]["file"] for row in rows])
        pool_hit = mean([row["variant"][name]["pool_hit"] for row in rows])
        chars = mean([row["variant"][name]["chars"] for row in rows])
        print(f"{name:10s} {symbol:7.4f} {file:7.4f} {file / symbol:6.2f} {pool_hit:6.3f} {chars:7.0f}")

    for name, field in (("symbol", "symbol"), ("file", "file")):
        for other in ("body_in", "body_noise"):
            if other not in rows[0]["variant"]:
                continue
            deltas = [row["variant"][other][field] - row["variant"]["body_out"][field] for row in rows]
            wins = sum(1 for delta in deltas if delta > 1e-9)
            losses = sum(1 for delta in deltas if delta < -1e-9)
            print(f"{name}: {other} - body_out = {mean(deltas):+.4f}  "
                  f"({wins} wins, {losses} losses)")
        if "body_noise" in rows[0]["variant"]:
            deltas = [row["variant"]["body_in"][field] - row["variant"]["body_noise"][field]
                      for row in rows]
            wins = sum(1 for delta in deltas if delta > 1e-9)
            losses = sum(1 for delta in deltas if delta < -1e-9)
            print(f"{name}: body_in - body_noise = {mean(deltas):+.4f}  "
                  f"({wins} wins, {losses} losses)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
