"""How much of each task's gold fix does a graph actually represent?

The interesting output is not one coverage percentage but the split between
"absent because the file is missing", "absent because the symbol is missing"
and "present under a different module path". Aggregating those hides exactly
the thing the paper is about.
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    from .coverage import MATCH_EXACT, MATCH_MISS, MATCH_MODULE_ONLY, MATCH_SUFFIX, classify
except ImportError:  # running as a script
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from experiments.coverage import (
        MATCH_EXACT, MATCH_MISS, MATCH_MODULE_ONLY, MATCH_SUFFIX, classify,
    )

KINDS = (MATCH_EXACT, MATCH_SUFFIX, MATCH_MODULE_ONLY, MATCH_MISS)
FOUND = (MATCH_EXACT, MATCH_SUFFIX)


def gold_symbols(record: dict) -> list[tuple[str, str, str]]:
    """(file, qualname, kind) for every symbol the reference patch touches."""
    out: list[tuple[str, str, str]] = []
    for entry in record.get("files", []):
        if entry.get("language") != "python":
            continue
        for sym in entry.get("symbols", []):
            out.append((entry["path"], sym["qualname"], sym["kind"]))
    return out


def evaluate(record: dict, node_ids: set[str], unresolved_anchors: int = 0) -> dict:
    """Coverage of one task's gold symbols by one graph."""
    counts = {kind: 0 for kind in KINDS}
    missed: list[dict] = []
    symbols = gold_symbols(record)
    for path, qualname, sym_kind in symbols:
        kind, in_module = classify(path, qualname, node_ids)
        counts[kind] += 1
        if kind not in FOUND:
            missed.append(
                {"file": path, "qualname": qualname, "kind": sym_kind,
                 "reason": kind, "nodes_in_module": in_module}
            )

    total = len(symbols)
    found = counts[MATCH_EXACT] + counts[MATCH_SUFFIX]
    return {
        "instance_id": record.get("instance_id", ""),
        "repo": record.get("repo", ""),
        "gold": total,
        "found": found,
        "coverage": (found / total) if total else None,
        "counts": counts,
        "unresolved_anchors": unresolved_anchors,
        "missed": missed,
    }


def aggregate(rows: list[dict]) -> dict:
    counts = {kind: 0 for kind in KINDS}
    gold = found = 0
    for row in rows:
        gold += row["gold"]
        found += row["found"]
        for kind in KINDS:
            counts[kind] += row["counts"][kind]
    per_task = [r["coverage"] for r in rows if r["coverage"] is not None]
    return {
        "tasks": len(rows),
        "tasks_with_gold": len(per_task),
        "gold_symbols": gold,
        "found": found,
        "coverage": (found / gold) if gold else None,
        "mean_task_coverage": (sum(per_task) / len(per_task)) if per_task else None,
        "counts": counts,
        "tasks_fully_covered": sum(1 for c in per_task if c == 1.0),
    }


def by_repo(rows: list[dict]) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["repo"], []).append(row)
    return {repo: aggregate(group) for repo, group in sorted(groups.items())}


def load_rows(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
