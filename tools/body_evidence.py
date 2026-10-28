"""Does the issue quote the code it complains about?

Our symbol document is path + qualified name + signature + docstring; the body is
never indexed. But issues routinely paste the offending line. This census asks
how often the issue contains a verbatim line, or a long verbatim token run, from
the gold symbol's body — and whether our ranking finds that symbol anyway.

    python tools/body_evidence.py --jobs 6
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.snapindex import SnapshotIndex  # noqa: E402
from experiments.snapshot import Snapshot  # noqa: E402
from experiments.symbols import python_symbols, resolve  # noqa: E402
from experiments.retrieve import tokenize  # noqa: E402

_INDEX: SnapshotIndex | None = None
WS = re.compile(r"\s+")

NGRAM = 4
LONG_RUN = 8


def _normalise(text: str) -> str:
    return WS.sub(" ", text).strip()


def _body_lines(source: str, lineno: int, end_lineno: int) -> list[str]:
    lines = source.splitlines()[lineno - 1:end_lineno]
    return [line.strip() for line in lines if len(line.strip()) >= 15]


def _shared_run(issue_tokens: list[str], body_tokens: list[str]) -> int:
    """Longest run of consecutive body tokens that also appears in the issue."""
    if not body_tokens or not issue_tokens:
        return 0
    grams = {tuple(issue_tokens[i:i + NGRAM]) for i in range(len(issue_tokens) - NGRAM + 1)}
    best = current = 0
    for i in range(len(body_tokens) - NGRAM + 1):
        if tuple(body_tokens[i:i + NGRAM]) in grams:
            current = max(current, NGRAM)
            j = i + NGRAM
            while j < len(body_tokens) and body_tokens[j] in issue_tokens:
                current += 1
                j += 1
            best = max(best, current)
            i = j
        else:
            current = 0
    return best


def _init(repos: str) -> None:
    global _INDEX
    _INDEX = SnapshotIndex(repos)


def _work(task: dict) -> dict:
    assert _INDEX is not None
    gold = task["_gold"]
    path = _INDEX.path_for(task)
    if path is None:
        return {"instance_id": task["instance_id"], "error": "no_snapshot"}

    issue = task.get("problem_statement") or ""
    issue_norm = _normalise(issue)
    issue_tokens = tokenize(issue)

    line_hits = 0
    run = 0
    checked = 0
    with Snapshot(path) as snap:
        for entry in gold["files"]:
            if entry.get("language") != "python":
                continue
            source = snap.read_text(entry["path"])
            if not source:
                continue
            table = python_symbols(source)
            for symbol in entry.get("symbols", []):
                containing = resolve(table, symbol["lineno"])
                start = containing.lineno if containing else symbol["lineno"]
                end = containing.end_lineno if containing else symbol["end_lineno"]
                lines = _body_lines(source, start, end)
                checked += 1
                for line in lines:
                    if _normalise(line) and _normalise(line) in issue_norm:
                        line_hits += 1
                        break
                body = "\n".join(lines)
                run = max(run, _shared_run(issue_tokens, tokenize(body)))

    return {
        "instance_id": task["instance_id"],
        "repo": task.get("repo", ""),
        "symbols": checked,
        "line_quote": line_hits > 0,
        "line_hits": line_hits,
        "token_run": run,
        "long_quote": run >= LONG_RUN,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_lite.jsonl"))
    ap.add_argument("--gold", default=str(ROOT / "data" / "gold_symbols.jsonl"))
    ap.add_argument("--rows", default=str(ROOT / "data" / "experiment_v3.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--out", default=str(ROOT / "data" / "body_evidence.jsonl"))
    ap.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    gold = {row["instance_id"]: row for row in
            (json.loads(line) for line in Path(args.gold).open(encoding="utf-8") if line.strip())}
    tasks = [json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip()]
    tasks = [task for task in tasks if task["instance_id"] in gold and gold[task["instance_id"]]["has_symbols"]]
    if args.limit:
        tasks = tasks[: args.limit]
    for task in tasks:
        task["_gold"] = gold[task["instance_id"]]

    started = time.time()
    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.jobs, initializer=_init,
                             initargs=(args.repos,)) as pool:
        futures = {pool.submit(_work, task): task for task in tasks}
        for done, future in enumerate(as_completed(futures), 1):
            try:
                rows.append(future.result())
            except Exception as exc:  # noqa: BLE001
                task = futures[future]
                rows.append({"instance_id": task["instance_id"], "error": f"{type(exc).__name__}: {exc}"})
            if done % 40 == 0 or done == len(tasks):
                print(f"  {done}/{len(tasks)}  {done / (time.time() - started):.2f} task/s", flush=True)

    ok = [row for row in rows if "error" not in row]
    out = Path(args.out)
    with out.open("w", encoding="utf-8") as fh:
        for row in sorted(ok, key=lambda r: r["instance_id"]):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    hits = {row["instance_id"]: row for row in ok}
    v3 = {row["instance_id"]: row for row in
          (json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip())}

    def found_top10(instance_id: str) -> bool | None:
        row = v3.get(instance_id)
        if not row or not row.get("arms"):
            return None
        return row["arms"]["text"]["recall@10"] > 0

    print(f"\ntasks checked: {len(ok)}  ({round(time.time() - started, 1)}s)")
    line_quote = [row for row in ok if row["line_quote"]]
    long_quote = [row for row in ok if row["long_quote"]]
    print(f"issue contains a verbatim body line: {len(line_quote)} "
          f"({len(line_quote) / len(ok):.1%})")
    print(f"issue shares a run of >= {LONG_RUN} tokens with a body: {len(long_quote)} "
          f"({len(long_quote) / len(ok):.1%})")

    for name, subset in (("verbatim line", line_quote), ("long token run", long_quote)):
        found = [row for row in subset if found_top10(row["instance_id"]) is True]
        print(f"  of the {len(subset)} with a {name}, top-10 already contains the symbol: "
              f"{len(found)} ({len(found) / max(len(subset), 1):.1%})")

    print(f"median longest shared run: {statistics.median([row['token_run'] for row in ok]):.0f} tokens")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
