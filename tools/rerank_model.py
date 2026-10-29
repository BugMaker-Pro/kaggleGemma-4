"""Does a semantic reranker close the gap the cheap features cannot?

Every signal in the paper is lexical: a token either appears in the issue or it
does not. The ten-slot ceiling within the pool is 0.600 and the best cheap ranker
reaches 0.361, so two thirds of the headroom sits on symbols whose words do not
match — `Colormap.__call__` against "deprecation warning". That is the part only a
model can read.

This runs one strong off-the-shelf cross-encoder, `BAAI/bge-reranker-v2-m3`, over
(issue, candidate) pairs drawn from the *same* pool, and scores the same ten slots
with the same denominator. Nothing is tuned; the model is used as an instrument,
not as a contribution.

Output: data/rerank_model.jsonl with the model's ordering per task, so the
analysis can be re-run without the GPU.

    python tools/rerank_model.py --limit 40          # smoke test
    python tools/rerank_model.py                      # all 2,232 tasks
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.snapindex import SnapshotIndex  # noqa: E402
from experiments.snapshot import Snapshot  # noqa: E402
from experiments.symbols import python_symbols  # noqa: E402

MODEL = "BAAI/bge-reranker-v2-m3"
MAX_ISSUE = 1200
MAX_SYMBOL = 800


def symbol_text(source: str | None, qualname: str) -> str:
    if not source:
        return qualname
    table = python_symbols(source)
    for symbol in table:
        if symbol.qualname == qualname:
            body = source[symbol.start_offset:symbol.end_offset] if hasattr(symbol, "start_offset") else ""
            if not body:
                lines = source.splitlines()
                body = "\n".join(lines[symbol.lineno - 1:(symbol.end_lineno or symbol.lineno)])
            return body[:MAX_SYMBOL]
    return qualname


def build_pairs(task: dict, index: SnapshotIndex) -> tuple[dict, list[tuple[str, str]], list[int]]:
    path = index.path_for(task)
    if path is None:
        return task, [], []
    files = sorted({task["files"][i] for i in range(len(task["ids"])) if task["files"][i]})
    with Snapshot(path) as snap:
        texts = snap.subset_text(files)
    issue = (task.get("problem_statement") or (ROOT / "data" / "issues.jsonl").exists() and "") or ""
    return task, texts, []


def load_issue(instance_id: str, tasks: dict) -> str:
    return tasks.get(instance_id, "")


def qualname_of(node_id: str, path: str) -> str:
    """`<module>.<qualname>` -> `<qualname>`, using the candidate's own file.

    The module is the repository-relative path without `.py`, and a package's
    `__init__` is written as the package itself, exactly as the graph builder did.
    """
    module = path[:-3].replace("/", ".").replace(".__init__", "")
    prefix = module + "."
    if node_id.startswith(prefix):
        return node_id[len(prefix):]
    return node_id.rsplit(".", 1)[-1]


def source_of(symbols, source: str, qualname: str) -> str:
    for symbol in symbols:
        if symbol.qualname == qualname:
            lines = source.splitlines()
            return "\n".join(lines[symbol.lineno - 1:(symbol.end_lineno or symbol.lineno)])
    return ""


def dry_run(args) -> int:
    """Check the pair builder without a GPU: does every candidate resolve to text?"""
    tasks = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    if args.limit:
        tasks = tasks[: args.limit]
    issues = {row["instance_id"]: row.get("problem_statement") or "" for row in
              (json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip())}
    base = {row["instance_id"]: row.get("base_commit") or "" for row in
            (json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip())}
    for task in tasks:
        task["problem_statement"] = issues.get(task["instance_id"], "")
        task["base_commit"] = base.get(task["instance_id"], "")
    index = SnapshotIndex(args.repos)
    for task in tasks[:3]:
        path = index.path_for(task)
        ids = task["ids"]
        keep = list(range(min(args.top, len(ids)))) if args.top else list(range(len(ids)))
        files = sorted({task["files"][i] for i in keep if task["files"][i]})
        with Snapshot(path) as snap:
            texts = snap.subset_text(files)
        cache: dict[str, list] = {}
        resolved = 0
        for i in keep:
            path_i = task["files"][i]
            if path_i not in cache:
                cache[path_i] = python_symbols(texts.get(path_i) or "")
            qualname = qualname_of(ids[i], path_i)
            if source_of(cache[path_i], texts.get(path_i) or "", qualname):
                resolved += 1
        issue = issues.get(task["instance_id"], "")
        sample = ids[0] if ids else ""
        print(f"{task['instance_id']}: {len(keep)} candidates, {len(files)} files, "
              f"{resolved} resolved to source, issue {len(issue)} chars, first id {sample}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_full.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--out", default=str(ROOT / "data" / "rerank_model.jsonl"))
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--top", type=int, default=0, help="rerank only the first N pool candidates")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true",
                    help="build the pairs and print samples without loading a model")
    args = ap.parse_args(argv)

    if args.dry_run:
        return dry_run(args)

    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    import torch  # noqa: PLC0415
    from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: PLC0415

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device {device}", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model, torch_dtype=torch.float16 if device == "cuda" else torch.float32)
    model.to(device).eval()

    tasks = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    if args.limit:
        tasks = tasks[: args.limit]
    issues = {row["instance_id"]: row.get("problem_statement") or "" for row in
              (json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip())}
    commits = {row["instance_id"]: row.get("base_commit") or "" for row in
               (json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip())}
    for task in tasks:
        task["problem_statement"] = issues.get(task["instance_id"], "")
        task["base_commit"] = commits.get(task["instance_id"], "")

    index = SnapshotIndex(args.repos)
    work: queue.Queue = queue.Queue(maxsize=48)
    out = Path(args.out)
    started = time.time()
    scored_tasks = 0
    pairs_total = 0

    def produce():
        for task in tasks:
            path = index.path_for(task)
            if path is None:
                continue
            ids = task["ids"]
            keep = list(range(min(args.top, len(ids)))) if args.top else list(range(len(ids)))
            files = sorted({task["files"][i] for i in keep if task["files"][i]})
            with Snapshot(path) as snap:
                texts = snap.subset_text(files)
            cache: dict[str, list] = {}
            pairs = []
            for i in keep:
                path_i = task["files"][i]
                if path_i not in cache:
                    cache[path_i] = python_symbols(texts.get(path_i) or "")
                body = source_of(cache[path_i], texts.get(path_i) or "",
                                 qualname_of(ids[i], path_i))
                document = f"{path_i} :: {ids[i]}\n{body[:MAX_SYMBOL]}"
                pairs.append((i, task["problem_statement"][:MAX_ISSUE], document))
            work.put((task, keep, pairs))
        work.put(None)

    threads = [threading.Thread(target=produce, daemon=True) for _ in range(args.workers)]
    for thread in threads:
        thread.start()

    with out.open("w", encoding="utf-8") as fh:
        while True:
            item = work.get()
            if item is None:
                break
            task, keep, pairs = item
            if not pairs:
                continue
            flat = [(issue, document) for _, issue, document in pairs]
            scores: list[float] = []
            with torch.no_grad():
                for start in range(0, len(flat), args.batch):
                    batch = flat[start:start + args.batch]
                    encoded = tokenizer([pair[0] for pair in batch], [pair[1] for pair in batch],
                                        padding=True, truncation="only_second",
                                        max_length=512, return_tensors="pt").to(device)
                    logits = model(**encoded).logits.view(-1).float().cpu().tolist()
                    scores.extend(logits)
            order = sorted(range(len(pairs)), key=lambda position: -scores[position])
            fh.write(json.dumps({
                "instance_id": task["instance_id"],
                "candidates": [pairs[position][0] for position in order],
                "scores": [round(scores[position], 4) for position in order],
            }) + "\n")
            fh.flush()
            scored_tasks += 1
            pairs_total += len(pairs)
            if scored_tasks % 20 == 0:
                rate = scored_tasks / (time.time() - started)
                print(f"  {scored_tasks}/{len(tasks)}  {rate:.1f} task/s  "
                      f"{pairs_total / max(time.time() - started, 1e-9):.0f} pairs/s  "
                      f"eta {(len(tasks) - scored_tasks) / max(rate, 1e-9) / 60:.1f} min", flush=True)

    print(f"\ntasks {scored_tasks}  pairs {pairs_total}  "
          f"{time.time() - started:.0f}s  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
