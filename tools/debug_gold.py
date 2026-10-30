"""One task, both methods, every intermediate value. For eyeballing disagreements."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.gold import DictSnapshot, build_record  # noqa: E402
from experiments.snapindex import SnapshotIndex  # noqa: E402
from experiments.snapshot import Snapshot  # noqa: E402
from experiments.symbols import python_symbols, resolve  # noqa: E402

import tools.verify_gold as vg  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("instance_id")
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_lite.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--context", type=int, default=6)
    args = ap.parse_args(argv)
    tasks = [json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip()]
    task = next(t for t in tasks if t["instance_id"] == args.instance_id)
    path = SnapshotIndex(args.repos).path_for(task)
    files = vg.parse_verbose(task["patch"])
    wanted = [f["old"] if f["old"] != vg.DEV_NULL else f["new"] for f in files]
    with Snapshot(path) as snap:
        texts = snap.subset_text(wanted)
    record = build_record(task, None, snap=DictSnapshot(texts))
    print(f"{task['instance_id']}  files={len(files)}")
    for entry, prod in zip(files, record["files"]):
        old, new = entry["old"], entry["new"]
        pre = texts.get(old.replace("\\", "/").lstrip("./"))
        print(f"\n=== {old} -> {new}   in_snapshot={pre is not None} "
              f"prod_path={prod['path']} symbols={[s['qualname'] for s in prod['symbols']]} "
              f"unresolved={prod['unresolved_anchors']} anchors={prod['anchors']}")
        if pre is None:
            continue
        table = python_symbols(pre)
        lines = pre.splitlines()
        for hunk in entry["hunks"]:
            got = vg.anchors(hunk)
            print(f"  {hunk['header']}  old_len={hunk['old_len']} anchors={len(got)}")
        print("  anchor -> line -> symbol")
        for line in prod["anchors"]:
            text = lines[line - 1] if 0 < line <= len(lines) else "<out of range>"
            sym = resolve(table, line)
            print(f"    {line:5d}  {text.strip()[:60]:60s} -> {sym.qualname if sym else 'NONE'}")
        info = vg.method_b(pre, entry["hunks"])
        print(f"  B: pre_parse={info['pre_parse']} post_fail={info['post_parse_fail']} "
              f"ctx_mismatch={info['context_mismatches']} gold={info['gold']} "
              f"added={info['added']} moved={info['moved']}")
        # first mismatching context lines, to see whether the applier is wrong
        post_lines, _ = vg.apply_hunks(lines, entry["hunks"])
        pos = 0
        shown = 0
        for hunk in entry["hunks"]:
            begin = hunk["old_start"] - 1 if hunk["old_len"] > 0 else hunk["old_start"]
            pos = begin
            for mark, text in hunk["lines"]:
                if mark == " ":
                    if pos < len(lines) and lines[pos].rstrip() != text.rstrip() and shown < args.context:
                        print(f"    MISMATCH old line {pos + 1}:\n      file {lines[pos]!r}\n      diff {text!r}")
                        shown += 1
                    pos += 1
                elif mark == "-":
                    pos += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
