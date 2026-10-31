"""Does a body index still add anything to the ranker that already reads bodies?

The ablation showed +3.8 points for a BM25 over documents that include the
candidate's own body. But the sixteen-feature ranker already carries two
body-quote features, so part of that signal may be priced in. This measures the
marginal value at the ranker's own layer, with the pool held fixed:

  for every candidate in the *paper's* pool, add
    body_in_pool   1 if a body-inclusive BM25 ranks it in its own top 200
    body_rank      1 / (1 + its rank there), 0 when absent

then retrain the same ranker on the same folds and compare with the 16-feature
baseline. A pool miss on the body side is not a drop: the candidate is still in
the pool being ranked, this is only extra evidence.

    python tools/body_rank_feature.py --jobs 5
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.buildgraph import build_graph, read_snapshot  # noqa: E402
from experiments.retrieve import BM25, document_text  # noqa: E402
from experiments.snapindex import SnapshotIndex  # noqa: E402

POOL = 200
BODY_LINES = 80
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
    docs = {node_id: document_text(node) + "\n" + body_text(node, files)
            for node_id, node in nodes.items()}
    ranked = BM25(docs).search(task.get("problem_statement") or "", POOL)
    position = {node_id: rank for rank, (node_id, _score) in enumerate(ranked, start=1)}
    ids = task["ids"]
    return {
        "instance_id": task["instance_id"],
        "body_in_pool": [1.0 if node_id in position else 0.0 for node_id in ids],
        "body_rank": [1.0 / (1.0 + position[node_id]) if node_id in position else 0.0
                      for node_id in ids],
        "body_pool_size": len(ranked),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_full.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--out", default=str(ROOT / "data" / "body_rank_features.jsonl"))
    ap.add_argument("--jobs", type=int, default=min(5, os.cpu_count() or 1))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    # the features rows carry ids but not the revision, so the task metadata
    # (base_commit, problem statement) comes from the benchmark file
    meta = {row["instance_id"]: row for row in
            (json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip())}
    rows_in = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    tasks = []
    for row in rows_in:
        task = meta.get(row["instance_id"])
        if task is None:
            continue
        tasks.append({**task, "ids": row["ids"]})
    if args.limit:
        tasks = tasks[: args.limit]

    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.jobs, initializer=_init,
                             initargs=(args.repos,)) as pool:
        futures = {pool.submit(work, task): task for task in tasks}
        for done, future in enumerate(as_completed(futures), 1):
            row = future.result()
            if "error" in row:
                continue
            rows.append(row)
            if done % 50 == 0:
                print(f"  {done}/{len(tasks)}", flush=True)

    Path(args.out).write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    covered = sum(sum(row["body_in_pool"]) for row in rows) / max(len(rows), 1)
    print(f"{len(rows)} tasks -> {args.out}")
    print(f"candidates also in the body pool: {covered:.1f} of 200 per task on average")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
