"""E0: extract gold symbols from each task's reference patch.

Input : tasks.jsonl (instance_id, repo, base_commit, patch, ...)
        snapshots/<instance_id>.tgz  (repository at base_commit)
Output: data/gold_symbols.jsonl, one record per task.

This file is the denominator of every coverage number, so it reports what it
could not resolve instead of silently dropping it.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

try:
    from .patchfile import FilePatch, parse as parse_patch
    from .snapindex import SnapshotIndex
    from .snapshot import Snapshot
    from .symbols import language_of, python_symbols, resolve
except ImportError:  # running as a script: python experiments/gold.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from experiments.patchfile import FilePatch, parse as parse_patch
    from experiments.snapindex import SnapshotIndex
    from experiments.snapshot import Snapshot
    from experiments.symbols import language_of, python_symbols, resolve


def _file_record(fp: FilePatch, snap: Snapshot | None) -> dict:
    language = language_of(fp.path)
    anchors = fp.anchors()
    record = {
        "path": fp.path,
        "language": language,
        "added": fp.added,
        "removed": fp.removed,
        "anchors": anchors,
        "symbols": [],
        "unresolved_anchors": len(anchors),
        "missing_source": False,
    }
    if language != "python" or snap is None:
        return record

    source = snap.read_text(fp.path)
    if source is None:
        record["missing_source"] = True
        return record

    table = python_symbols(source)
    seen: set[tuple[str, str]] = set()
    resolved_count = 0
    for line in anchors:
        sym = resolve(table, line)
        if sym is None:
            continue
        resolved_count += 1
        key = (sym.qualname, sym.kind)
        if key in seen:
            continue
        seen.add(key)
        record["symbols"].append(
            {
                "qualname": sym.qualname,
                "kind": sym.kind,
                "lineno": sym.lineno,
                "end_lineno": sym.end_lineno,
            }
        )
    record["unresolved_anchors"] = len(anchors) - resolved_count
    return record


class DictSnapshot:
    """A snapshot already held in memory, for callers that parsed the repo anyway.

    The graph builder reads every `.py` file of a repository in one pass; making
    the gold-symbol extractor re-open the same tarball would double the I/O for
    no information.
    """

    def __init__(self, files: dict[str, str]) -> None:
        self.files = {path.replace("\\", "/"): text for path, text in files.items()}

    def read_text(self, path: str) -> str | None:
        return self.files.get(path.replace("\\", "/").lstrip("./"))

    def close(self) -> None:
        return None


def build_record(task: dict, snapshots: SnapshotIndex | None, snap=None) -> dict:
    instance_id = task.get("instance_id", "")
    patch = task.get("patch") or ""
    files = parse_patch(patch)

    if snap is None and snapshots is not None:
        snap = snapshots.open(task)

    try:
        file_records = [_file_record(fp, snap) for fp in files]
    finally:
        if snap is not None:
            snap.close()

    return {
        "instance_id": instance_id,
        "repo": task.get("repo", ""),
        "base_commit": task.get("base_commit", ""),
        "patch_files": len(file_records),
        "added": sum(f["added"] for f in file_records),
        "removed": sum(f["removed"] for f in file_records),
        "has_symbols": any(f["symbols"] for f in file_records),
        "files": file_records,
    }


def _patched_files(task: dict, index: SnapshotIndex | None):
    """The patch's own files, read in one pass, or None when there is no snapshot."""
    if index is None:
        return None
    path = index.path_for(task)
    if path is None:
        return None
    wanted = [fp.path for fp in parse_patch(task.get("patch") or "")]
    with Snapshot(path) as snap:
        return DictSnapshot(snap.subset_text(wanted))


def run(
    tasks_path: Path,
    out_path: Path,
    snapshots_dir: Path | None = None,
    limit: int | None = None,
    quiet: bool = False,
) -> dict:
    stats = {
        "tasks": 0,
        "tasks_with_symbols": 0,
        "python_files": 0,
        "other_files": 0,
        "symbols": 0,
        "missing_source": 0,
        "with_snapshot": 0,
    }
    index = SnapshotIndex(snapshots_dir) if snapshots_dir is not None else None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tasks_path.open("r", encoding="utf-8") as fh, out_path.open(
        "w", encoding="utf-8"
    ) as out:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            task = json.loads(line)
            record = build_record(task, index, snap=_patched_files(task, index))
            stats["tasks"] += 1
            stats["tasks_with_symbols"] += int(record["has_symbols"])
            for entry in record["files"]:
                if entry["language"] == "python":
                    stats["python_files"] += 1
                else:
                    stats["other_files"] += 1
                stats["symbols"] += len(entry["symbols"])
                stats["missing_source"] += int(entry["missing_source"])
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            if limit is not None and stats["tasks"] >= limit:
                break
    if snapshots_dir is not None:
        missing = len(set(index.missing)) if index else 0
        stats["with_snapshot"] = stats["tasks"] - missing
        if missing:
            stats["missing_snapshots"] = missing
    if not quiet:
        print(json.dumps(stats, indent=2))
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract gold symbols (E0)")
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--snapshots", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if not args.tasks.exists():
        print(f"tasks file not found: {args.tasks}", file=sys.stderr)
        return 2
    run(args.tasks, args.out, args.snapshots, args.limit, args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
