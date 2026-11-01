"""What does the issue offer on the tasks the pool misses?

The 27.6% tail (80 tasks, no gold in the top-500 pool) is where every arm in the
paper fails. This counts, over those 80, how often the issue supplies anything
exact at all:

  name  - the gold symbol's leaf identifier appears in the issue text
  body  - a verbatim line of the gold symbol's body appears in the issue
  path  - the issue names a file the patch touches
  frame - a traceback frame names such a file

All four are exact matches: no training, no graph, no embedding. The union is the
cheapest ceiling for any pool built from what an issue states.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name: str) -> list[dict]:
    with (ROOT / name).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def leaf(qualname: str) -> str:
    name = qualname.rsplit(".", 1)[-1]
    return "" if name == "__init__" else name


def census() -> dict:
    ablation = {row["instance_id"]: row for row in load("data/ablation.jsonl")}
    gold = {row["instance_id"]: row for row in load("data/gold_symbols.jsonl")}
    body = {row["instance_id"]: row for row in load("data/body_evidence.jsonl")}
    issue = {row["instance_id"]: row for row in load("data/issue_evidence.jsonl")}
    text = {row["instance_id"]: (row.get("problem_statement") or "")
            for row in load("data/swebench_lite.jsonl")}

    tail = [task for task, row in ablation.items()
            if row.get("pool_recall") and float(row["pool_recall"].get("500", 1)) == 0.0]
    tail.sort()
    counts = {"tail": len(tail), "name": 0, "body": 0, "path": 0, "frame": 0, "any": 0}
    for task in tail:
        leaves = set()
        for file in gold[task].get("files") or []:
            for symbol in file.get("symbols") or []:
                name = leaf(symbol["qualname"])
                if name:
                    leaves.add(name)
        issue_text = text.get(task, "")
        name = any(re.search(rf"(?<![\w.]){re.escape(n)}(?![\w])", issue_text) for n in leaves)
        quote = bool(body[task]["line_quote"])
        path = bool(issue[task]["path_hit"])
        frame = bool(issue[task].get("frames"))
        counts["name"] += name
        counts["body"] += quote
        counts["path"] += path
        counts["frame"] += frame
        counts["any"] += bool(name or quote or path or frame)
    return counts


def main() -> None:
    counts = census()
    tail = counts["tail"]
    print(f"tail {tail} tasks")
    for key in ("name", "body", "path", "frame", "any"):
        print(f"  {key:5s} {counts[key]:3d} / {tail}  ({counts[key] / tail:.1%})")


if __name__ == "__main__":
    main()
