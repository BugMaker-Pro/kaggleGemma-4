"""Line-level coverage: do the ten slots cover the lines the patch actually edits?

Symbol recall asks whether the shortlist names the right definition; a patch that
touches three lines inside one function is served by that function, but a task
whose patch spans two functions is only half served by one of them. Counting
*lines* answers the question a patch author asks: is the place I have to edit
inside the shortlist?

Each changed line is mapped to its enclosing gold symbol (the innermost one), so
this needs no repository access — the mapping was computed once by `gold.py`.

    python tools/line_coverage.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.analyse import bootstrap_ci, sign_test  # noqa: E402

ARMS = ("text", "graph_rerank", "graph_open", "graph_open2", "graph_fuse",
        "graph_fuse_precise", "graph_ppr", "graph_ppr_text")


def module_of(path: str) -> str:
    stem = path[:-3] if path.endswith(".py") else path
    parts = [part for part in stem.split("/") if part not in ("", ".")]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def anchor_symbols(record: dict) -> tuple[list[str | None], int]:
    """One node id per changed line, or None when the line sits outside any def."""
    mapped: list[str | None] = []
    unresolved = 0
    for entry in record.get("files", []):
        if entry.get("language") != "python":
            continue
        module = module_of(entry["path"])
        symbols = entry.get("symbols", [])
        for anchor in entry.get("anchors", []):
            best = None
            for symbol in symbols:
                if symbol["lineno"] <= anchor <= symbol["end_lineno"]:
                    if best is None or symbol["lineno"] > best["lineno"]:
                        best = symbol
            if best is None:
                mapped.append(None)
                unresolved += 1
            else:
                mapped.append(f"{module}.{best['qualname']}" if module else best["qualname"])
    return mapped, unresolved


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "experiment_v3.jsonl"))
    ap.add_argument("--gold", default=str(ROOT / "data" / "gold_symbols.jsonl"))
    args = ap.parse_args(argv)

    gold = {row["instance_id"]: row for row in
            (json.loads(line) for line in Path(args.gold).open(encoding="utf-8") if line.strip())}
    rows = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    rows = [row for row in rows if row.get("arms")]

    per_task: list[dict] = []
    for row in rows:
        record = gold.get(row["instance_id"])
        if record is None:
            continue
        mapped, unresolved = anchor_symbols(record)
        if not mapped:
            continue
        per_task.append({"instance_id": row["instance_id"], "lines": mapped,
                         "unresolved": unresolved, "arms": row["arms"],
                         "gold_nodes": set(row["gold_nodes"])})

    print(f"tasks: {len(per_task)}  changed lines: "
          f"{sum(len(t['lines']) for t in per_task)}  "
          f"outside any definition: {sum(t['unresolved'] for t in per_task)}\n")

    def line_recall(task: dict, arm: str, k: int) -> float:
        top = set(task["arms"][arm]["top"][:k])
        lines = task["lines"]
        return sum(1 for node in lines if node is not None and node in top) / len(lines)

    def symbol_recall(task: dict, arm: str, k: int = 10) -> float:
        top = set(task["arms"][arm]["top"][:k])
        gold = task["gold_nodes"]
        return len(top & gold) / len(gold)

    print(f"{'arm':20s}{'symbol r@10':>12s}{'line r@5':>9s}{'line r@10':>10s}"
          f"{'any line@10':>12s}")
    for arm in ARMS:
        symbol = statistics.fmean(symbol_recall(t, arm) for t in per_task)
        line5 = statistics.fmean(line_recall(t, arm, 5) for t in per_task)
        line10 = statistics.fmean(line_recall(t, arm, 10) for t in per_task)
        anyline = statistics.fmean(
            1.0 if any(n is not None and n in set(t["arms"][arm]["top"][:10])
                       for n in t["lines"]) else 0.0 for t in per_task)
        print(f"{arm:20s}{symbol:12.3f}{line5:9.3f}{line10:10.3f}{anyline:12.3f}")

    print("\n== paired at line level (vs text) ==")
    print(f"{'arm':20s}{'delta@10':>10s}{'95% CI':>18s}{'W/L':>9s}{'p':>7s}")
    for arm in ARMS[1:]:
        deltas, wins, losses = [], 0, 0
        for task in per_task:
            delta = line_recall(task, arm, 10) - line_recall(task, "text", 10)
            deltas.append(delta)
            wins += delta > 0
            losses += delta < 0
        lo, hi = bootstrap_ci(deltas)
        print(f"{arm:20s}{statistics.fmean(deltas):+10.3f}"
              f"{(round(lo, 3), round(hi, 3))!s:>18s}{wins:5d}/{losses:3d}"
              f"{sign_test(wins, losses):7.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
