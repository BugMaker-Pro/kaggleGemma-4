"""Walk one task from diff to gold symbols, so the answer key can be checked by eye.

For each hunk: the old-side coordinates, every anchor it produces, the pre-fix
line each anchor points at, and the innermost definition containing it. This is
the exact procedure `experiments/gold.py` runs over all 300 tasks.

    python tools/explain_gold.py psf__requests-2148
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.gold import DictSnapshot, build_record  # noqa: E402
from experiments.patchfile import parse as parse_patch  # noqa: E402
from experiments.snapindex import SnapshotIndex  # noqa: E402
from experiments.snapshot import Snapshot  # noqa: E402
from experiments.symbols import python_symbols, resolve  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("instance_id")
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_lite.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip()]
    task = next(t for t in tasks if t["instance_id"] == args.instance_id)
    index = SnapshotIndex(args.repos)
    path = index.path_for(task)

    print(f"{task['instance_id']}  ({task['repo']})")
    print(f"snapshot: {Path(path).name}\n")

    with Snapshot(path) as snap:
        for fp in parse_patch(task["patch"]):
            print(f"=== {fp.path}   +{fp.added} -{fp.removed}")
            source = snap.read_text(fp.path)
            lines = source.splitlines() if source else []
            table = python_symbols(source) if source else []
            for hunk in fp.hunks:
                print(f"  hunk @@ -{hunk.old_start},{hunk.old_len} "
                      f"+{hunk.new_start},{hunk.new_len} @@ {hunk.section}")
                print(f"    anchors (old-side): {hunk.anchors}")
                for anchor in hunk.anchors:
                    text = lines[anchor - 1].strip() if 0 < anchor <= len(lines) else "<out of range>"
                    sym = resolve(table, anchor)
                    where = f"{sym.qualname} ({sym.kind})" if sym else "NO DEFINITION"
                    print(f"      line {anchor:4d}: {text[:56]:58s} -> {where}")
            if not source:
                print("  (no source at this path in the base commit)")
            print()

        record = build_record(task, None, snap=__import__("experiments.snapshot", fromlist=["Snapshot"]).Snapshot(path))
        print("gold set:")
        for entry in record["files"]:
            for sym in entry.get("symbols", []):
                print(f"  {entry['path']}::{sym['qualname']}  [{sym['kind']}] "
                      f"lines {sym['lineno']}-{sym['end_lineno']}")
            if entry.get("unresolved_anchors"):
                print(f"  {entry['path']}: {entry['unresolved_anchors']} anchor(s) outside any definition")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
