"""Audit the answer key: re-derive the gold symbol set by a second, independent method.

Method A (production, `experiments/gold.py`): a changed line anchors an old-side
line number; the innermost pre-fix definition containing that line is gold.

Method B (this file): rebuild the post-fix file from the diff, parse both trees,
and take every definition whose source text differs -- then keep the innermost
ones. No line numbers are shared between the two methods: B never looks at an
anchor, A never compares source text.

Where they disagree the disagreement is printed with the diff, so a human can
decide which one is right instead of trusting either.

    python tools/verify_gold.py --limit 300
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.gold import DictSnapshot, build_record  # noqa: E402
from experiments.snapindex import SnapshotIndex  # noqa: E402
from experiments.snapshot import Snapshot  # noqa: E402

DEV_NULL = "/dev/null"
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def clean_path(raw: str) -> str:
    path = raw.strip()
    if path.startswith('"') and path.endswith('"'):
        path = path[1:-1]
    if "\t" in path:
        path = path.split("\t", 1)[0]
    if path == DEV_NULL:
        return DEV_NULL
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return path


def parse_verbose(text: str) -> list[dict]:
    """Diff text -> [{old, new, hunks:[{old_start, old_len, header, lines}]}]."""
    files: list[dict] = []
    current = None
    hunk = None
    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            current = None
            hunk = None
            continue
        if raw.startswith("--- ") and not raw.startswith("---\t"):
            current = {"old": clean_path(raw[4:]), "new": clean_path(raw[4:]), "hunks": []}
            files.append(current)
            hunk = None
            continue
        if raw.startswith("+++ ") and current is not None:
            current["new"] = clean_path(raw[4:])
            continue
        if raw.startswith("@@") and current is not None:
            match = HUNK_RE.match(raw)
            if not match:
                hunk = None
                continue
            hunk = {
                "old_start": int(match.group(1)),
                "old_len": int(match.group(2)) if match.group(2) is not None else 1,
                "header": raw,
                "lines": [],
            }
            current["hunks"].append(hunk)
            continue
        if hunk is None:
            continue
        if raw.startswith("\\"):
            continue
        if raw == "":
            hunk["lines"].append((" ", ""))
            continue
        mark = raw[0]
        if mark not in (" ", "+", "-"):
            continue
        hunk["lines"].append((mark, raw[1:]))
    return [f for f in files if f["hunks"]]


def anchors(hunk: dict) -> list[int]:
    """Old-side line numbers, computed without touching production code."""
    line = hunk["old_start"]
    out = []
    for mark, _text in hunk["lines"]:
        if mark == "-":
            out.append(line)
            line += 1
        elif mark == "+":
            out.append(max(line - 1, 1))
        else:
            line += 1
    return out


def apply_hunks(old_lines: list[str], hunks: list[dict]) -> tuple[list[str], int]:
    """Rebuild the post-fix file. Returns (lines, context_mismatches)."""
    out: list[str] = []
    pos = 0  # 0-based cursor into old_lines
    mismatches = 0
    for hunk in hunks:
        start = hunk["old_start"]
        # POSIX: for an empty old range the number is the line *after* which the
        # insertion happens, so the cursor lands on `start` itself.
        begin = start - 1 if hunk["old_len"] > 0 else start
        out.extend(old_lines[pos:begin])
        pos = begin
        for mark, text in hunk["lines"]:
            if mark == " ":
                if pos < len(old_lines) and old_lines[pos].rstrip() != text.rstrip():
                    mismatches += 1
                out.append(old_lines[pos] if pos < len(old_lines) else text)
                pos += 1
            elif mark == "-":
                pos += 1
            else:
                out.append(text)
    out.extend(old_lines[pos:])
    return out, mismatches


def _segment(source: str, node: ast.AST) -> str:
    start = node.lineno
    for dec in getattr(node, "decorator_list", []) or []:
        start = min(start, dec.lineno)
    end = getattr(node, "end_lineno", None) or start
    lines = source.splitlines()[start - 1:end]
    return "\n".join(line.rstrip() for line in lines).strip("\n")


def parse_tree(source: str) -> ast.AST | None:
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError):
        return None


def def_nodes(tree: ast.AST) -> dict[str, ast.AST]:
    """{qualname: innermost-first definition node} for a parsed file."""
    found: dict[str, ast.AST] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if type(child) not in DEFS:
                walk(child, prefix)
                continue
            qualname = f"{prefix}.{child.name}" if prefix else child.name
            found.setdefault(qualname, child)
            walk(child, qualname)

    walk(tree, "")
    return found


def symbol_table(source: str) -> list[tuple[str, int, int]]:
    """[(qualname, lineno, end_lineno)] with the same naming production uses."""
    tree = parse_tree(source)
    if tree is None:
        return []
    return [(q, n.lineno, getattr(n, "end_lineno", None) or n.lineno)
            for q, n in def_nodes(tree).items()]


def resolve_node(table: list[tuple[str, int, int]], line: int) -> str | None:
    """Innermost definition containing `line`, tie-broken by later start."""
    best: tuple[int, int, str] | None = None
    for qualname, start, end in table:
        if start <= line <= end:
            key = (qualname.count("."), start, qualname)
            if best is None or key >= best:
                best = key
    return best[2] if best else None


def definitions(source: str) -> dict[str, dict] | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    found: dict[str, dict] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if type(child) not in DEFS:
                walk(child, prefix)
                continue
            name = getattr(child, "name", "")
            qualname = f"{prefix}.{name}" if prefix else name
            entry = found.get(qualname)
            text = _segment(source, child)
            if entry is None:
                found[qualname] = {
                    "kind": "class" if isinstance(child, ast.ClassDef) else "function",
                    "lineno": child.lineno,
                    "end": getattr(child, "end_lineno", None) or child.lineno,
                    "text": text,
                }
            else:  # same name defined twice in one scope: compare the union
                entry["text"] += "\n#---\n" + text
            walk(child, qualname)

    walk(tree, "")
    return found


def method_b(pre_source: str | None, hunks: list[dict]) -> dict:
    """Gold by pre/post text comparison. `gold` keeps pre-fix names only."""
    out = {"pre_parse": False, "post_parse_fail": False, "gold": [], "added": [],
           "moved": [], "context_mismatches": 0}
    if pre_source is None:
        return out
    pre = definitions(pre_source)
    if pre is None:
        out["pre_parse"] = True
        return out
    post_lines, mismatches = apply_hunks(pre_source.splitlines(), hunks)
    out["context_mismatches"] = mismatches
    post = definitions("\n".join(post_lines))
    if post is None:
        out["post_parse_fail"] = True
        return out  # patched file does not parse: cannot compare

    changed = {q for q in pre if q in post and pre[q]["text"] != post[q]["text"]}
    removed = {q for q in pre if q not in post}
    added = [q for q in post if q not in pre]
    candidate = changed | removed

    def innermost(names: set[str]) -> list[str]:
        return sorted(q for q in names if not any(r != q and r.startswith(q + ".") for r in names))

    out["gold"] = innermost(candidate)
    out["added"] = sorted(added)
    # A definition that only moved keeps its text; A still sees '-' and '+' lines.
    out["moved"] = sorted(q for q in removed if q in added)
    return out


def is_test_path(path: str) -> bool:
    parts = path.lower().replace("\\", "/").split("/")
    return any(p in ("test", "tests", "testing") for p in parts[:3]) or Path(path).name.startswith("test_")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_lite.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=str(ROOT / "data" / "gold_check.jsonl"))
    ap.add_argument("--samples", default=str(ROOT / "data" / "gold_check_samples.txt"))
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip()]
    if args.limit:
        tasks = tasks[: args.limit]
    index = SnapshotIndex(args.repos)
    stats = Counter()
    rows = []
    samples: list[str] = []
    missing = 0

    for number, task in enumerate(tasks, 1):
        path = index.path_for(task)
        if path is None:
            missing += 1
            continue
        wanted = [fp["old"] if fp["old"] != DEV_NULL else fp["new"]
                  for fp in parse_verbose(task.get("patch") or "")]
        with Snapshot(path) as snap:
            texts = snap.subset_text(wanted)
        record = build_record(task, None, snap=DictSnapshot(texts))

        files = parse_verbose(task.get("patch") or "")
        per_file = []
        for entry in files:
            old_path = entry["old"]
            new_path = entry["new"]
            pre_source = texts.get(old_path.replace("\\", "/").lstrip("./"))
            production = next((f for f in record["files"]
                               if f["path"] == (old_path if old_path != DEV_NULL else new_path)),
                              None)
            gold_a = sorted(f"{production['path']}::{s['qualname']}" for s in (production or {}).get("symbols", []))
            info = method_b(pre_source, entry["hunks"])
            gold_b = sorted(f"{old_path}::{q}" for q in info["gold"]) if old_path != DEV_NULL else []

            is_new_file = old_path == DEV_NULL
            is_deleted = new_path == DEV_NULL
            parse_fail = info["pre_parse"] or info["post_parse_fail"]
            probe = {
                "old": old_path, "new": new_path, "new_file": is_new_file,
                "deleted_file": is_deleted, "python": (production or {}).get("language") == "python",
                "anchors": sum(len(anchors(h)) for h in entry["hunks"]),
                "unresolved": (production or {}).get("unresolved_anchors", 0),
                "missing_source": (production or {}).get("missing_source", False),
                "gold_a": gold_a, "gold_b": gold_b,
                "added_defs": info["added"], "moved_defs": info["moved"],
                "context_mismatches": info["context_mismatches"],
                "zero_len_hunks": sum(1 for h in entry["hunks"] if h["old_len"] == 0),
                "plus_only_file": all(m != "-" for h in entry["hunks"] for m, _ in h["lines"]),
                "parse_fail": bool(parse_fail),
            }
            per_file.append(probe)

            stats["files"] += 1
            stats["python_files"] += int(probe["python"])
            stats["new_files"] += int(is_new_file)
            stats["deleted_files"] += int(is_deleted)
            stats["parse_fail"] += int(probe["parse_fail"])
            stats["zero_len_hunks"] += probe["zero_len_hunks"]
            stats["context_mismatches"] += probe["context_mismatches"]
            stats["anchors"] += probe["anchors"]
            stats["unresolved"] += probe["unresolved"]
            stats["missing_source"] += int(probe["missing_source"])
            stats["gold_a"] += len(gold_a)
            stats["gold_b"] += len(gold_b)
            stats["test_gold_a"] += sum(1 for g in gold_a if is_test_path(g.split("::")[0]))
            stats["test_gold_b"] += sum(1 for g in gold_b if is_test_path(g.split("::")[0]))
            stats["added_defs"] += len(info["added"])

            if not probe["python"]:
                continue
            set_a, set_b = set(gold_a), set(gold_b)
            if set_a == set_b:
                stats["file_agree"] += 1
            elif set_a and set_b and set_a < set_b:
                stats["file_a_subset"] += 1
            elif set_a and set_b and set_b < set_a:
                stats["file_a_superset"] += 1
            elif not set_a and set_b:
                stats["file_a_empty"] += 1
            elif set_a and not set_b:
                stats["file_b_empty"] += 1
            else:
                stats["file_differ"] += 1

        gold_a_all = sorted({g for f in per_file for g in f["gold_a"]})
        gold_b_all = sorted({g for f in per_file for g in f["gold_b"]})
        if not any(f["python"] for f in per_file):
            stats["task_non_python"] += 1
        if not gold_a_all:
            stats["task_no_gold_a"] += 1
        if not gold_b_all:
            stats["task_no_gold_b"] += 1
        if gold_a_all == gold_b_all:
            stats["task_agree"] += 1
        else:
            stats["task_differ"] += 1
        if gold_a_all and gold_b_all and not set(gold_a_all) & set(gold_b_all):
            stats["task_disjoint"] += 1

        rows.append({
            "instance_id": task["instance_id"], "repo": task.get("repo"),
            "gold_a": gold_a_all, "gold_b": gold_b_all, "files": per_file,
        })

        if gold_a_all != gold_b_all and len(samples) < 12:
            samples.append(render_sample(task, per_file, gold_a_all, gold_b_all))
        if number % 50 == 0:
            print(f"  {number}/{len(tasks)} tasks  agree {stats['task_agree']}", flush=True)

    stats["tasks"] = len(rows)
    stats["missing_snapshots"] = missing
    Path(args.out).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                              encoding="utf-8")
    Path(args.samples).write_text("\n\n".join(samples), encoding="utf-8")
    print(json.dumps(dict(sorted(stats.items())), indent=2))
    return 0


def render_sample(task: dict, per_file: list[dict], gold_a: list[str], gold_b: list[str]) -> str:
    out = [f"===== {task['instance_id']}  ({task.get('repo')})",
           "--- gold A (production): " + (", ".join(gold_a) or "(empty)"),
           "--- gold B (text diff): " + (", ".join(gold_b) or "(empty)")]
    for probe in per_file:
        flag = "" if probe["gold_a"] == probe["gold_b"] else "   <<< DIFFER"
        out.append(f"  file {probe['old']} -> {probe['new']}{flag}")
        out.append(f"    anchors {probe['anchors']}  unresolved {probe['unresolved']}  "
                   f"zero-len hunks {probe['zero_len_hunks']}  added defs {probe['added_defs']}  "
                   f"moved {probe['moved_defs']}")
    out.append("--- diff")
    out.append(task.get("patch") or "")
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
