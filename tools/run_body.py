"""Body-evidence reranking: the issue usually quotes the code it complains about.

Our symbol document is path + name + signature + docstring, so a pasted line of
source is reduced to noise tokens that match nothing. This pass adds a second
stage: for the 200 BM25 candidates only, extract the function body and score it
by the longest run of consecutive tokens it shares with the issue.

Arms (same ten slots, same character budget):
  text        BM25 top 10                                    (reference)
  body_hard   all candidates with a run >= 8 first, by run length
  body_cap5   at most five such candidates first, then BM25
  body_file   the file of the best body match gets five slots, five go to text

    python tools/run_body.py --jobs 6 --out data/experiment_body.jsonl
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
from experiments.retrieve import BM25, context_chars, document_text, tokenize  # noqa: E402
from experiments.snapindex import SnapshotIndex  # noqa: E402
from tools.run_experiment import file_recall_at, target_ids  # noqa: E402

_INDEX: SnapshotIndex | None = None
_POOL = 200
_SLOTS = 10
_NGRAM = 4
_MIN_RUN = 8
_BODY_LINES = 80


def _init(repos: str, pool: int = 200) -> None:
    global _INDEX, _POOL
    _INDEX = SnapshotIndex(repos)
    _POOL = pool


def _run_length(issue_tokens: set[tuple], issue_set: set[str], body: str) -> int:
    tokens = tokenize(body)
    best = current = 0
    index = 0
    limit = len(tokens) - _NGRAM + 1
    while index < limit:
        if tuple(tokens[index:index + _NGRAM]) in issue_tokens:
            current = _NGRAM
            position = index + _NGRAM
            while position < len(tokens) and tokens[position] in issue_set:
                current += 1
                position += 1
            best = max(best, current)
            index = position
        else:
            index += 1
    return best


def _arm(order: list[str], targets: set[str], gold_files: set[str],
         nodes: dict[str, dict], files_of: dict[str, str]) -> dict:
    top = order[:_SLOTS]
    return {
        "top": top,
        "recall@1": len(set(top[:1]) & targets) / len(targets),
        "recall@5": len(set(top[:5]) & targets) / len(targets),
        "recall@10": len(set(top[:10]) & targets) / len(targets),
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
    gold, _ = target_ids(record, set(nodes))
    row: dict = {"instance_id": task["instance_id"], "repo": task.get("repo", ""),
                 "gold_nodes": gold, "seconds": 0.0}
    if not gold:
        row["seconds"] = round(time.time() - started, 2)
        return row

    docs = {node_id: document_text(node) for node_id, node in nodes.items()}
    bm25 = BM25(docs)
    issue = task.get("problem_statement") or ""
    pool = [node_id for node_id, _ in bm25.search(issue, _POOL)]
    files_of = {node_id: node.get("file", "") for node_id, node in nodes.items()}
    gold_files = {entry["path"] for entry in record.get("files", [])
                  if entry.get("language") == "python"}
    targets = set(gold)

    issue_tokens = tokenize(issue)
    issue_set = set(issue_tokens)
    issue_grams = {tuple(issue_tokens[i:i + _NGRAM])
                   for i in range(len(issue_tokens) - _NGRAM + 1)}

    line_cache: dict[str, list[str]] = {}

    def body_of(node_id: str) -> str:
        node = nodes.get(node_id)
        if not node:
            return ""
        path_ = node.get("file", "")
        lines = line_cache.get(path_)
        if lines is None:
            lines = files.get(path_, "").splitlines()
            line_cache[path_] = lines
        start = max(node.get("lineno", 1) - 1, 0)
        end = min(node.get("end_lineno") or start + 1, start + _BODY_LINES)
        return "\n".join(lines[start:end])

    runs = {node_id: _run_length(issue_grams, issue_set, body_of(node_id)) for node_id in pool}
    matched = [node_id for node_id in pool if runs[node_id] >= _MIN_RUN]
    matched.sort(key=lambda node_id: -runs[node_id])

    orders: dict[str, list[str]] = {"text": pool}
    orders["body_hard"] = matched + [n for n in pool if n not in set(matched)]
    capped = matched[:_SLOTS // 2]
    orders["body_cap5"] = capped + [n for n in pool if n not in set(capped)]

    deep_file = files_of.get(matched[0], "") if matched else ""
    if deep_file:
        same = [n for n in pool if files_of.get(n) == deep_file]
        head = same[:_SLOTS // 2]
        orders["body_file"] = head + [n for n in pool if n not in set(head)]
    else:
        orders["body_file"] = pool

    arms = {name: _arm(order, targets, gold_files, nodes, files_of)
            for name, order in orders.items()}
    row["arms"] = arms
    row["body"] = {
        "matched": len(matched),
        "top_match_is_gold": bool(matched and matched[0] in targets),
        "top_run": runs[matched[0]] if matched else 0,
        "gold_run": max((runs.get(node, 0) for node in targets), default=0),
    }
    row["seconds"] = round(time.time() - started, 2)
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_lite.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--out", default=str(ROOT / "data" / "experiment_body.jsonl"))
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
                print(f"  {done}/{len(tasks)}  {rate:.2f} task/s  "
                      f"eta {(len(tasks) - done) / max(rate, 1e-9) / 60:.1f} min", flush=True)

    scored = [row for row in rows if row.get("arms")]
    print(f"\ntasks {len(rows)} scored {len(scored)} failures {failures} "
          f"{round(time.time() - started, 1)}s")
    print(f"{'arm':12s}{'r@1':>7s}{'r@5':>7s}{'r@10':>7s}{'file@10':>9s}{'chars':>8s}")
    for name in ("text", "body_hard", "body_cap5", "body_file"):
        def mean(metric):
            return sum(row["arms"][name][metric] for row in scored) / len(scored)
        print(f"{name:12s}{mean('recall@1'):7.3f}{mean('recall@5'):7.3f}"
              f"{mean('recall@10'):7.3f}{mean('file_recall@10'):9.3f}{mean('chars@10'):8.0f}")

    with_match = [row for row in scored if row["body"]["matched"]]
    print(f"\nbody match (run >= {_MIN_RUN}) on {len(with_match)} tasks; "
          f"best match is the gold symbol on "
          f"{sum(1 for row in with_match if row['body']['top_match_is_gold'])}")
    print(f"gold body has a run >= {_MIN_RUN}: "
          f"{sum(1 for row in scored if row['body']['gold_run'] >= _MIN_RUN)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
