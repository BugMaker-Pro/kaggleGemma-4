"""Does the graph pay as *document text* even though it does not pay as a ranking prior?

Every graph arm in the paper puts edges into the score: rerank, expand, fuse, PPR.
None of them helps. But an issue often names the *caller* ("when `foo` calls
`bar`..."), and the symbol document never contains that text. So the other role is
worth one measurement: append each candidate's call sites to its document and let
BM25 match them.

Three documents per candidate, same pool, same budget:

  doc               path, qualified name, signature, docstring   (the paper)
  doc_body          + the candidate's own first 80 body lines
  doc_body_callers  + one line per caller that mentions its name

    python tools/graph_as_text.py --limit 300 --jobs 4
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from collections import defaultdict
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


def caller_lines(node: dict, callers: list[str], nodes: dict, files: dict[str, str]) -> str:
    """One line per caller, the one that mentions this symbol's name."""
    name = node.get("name") or ""
    if not name:
        return ""
    found = []
    for caller_id in callers:
        source = files.get(nodes.get(caller_id, {}).get("file", ""))
        if not source:
            continue
        start = max(nodes[caller_id].get("lineno", 1) - 1, 0)
        end = min(nodes[caller_id].get("end_lineno") or start + 1, start + BODY_LINES)
        for line in source.splitlines()[start:end]:
            if name in line and len(line.strip()) > 3:
                found.append(line.strip())
                break
    return "\n".join(found[:4])


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
    total = sum(len(entry.get("symbols", [])) for entry in record["files"]
                if entry["language"] == "python")
    if not total:
        return {"instance_id": task["instance_id"], "skipped": True}

    callers: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        if edge.get("type") == "calls" and edge.get("source") and edge.get("target"):
            callers[edge["target"]].append(edge["source"])

    docs = {
        "doc": {},
        "doc_body": {},
        "doc_body_callers": {},
    }
    for node_id, node in nodes.items():
        base = document_text(node)
        body = body_text(node, files)
        docs["doc"][node_id] = base
        docs["doc_body"][node_id] = base + "\n" + body
        docs["doc_body_callers"][node_id] = (base + "\n" + body + "\n"
                                             + caller_lines(node, callers.get(node_id, []),
                                                            nodes, files))

    issue = task.get("problem_statement") or ""
    out: dict = {"instance_id": task["instance_id"], "repo": task.get("repo"), "variant": {}}
    files_of = {node_id: node.get("file", "") for node_id, node in nodes.items()}
    for name, corpus in docs.items():
        ranked = BM25(corpus).search(issue, POOL)
        pool = [node_id for node_id, _ in ranked]
        top = pool[:K]
        gold_set = set(gold)
        seen = []
        for node_id in top:
            file_path = files_of.get(node_id, "")
            if file_path and file_path not in seen:
                seen.append(file_path)
        out["variant"][name] = {
            "symbol": len(gold_set & set(top)) / total,
            "file": (len(set(seen) & set(gold_files)) / len(gold_files)) if gold_files else 0.0,
            "pool_hit": 1.0 if gold_set & set(pool) else 0.0,
            "chars": sum(len(document_text(nodes[node_id])) for node_id in top),
        }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_lite.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--out", default=str(ROOT / "data" / "graph_as_text.jsonl"))
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
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

    Path(args.out).write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    print(f"\n{len(rows)} tasks -> {args.out}\n")
    print(f"{'variant':18s} {'symbol':>7s} {'file':>7s} {'pool':>6s} {'chars':>7s}")
    for name in ("doc", "doc_body", "doc_body_callers"):
        symbol = statistics.fmean(row["variant"][name]["symbol"] for row in rows)
        file = statistics.fmean(row["variant"][name]["file"] for row in rows)
        pool_hit = statistics.fmean(row["variant"][name]["pool_hit"] for row in rows)
        chars = statistics.fmean(row["variant"][name]["chars"] for row in rows)
        print(f"{name:18s} {symbol:7.4f} {file:7.4f} {pool_hit:6.3f} {chars:7.0f}")
    for field in ("symbol", "file", "pool_hit"):
        deltas = [row["variant"]["doc_body_callers"][field] - row["variant"]["doc_body"][field]
                  for row in rows]
        wins = sum(1 for d in deltas if d > 1e-9)
        losses = sum(1 for d in deltas if d < -1e-9)
        print(f"{field:8s} callers - body = {statistics.fmean(deltas):+.4f}  "
              f"({wins} wins, {losses} losses)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
