"""Re-derive the gold set with line-number repair, and check the shipped one against it.

Three independent answers per task, all from the same patch:

  A   shipped: `experiments/gold.py` (anchor -> innermost pre-fix definition)
  B3  oracle : for every definition, compare its *own* source text (nested defs
               cut out) between the pre-fix tree and the patched tree. A
               definition is gold iff its own text changed or it disappeared.
               This needs no line numbers, so a stale hunk header cannot break it.
  C   repair : A with two fixes -- hunks are re-located in the file by matching
               their context lines, and a brand-new definition is attributed to
               the pre-fix parent it was inserted into (the only symbol a
               retriever could have returned).

C is what a corrected pipeline would ship; B3 says whether C is right.

    python tools/gold_fix.py --limit 300
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.gold import DictSnapshot, build_record  # noqa: E402
from experiments.snapindex import SnapshotIndex  # noqa: E402
from experiments.snapshot import Snapshot  # noqa: E402

import tools.verify_gold as vg  # noqa: E402

SEARCH = 400


def own_text(source: str, node: ast.AST) -> str:
    """A definition's text with every nested definition's text cut out."""
    lines = source.splitlines()
    start = node.lineno
    for dec in getattr(node, "decorator_list", []) or []:
        start = min(start, dec.lineno)
    end = getattr(node, "end_lineno", None) or start
    drop = set()
    stack = [node]
    while stack:
        current = stack.pop()
        for child in ast.iter_child_nodes(current):
            if type(child) in vg.DEFS:
                for line in range(child.lineno, (getattr(child, "end_lineno", None) or child.lineno) + 1):
                    drop.add(line)
                stack.append(child)
            else:
                stack.append(child)
    kept = [lines[i - 1].rstrip() for i in range(start, end + 1) if i not in drop]
    return "\n".join(line for line in kept if line.strip())


def oracle(pre_source: str | None, post_lines: list[str]) -> dict | None:
    """B3: definitions whose own text changed, or that vanished."""
    if pre_source is None:
        return None
    pre_tree = vg.parse_tree(pre_source)
    post_text = "\n".join(post_lines)
    post_tree = vg.parse_tree(post_text)
    if pre_tree is None:
        return None
    if post_tree is None:
        return None
    pre = vg.def_nodes(pre_tree)
    post = vg.def_nodes(post_tree)
    changed = {q for q, n in pre.items() if q in post and own_text(pre_source, n) != own_text(post_text, post[q])}
    removed = {q for q in pre if q not in post}
    return {"gold": sorted(changed | removed), "changed": sorted(changed), "removed": sorted(removed),
            "added": sorted(q for q in post if q not in pre)}


def locate(hunk: dict, lines: list[str]) -> tuple[int, int]:
    """Where this hunk really sits in the file. Returns (offset, matched_lines)."""
    expected = [text.rstrip() for mark, text in hunk["lines"] if mark in (" ", "-")]
    if not expected:
        return 0, 0
    base = hunk["old_start"] - 1
    span = len(expected)
    lo, hi = max(0, base - SEARCH), min(len(lines) - span, base + SEARCH)
    best = None
    for pos in range(lo, hi + 1):
        if all(lines[pos + i].rstrip() == expected[i] for i in range(span)):
            distance = abs(pos - base)
            if best is None or distance < best[0]:
                best = (distance, pos)
    if best is not None:
        return best[1] - base, span
    for width in (3, 2, 1):  # truncated patches: match the head of the hunk
        if span < width:
            continue
        for pos in range(lo, hi + 1):
            if all(lines[pos + i].rstrip() == expected[i] for i in range(width)):
                return pos - base, width
    return 0, 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_lite.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=str(ROOT / "data" / "gold_fixed.jsonl"))
    ap.add_argument("--jobs-off", action="store_true")
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip()]
    if args.limit:
        tasks = tasks[: args.limit]
    index = SnapshotIndex(args.repos)
    stats = Counter()
    rows = []

    for number, task in enumerate(tasks, 1):
        path = index.path_for(task)
        if path is None:
            stats["no_snapshot"] += 1
            continue
        entries = vg.parse_verbose(task.get("patch") or "")
        wanted = [e["old"] if e["old"] != vg.DEV_NULL else e["new"] for e in entries]
        with Snapshot(path) as snap:
            texts = snap.subset_text(wanted)
        record = build_record(task, None, snap=DictSnapshot(texts))

        gold_a: set[str] = set()
        gold_c: set[str] = set()
        gold_b3: set[str] = set()
        files = []
        for entry, prod in zip(entries, record["files"]):
            old, new = entry["old"], entry["new"]
            rel = old.replace("\\", "/").lstrip("./")
            pre_source = texts.get(rel)
            gold_a |= {f"{prod['path']}::{s['qualname']}" for s in prod["symbols"]}
            info = {"old": old, "new": new, "symbols_c": [], "symbols_b3": [],
                    "offset": 0, "aligned": True, "added": [], "repaired_anchors": 0}

            if pre_source is None or prod["language"] != "python":
                files.append(info)
                continue
            lines = pre_source.splitlines()
            # -- repair the hunk positions -------------------------------------
            shifts = []
            matched_all = True
            for hunk in entry["hunks"]:
                offset, matched = locate(hunk, lines)
                shifts.append(offset)
                info["repaired_anchors"] += int(offset != 0)
                matched_all = matched_all and matched > 0
            info["aligned"] = matched_all
            if any(s != 0 for s in shifts):
                info["offset"] = max(set(shifts), key=shifts.count)
                stats["tasks_repaired"] += 1
                info["aligned"] = False

            shifted = []
            for hunk, offset in zip(entry["hunks"], shifts):
                moved = dict(hunk)
                moved["old_start"] = max(1, hunk["old_start"] + offset)
                shifted.append(moved)

            table = vg.symbol_table(pre_source)
            for line in sorted({a for hunk in shifted for a in vg.anchors(hunk)}):
                node = vg.resolve_node(table, line)
                if node is not None:
                    gold_c.add(f"{old}::{node}")

            post_tree = vg.parse_tree("\n".join(vg.apply_hunks(lines, shifted)[0]))
            names = {q for q, _s, _e in table}
            added = [q for q in vg.def_nodes(post_tree) if q not in names] if post_tree is not None else []
            info["added"] = sorted(added)
            for qualname in info["added"]:
                parent = qualname.rsplit(".", 1)[0] if "." in qualname else ""
                if parent and parent in names:
                    gold_c.add(f"{old}::{parent}")
                    info["symbols_c"].append(f"{parent} (parent of new {qualname})")

            post_lines, _ = vg.apply_hunks(lines, shifted)
            got = oracle(pre_source, post_lines)
            if got is not None:
                gold_b3 |= {f"{old}::{q}" for q in got["gold"]}
                info["symbols_b3"] = got["gold"]
            files.append(info)

        stats["tasks"] += 1
        stats["gold_a"] += len(gold_a)
        stats["gold_c"] += len(gold_c)
        stats["gold_b3"] += len(gold_b3)
        stats["task_a_eq_b3"] += int(gold_a == gold_b3)
        stats["task_c_eq_b3"] += int(gold_c == gold_b3)
        if gold_a != gold_b3:
            stats["task_a_differs"] += 1
        if gold_c != gold_b3:
            stats["task_c_differs"] += 1
        rows.append({
            "instance_id": task["instance_id"], "repo": task.get("repo"),
            "gold_a": sorted(gold_a), "gold_c": sorted(gold_c), "gold_b3": sorted(gold_b3),
            "files": files,
        })
        if number % 50 == 0:
            print(f"  {number}/{len(tasks)}  A==B3 {stats['task_a_eq_b3']}  C==B3 {stats['task_c_eq_b3']}",
                  flush=True)

    Path(args.out).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                              encoding="utf-8")
    print(json.dumps(dict(sorted(stats.items())), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
