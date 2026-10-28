"""Evidence-first localisation: use the file paths and traceback lines in the issue.

BM25 tokenises the issue into a bag of words, which destroys the two most precise
signals it contains: a path says *which file*, and a traceback frame says *which
line*. This pass uses them in three layers, then compares against plain text.

Arms:
  text      BM25 top 10 (reference)
  ev_frame  layer 1 only: a traceback frame resolves to a definition, put it first
  ev_soft   layer 1, then the file named in the issue is moved forward (no exclusion)
  ev_hard   layer 1, then the named file is the only source of slots
  ev_mix    layer 1/2, then five slots from the preferred file and five from text

Layer 1 is high precision (the answer is printed); layer 2 is not (54% of named
paths are right), which is exactly what ev_soft versus ev_hard measures.

    python tools/run_evidence.py --jobs 6 --out data/experiment_ev.jsonl
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
from experiments.retrieve import BM25, context_chars, document_text  # noqa: E402
from experiments.snapindex import SnapshotIndex  # noqa: E402
from experiments.symbols import python_symbols, resolve  # noqa: E402
from tools.run_experiment import file_recall_at, target_ids  # noqa: E402

PATH_RE = re.compile(r"[\w./\\-]+\.py\b")
FRAME_RE = re.compile(r'File "([^"]+)", line (\d+)')

_INDEX: SnapshotIndex | None = None
_POOL = 200
_SLOTS = 10
_KEEP = 50


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
    """Map a path from the issue onto a repository-relative path, by suffix."""
    candidate = _normalise(candidate)
    if candidate in repo_files:
        return candidate
    hits = [path for path in repo_files
            if path.endswith("/" + candidate) or candidate.endswith("/" + path)]
    if not hits:
        return None
    return sorted(hits, key=lambda path: (len(path), path))[0]


def _arm(order: list[str], targets: set[str], gold_files: set[str],
         nodes: dict[str, dict], files_of: dict[str, str]) -> dict:
    top = order[:_KEEP]
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
    ranked = bm25.search(issue, _POOL)
    pool_ids = [node_id for node_id, _ in ranked]
    files_of = {node_id: node.get("file", "") for node_id, node in nodes.items()}
    gold_files = {entry["path"] for entry in record.get("files", [])
                  if entry.get("language") == "python"}
    targets = set(gold)
    repo_files = {path for path in files if path.endswith(".py")}

    # ---- evidence layers -------------------------------------------------
    frame_symbols: list[str] = []
    for raw_path, raw_line in FRAME_RE.findall(issue):
        matched = _match_file(raw_path, repo_files)
        if not matched:
            continue
        source = files.get(matched)
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

    by_file: dict[str, list[str]] = {}
    for node_id in [n for n, _ in bm25.search(issue, len(docs))]:
        by_file.setdefault(files_of.get(node_id, ""), []).append(node_id)

    def take(order: list[str], slots: int = _SLOTS) -> list[str]:
        out, seen = [], set()
        for node_id in order:
            if len(out) >= slots:
                break
            if node_id not in seen:
                out.append(node_id)
                seen.add(node_id)
        return out

    text_order = pool_ids + [n for n, _ in bm25.search(issue, len(docs))]

    orders: dict[str, list[str]] = {"text": text_order}
    orders["ev_frame"] = take(frame_symbols) + [n for n in text_order
                                               if n not in set(frame_symbols)]

    preferred = named_files[0] if named_files else ""
    forward: list[str] = []
    if preferred:
        forward = by_file.get(preferred, [])
    orders["ev_soft"] = take(frame_symbols + forward) + [
        n for n in text_order if n not in set(frame_symbols + forward)]
    orders["ev_hard"] = take(frame_symbols + forward)
    orders["ev_hard"] = orders["ev_hard"] + [
        n for n in text_order if n not in set(orders["ev_hard"])]
    orders["ev_mix"] = take((frame_symbols[:5] + forward)[:5]) + [
        n for n in text_order if n not in set(frame_symbols[:5] + forward)]

    arms = {name: _arm(order, targets, gold_files, nodes, files_of)
            for name, order in orders.items()}
    row["arms"] = arms
    row["evidence"] = {
        "frame_symbols": len(frame_symbols),
        "frame_correct": len(set(frame_symbols) & targets),
        "named_files": named_files[:3],
        "named_correct": bool(set(named_files) & gold_files),
    }
    row["seconds"] = round(time.time() - started, 2)
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_lite.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--out", default=str(ROOT / "data" / "experiment_ev.jsonl"))
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
    print(f"{'arm':10s}{'r@1':>7s}{'r@5':>7s}{'r@10':>7s}{'file@10':>9s}{'chars':>8s}")
    for name in ("text", "ev_frame", "ev_soft", "ev_hard", "ev_mix"):
        def mean(metric):
            return sum(row["arms"][name][metric] for row in scored) / len(scored)
        print(f"{name:10s}{mean('recall@1'):7.3f}{mean('recall@5'):7.3f}"
              f"{mean('recall@10'):7.3f}{mean('file_recall@10'):9.3f}{mean('chars@10'):8.0f}")

    with_frames = [row for row in scored if row["evidence"]["frame_symbols"]]
    named = [row for row in scored if row["evidence"]["named_files"]]
    print(f"\nlayer 1 used on {len(with_frames)} tasks, "
          f"gold symbol hit on {sum(1 for row in with_frames if row['evidence']['frame_correct'])}")
    print(f"layer 2 used on {len(named)} tasks, "
          f"named file correct on {sum(1 for row in named if row['evidence']['named_correct'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
