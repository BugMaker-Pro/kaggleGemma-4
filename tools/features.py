"""One row of features per candidate symbol, for learning to rank.

Every signal the paper has built so far, plus the graph statistics that the eight
arms used implicitly, in one table. Labels are the gold symbol ids from the
reference patch; nothing in the features reads the patch.

Features (all computed per candidate in the BM25 top-200):

  bm25_score, bm25_rank        the lexical baseline itself
  body_run, body_line          longest shared token run with the issue; a full
                               body line appearing verbatim in the issue
  path_in_issue, path_overlap  the file is named; IDF-weighted path-token match
  frame_hit, frame_file        a traceback line resolves to this symbol; the
                               symbol sits in a file a frame names
  named_file                   the symbol sits in a file the issue names
  in_degree, out_degree        call/inherit edges, log1p
  near_seed                    adjacent to one of the top five BM25 hits
  file_best, file_size         the file's best symbol score, number of symbols
  span_lines, doc_tokens       symbol size, document length

    python tools/features.py --jobs 6 --out data/features.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.buildgraph import build_graph, read_snapshot  # noqa: E402
from experiments.gold import DictSnapshot, build_record  # noqa: E402
from experiments.retrieve import BM25, document_text, tokenize  # noqa: E402
from experiments.snapindex import SnapshotIndex  # noqa: E402
from experiments.symbols import python_symbols, resolve  # noqa: E402
from tools.run_experiment import target_ids  # noqa: E402

PATH_RE = re.compile(r"[\w./\\-]+\.py\b")
FRAME_RE = re.compile(r'File "([^"]+)", line (\d+)')
NGRAM = 4
BODY_LINES = 80

FEATURES = ("bm25_score", "bm25_rank", "body_run", "body_line", "path_in_issue",
            "path_overlap", "frame_hit", "frame_file", "named_file", "in_degree",
            "out_degree", "near_seed", "file_best", "file_size", "span_lines",
            "doc_tokens")

_INDEX: SnapshotIndex | None = None


def _init(repos: str) -> None:
    global _INDEX
    _INDEX = SnapshotIndex(repos)


def _normalise(raw: str) -> str:
    path = raw.replace("\\", "/")
    if "site-packages/" in path:
        path = path.split("site-packages/", 1)[1]
    return path.lstrip("./").split("../")[-1]


def _match_file(candidate: str, repo_files: set[str]) -> str | None:
    candidate = _normalise(candidate)
    if candidate in repo_files:
        return candidate
    hits = [path for path in repo_files
            if path.endswith("/" + candidate) or candidate.endswith("/" + path)]
    return sorted(hits, key=lambda path: (len(path), path))[0] if hits else None


def _run_length(issue_grams: set[tuple], issue_set: set[str], body: str) -> int:
    tokens = tokenize(body)
    best = index = 0
    limit = len(tokens) - NGRAM + 1
    while index < limit:
        if tuple(tokens[index:index + NGRAM]) in issue_grams:
            length = NGRAM
            position = index + NGRAM
            while position < len(tokens) and tokens[position] in issue_set:
                length += 1
                position += 1
            best = max(best, length)
            index = position
        else:
            index += 1
    return best


def _work(task: dict) -> dict:
    assert _INDEX is not None
    started = time.time()
    path = _INDEX.path_for(task)
    if path is None:
        return {"instance_id": task["instance_id"], "error": "no_snapshot"}

    files = read_snapshot(path)
    graph, _ = build_graph(files)
    nodes = graph.nodes
    record = build_record(task, None, snap=DictSnapshot(files))
    gold, _ = target_ids(record, set(nodes))
    if not gold:
        return {"instance_id": task["instance_id"], "repo": task.get("repo", ""),
                "skipped": True, "seconds": round(time.time() - started, 2)}

    docs = {node_id: document_text(node) for node_id, node in nodes.items()}
    bm25 = BM25(docs)
    issue = task.get("problem_statement") or ""
    ranked = bm25.search(issue, 200)
    pool = [node_id for node_id, _ in ranked]
    top_score = ranked[0][1] if ranked else 1.0
    files_of = {node_id: node.get("file", "") for node_id, node in nodes.items()}
    repo_files = {name for name in files if name.endswith(".py")}

    degrees_in: dict[str, int] = defaultdict(int)
    degrees_out: dict[str, int] = defaultdict(int)
    neighbours: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        if edge.get("type") not in ("calls", "inherits"):
            continue
        source, target = edge.get("source"), edge.get("target")
        if not source or not target:
            continue
        degrees_out[source] += 1
        degrees_in[target] += 1
        neighbours[source].add(target)
        neighbours[target].add(source)

    seeds = set(pool[:5])
    near = set()
    for seed in seeds:
        near |= neighbours.get(seed, set())

    # issue-side signals
    issue_tokens = tokenize(issue)
    issue_set = set(issue_tokens)
    issue_grams = {tuple(issue_tokens[i:i + NGRAM])
                   for i in range(len(issue_tokens) - NGRAM + 1)}
    issue_norm = " ".join(issue.split())

    frame_symbols: set[str] = set()
    frame_files: set[str] = set()
    for raw_path, raw_line in FRAME_RE.findall(issue):
        matched = _match_file(raw_path, repo_files)
        if not matched:
            continue
        frame_files.add(matched)
        source = files.get(matched)
        symbol = resolve(python_symbols(source), int(raw_line)) if source else None
        if symbol is None:
            continue
        module = matched[:-3].replace("/", ".").replace(".__init__", "")
        node_id = f"{module}.{symbol.qualname}" if module else symbol.qualname
        if node_id in nodes:
            frame_symbols.add(node_id)

    named_files = {matched for matched in
                   (_match_file(raw, repo_files) for raw in PATH_RE.findall(issue)) if matched}

    path_df: dict[str, int] = defaultdict(int)
    path_tokens: dict[str, set[str]] = {}
    for name in repo_files:
        tokens = {token.lower() for token in tokenize(name.replace("/", " ").replace(".", " "))}
        path_tokens[name] = tokens
        for token in tokens:
            path_df[token] += 1
    limit = max(len(repo_files) // 20, 2)

    file_scores: dict[str, float] = defaultdict(float)
    file_sizes: dict[str, int] = defaultdict(int)
    for node_id, score in ranked:
        file_path = files_of.get(node_id, "")
        file_scores[file_path] = max(file_scores.get(file_path, 0.0), score)
        file_sizes[file_path] += 1

    line_cache: dict[str, list[str]] = {}

    rows = []
    for rank, (node_id, score) in enumerate(ranked, start=1):
        node = nodes.get(node_id, {})
        file_path = files_of.get(node_id, "")
        lines = line_cache.get(file_path)
        if lines is None:
            lines = files.get(file_path, "").splitlines()
            line_cache[file_path] = lines
        start = max(node.get("lineno", 1) - 1, 0)
        end = min(node.get("end_lineno") or start + 1, start + BODY_LINES)
        body = "\n".join(lines[start:end])

        run = _run_length(issue_grams, issue_set, body)
        body_line = 0
        for line in body.splitlines():
            stripped = " ".join(line.split())
            if len(stripped) >= 15 and stripped in issue_norm:
                body_line = 1
                break

        tokens = path_tokens.get(file_path, set())
        overlap = sum(1.0 / (1.0 + math.log(path_df[token]))
                      for token in tokens & issue_set
                      if path_df[token] <= limit and len(token) > 2)

        rows.append([
            round(score / (top_score or 1.0), 4),
            round(1.0 / rank, 4),
            min(run, 40) / 40.0,
            float(body_line),
            float(bool(set(named_files) & {file_path})),
            round(overlap, 4),
            float(node_id in frame_symbols),
            float(file_path in frame_files),
            float(file_path in named_files),
            round(math.log1p(degrees_in.get(node_id, 0)), 4),
            round(math.log1p(degrees_out.get(node_id, 0)), 4),
            float(node_id in near and node_id not in seeds),
            round(file_scores.get(file_path, 0.0) / (top_score or 1.0), 4),
            round(math.log1p(file_sizes.get(file_path, 0)), 4),
            round(math.log1p(max((node.get("end_lineno") or 1) - (node.get("lineno") or 1), 1)), 4),
            round(math.log1p(len(tokenize(docs.get(node_id, "")))), 4),
        ])

    return {
        "instance_id": task["instance_id"],
        "repo": task.get("repo", ""),
        "features": list(FEATURES),
        "rows": rows,
        "labels": [1 if node_id in set(gold) else 0 for node_id in pool],
        "ids": pool,
        "seconds": round(time.time() - started, 2),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_lite.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--out", default=str(ROOT / "data" / "features.jsonl"))
    ap.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip()]
    if args.limit:
        tasks = tasks[: args.limit]

    started = time.time()
    rows, failures, skipped = [], 0, 0
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
                row = {"instance_id": task["instance_id"], "error": f"{type(exc).__name__}: {exc}"}
            if "error" in row:
                failures += 1
                print(f"  FAIL {row['instance_id']}: {row['error']}", flush=True)
            elif row.get("skipped"):
                skipped += 1
            else:
                rows.append(row)
                fh.write(json.dumps(row) + "\n")
                fh.flush()
            if done % 20 == 0 or done == len(tasks):
                rate = done / (time.time() - started)
                print(f"  {done}/{len(tasks)}  {rate:.2f} task/s  "
                      f"eta {(len(tasks) - done) / max(rate, 1e-9) / 60:.1f} min", flush=True)

    print(f"\ntasks {len(rows)} skipped {skipped} failures {failures} "
          f"{round(time.time() - started, 1)}s -> {out}")
    print(f"candidates {sum(len(r['rows']) for r in rows)} "
          f"positives {sum(sum(r['labels']) for r in rows)}")
    for index, name in enumerate(FEATURES):
        total = sum(row["rows"][i][index] for row in rows for i in range(len(row["rows"])))
        print(f"  {name:14s} mean {total / max(sum(len(r['rows']) for r in rows), 1):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
