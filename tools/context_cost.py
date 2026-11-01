"""What does file granularity cost the agent?

For every scored Lite task, measure the text the agent must read under each
granularity:

  file    - the gold file, in full
  symbol  - the touched definition plus its enclosing class

Both are read from the pre-fix snapshot, so the numbers are the bytes an agent
would actually receive. This is the cost side of the granularity gap: recall
says how often the right thing is in the shortlist, this says how much text
arrives when it is.
"""
from __future__ import annotations

import json
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load(name: str) -> list[dict]:
    with (ROOT / name).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def scored_tasks() -> list[str]:
    gold = {row["instance_id"]: row for row in load("data/gold_symbols.jsonl")}
    return sorted(task for task, row in gold.items() if row.get("has_symbols"))


def work(task: str) -> dict:
    from experiments.snapindex import SnapshotIndex
    from experiments.snapshot import Snapshot
    from experiments.symbols import python_symbols

    gold = {row["instance_id"]: row for row in load("data/gold_symbols.jsonl")}[task]
    issues = {row["instance_id"]: row for row in load("data/swebench_lite.jsonl")}
    index = SnapshotIndex(str(ROOT / "data" / "repos"))
    path = index.path_for(issues[task])
    if path is None:
        return {}

    file_chars = symbol_chars = file_lines = symbol_lines = definitions = 0
    with Snapshot(path) as snap:
        for file in gold.get("files") or []:
            text = snap.subset_text([file["path"]]).get(file["path"]) or ""
            if not text:
                continue
            lines = text.splitlines()
            file_chars += len(text)
            file_lines += len(lines)
            definitions += len(python_symbols(text))
            spans = []
            for symbol in file.get("symbols") or []:
                start = max(0, (symbol.get("lineno") or 1) - 1)
                end = min(len(lines), symbol.get("end_lineno") or start + 1)
                spans.append((start, end))
            if spans:
                lo, hi = min(s for s, _ in spans), max(e for _, e in spans)
                block = "\n".join(lines[lo:hi])
                symbol_chars += len(block)
                symbol_lines += hi - lo
    return {"task": task, "file_chars": file_chars, "symbol_chars": symbol_chars,
            "file_lines": file_lines, "symbol_lines": symbol_lines,
            "definitions": definitions}


def main() -> None:
    tasks = scored_tasks()
    with ProcessPoolExecutor(max_workers=12) as pool:
        rows = [row for row in pool.map(work, tasks) if row and row["symbol_chars"]]
    rows = [row for row in rows if row["symbol_chars"] > 0]
    print(f"tasks {len(rows)}")
    file_chars = [row["file_chars"] for row in rows]
    symbol_chars = [row["symbol_chars"] for row in rows]
    ratios = [f / s for f, s in zip(file_chars, symbol_chars)]
    defs = [row["definitions"] for row in rows]
    share = [s / f for f, s in zip(file_chars, symbol_chars)]

    print(f"file    median {statistics.median(file_chars):>8,.0f} chars  "
          f"mean {statistics.fmean(file_chars):>9,.0f}")
    print(f"symbol  median {statistics.median(symbol_chars):>8,.0f} chars  "
          f"mean {statistics.fmean(symbol_chars):>9,.0f}")
    print(f"ratio   median {statistics.median(ratios):>8.1f}x    "
          f"mean {statistics.fmean(ratios):>9.1f}x")
    print(f"the definition is {statistics.median(share) * 100:.1f}% of the file (median)")
    print(f"definitions in the gold file: median {statistics.median(defs):.0f}, "
          f"mean {statistics.fmean(defs):.1f}")
    for cut in (10, 25, 50, 100):
        n = sum(1 for r in ratios if r >= cut)
        print(f"  ratio >= {cut:3d}x: {n:3d} tasks")

    out = ROOT / "data" / "context_cost.jsonl"
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
