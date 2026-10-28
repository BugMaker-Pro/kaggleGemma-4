"""Combine the two evidence channels: what the issue names, and what it quotes.

Channel 1 (structure): a traceback frame resolves to a definition; a named path
points at a file.
Channel 2 (content): the issue pastes source lines, and the candidate's body
contains them verbatim.

They are independent — a frame tells you where, a quote tells you what — so this
pass orders a shortlist by: frame symbol, then body-matched candidates (capped),
then the named file, then plain BM25.

    python tools/run_combined.py --jobs 6 --out data/experiment_combo.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
from experiments.symbols import python_symbols, resolve  # noqa: E402
from tools.run_experiment import file_recall_at, target_ids  # noqa: E402

PATH_RE = re.compile(r"[\w./\\-]+\.py\b")
FRAME_RE = re.compile(r'File "([^"]+)", line (\d+)')

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
    limit = len(tokens) - _NGRAM + 1
    while index < limit:
        if tuple(tokens[index:index + _NGRAM]) in issue_grams:
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
    graph, _ = build_graph(files)
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
    repo_files = {name for name in files if name.endswith(".py")}

    # channel 1: structure named in the issue
    frame_symbols: list[str] = []
    for raw_path, raw_line in FRAME_RE.findall(issue):
        matched = _match_file(raw_path, repo_files)
        source = files.get(matched) if matched else None
        if not source:
            continue
        symbol = resolve(python_symbols(source), int(raw_line))
        if symbol is None:
            continue
        module = matched[:-3].replace("/", ".").replace(".__init__", "")
        node_id = f"{module}.{symbol.qualname}" if module else symbol.qualname
        if node_id in nodes and node_id not in frame_symbols:
            frame_symbols.append(node_id)

    named_files: list[str] = []
    for raw_path in PATH_RE.findall(issue):
        matched = _match_file(raw_path, repo_files)
        if matched and matched not in named_files:
            named_files.append(matched)

    # channel 2: source quoted in the issue
    issue_tokens = tokenize(issue)
    issue_set = set(issue_tokens)
    issue_grams = {tuple(issue_tokens[i:i + _NGRAM])
                   for i in range(len(issue_tokens) - _NGRAM + 1)}
    line_cache: dict[str, list[str]] = {}

    def body_of(node_id: str) -> str:
        node = nodes.get(node_id)
        if not node:
            return ""
        file_path = node.get("file", "")
        lines = line_cache.get(file_path)
        if lines is None:
            lines = files.get(file_path, "").splitlines()
            line_cache[file_path] = lines
        start = max(node.get("lineno", 1) - 1, 0)
        end = min(node.get("end_lineno") or start + 1, start + _BODY_LINES)
        return "\n".join(lines[start:end])

    runs = {node_id: _run_length(issue_grams, issue_set, body_of(node_id)) for node_id in pool}
    quoted = sorted((node_id for node_id in pool if runs[node_id] >= _MIN_RUN),
                    key=lambda node_id: -runs[node_id])
    preferred_file = named_files[0] if named_files else ""
    same_file = [node_id for node_id in pool if files_of.get(node_id) == preferred_file]

    def order(head: list[str]) -> list[str]:
        out = list(dict.fromkeys(head))
        seen = set(out)
        for node_id in pool:
            if node_id not in seen:
                out.append(node_id)
                seen.add(node_id)
        return out

    arms: dict[str, list[str]] = {
        "text": pool,
        "combo": order(frame_symbols + quoted[:_SLOTS // 2] + same_file[:_SLOTS // 2]),
        "combo3": order(frame_symbols + quoted[:3] + same_file[:4]),
        "combo_body_first": order(quoted[:_SLOTS // 2] + frame_symbols + same_file[:3]),
        "combo_nofile": order(frame_symbols + quoted[:_SLOTS // 2]),
        # The uncapped head could exceed ten slots: a task with nineteen traceback
        # frames was ordering the whole shortlist by frames, and the text answer
        # never got a slot. Cap every channel and keep a text floor of two.
        "combo_cap": order((frame_symbols[:2] + quoted[:4] + same_file[:2])[:8]),
        "combo_cap_loose": order((frame_symbols[:1] + quoted[:5] + same_file[:2])[:8]),
    }
    row["arms"] = {name: _arm(value, targets, gold_files, nodes, files_of)
                   for name, value in arms.items()}
    row["signals"] = {
        "frame": len(frame_symbols),
        "frame_correct": len(set(frame_symbols) & targets),
        "quoted": len(quoted),
        "quoted_gold": len(set(quoted) & targets),
        "named": len(named_files),
        "named_correct": bool(set(named_files) & gold_files),
    }
    row["seconds"] = round(time.time() - started, 2)
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_lite.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--out", default=str(ROOT / "data" / "experiment_combo.jsonl"))
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
    print(f"{'arm':18s}{'r@1':>7s}{'r@5':>7s}{'r@10':>7s}{'file@10':>9s}{'chars':>8s}")
    for name in ("text", "combo", "combo3", "combo_body_first", "combo_nofile",
                 "combo_cap", "combo_cap_loose"):
        def mean(metric):
            return sum(row["arms"][name][metric] for row in scored) / len(scored)
        print(f"{name:18s}{mean('recall@1'):7.3f}{mean('recall@5'):7.3f}"
              f"{mean('recall@10'):7.3f}{mean('file_recall@10'):9.3f}{mean('chars@10'):8.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
