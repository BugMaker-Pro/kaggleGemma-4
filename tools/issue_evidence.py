"""What does the issue text itself hand over?

A traceback names the file and the line; a backticked identifier names the class;
a path mentions the module. BM25 tokenises all of that away, which is why the
file is found only 29% of the time at rank one. This census measures how much
structural evidence the 300 issues actually contain, and how precise it is.

    python tools/issue_evidence.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PATH_RE = re.compile(r"[\w./\\-]+\.py\b")
FRAME_RE = re.compile(r'File "([^"]+)", line (\d+)')
LINE_RE = re.compile(r"(?:line|:)\s*(\d{1,5})\b")
BACKTICK_RE = re.compile(r"`([A-Za-z_][\w.]*)`")


def normalise(path: str) -> str:
    path = path.replace("\\", "/").split("/site-packages/")[-1]
    return path.lstrip("./")


def main() -> int:
    tasks = [json.loads(line) for line in
             (ROOT / "data" / "swebench_lite.jsonl").open(encoding="utf-8") if line.strip()]
    gold = {row["instance_id"]: row for row in
            (json.loads(line) for line in
             (ROOT / "data" / "gold_symbols.jsonl").open(encoding="utf-8") if line.strip())}

    stats = {"tasks": 0, "path_named": 0, "path_correct": 0, "frame": 0,
             "frame_correct_file": 0, "frame_in_gold_symbol": 0,
             "tick": 0, "tick_correct": 0}
    details = []

    for task in tasks:
        record = gold.get(task["instance_id"])
        if not record or not record["has_symbols"]:
            continue
        stats["tasks"] += 1
        issue = task.get("problem_statement") or ""
        gold_files = {normalise(entry["path"]) for entry in record["files"]
                      if entry.get("language") == "python"}
        symbols = [(entry["path"], sym) for entry in record["files"]
                   for sym in entry.get("symbols", [])]
        basenames = {path.rsplit("/", 1)[-1] for path in gold_files}

        named = {normalise(match) for match in PATH_RE.findall(issue)}
        hit_file = {path for path in named
                    if path in gold_files or path.rsplit("/", 1)[-1] in basenames}
        if named:
            stats["path_named"] += 1
            if hit_file:
                stats["path_correct"] += 1

        frames = FRAME_RE.findall(issue)
        if frames:
            stats["frame"] += 1
            for path, line in frames:
                path = normalise(path)
                line = int(line)
                if path.rsplit("/", 1)[-1] in basenames:
                    stats["frame_correct_file"] += 1
                    for entry in record["files"]:
                        for sym in entry.get("symbols", []):
                            if sym["lineno"] <= line <= sym["end_lineno"]:
                                stats["frame_in_gold_symbol"] += 1
                                break

        ticks = set(BACKTICK_RE.findall(issue))
        leaf_names = {sym["qualname"].rsplit(".", 1)[-1] for _, sym in symbols}
        if ticks:
            stats["tick"] += 1
            if ticks & leaf_names:
                stats["tick_correct"] += 1

        details.append({
            "instance_id": task["instance_id"],
            "paths": sorted(named)[:3], "path_hit": bool(hit_file),
            "frames": frames[:3], "ticks": sorted(ticks)[:5],
        })

    total = stats["tasks"]
    print(f"tasks with gold symbols: {total}\n")
    print(f"issue names a .py path:      {stats['path_named']:3d} "
          f"({stats['path_named'] / total:.1%})  of which correct file: "
          f"{stats['path_correct']} ({stats['path_correct'] / max(stats['path_named'], 1):.1%})")
    print(f"issue has a traceback frame: {stats['frame']:3d} "
          f"({stats['frame'] / total:.1%})  frame names a gold file: "
          f"{stats['frame_correct_file']}  frame lands inside a gold symbol: "
          f"{stats['frame_in_gold_symbol']}")
    print(f"issue has a backticked name: {stats['tick']:3d} "
          f"({stats['tick'] / total:.1%})  matches a gold leaf name: "
          f"{stats['tick_correct']} ({stats['tick_correct'] / max(stats['tick'], 1):.1%})")

    with (ROOT / "data" / "issue_evidence.jsonl").open("w", encoding="utf-8") as fh:
        for row in details:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("\nwrote data/issue_evidence.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
