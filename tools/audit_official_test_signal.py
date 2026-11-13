"""How informative are the hidden tests for main-track localization? (offline)

Parses each official task's test_patch (new test files/functions) and gold patch
(files changed) and measures whether the test id could route a repair.  This is
the main-track counterpart of tools/audit_test_signal.py; it reads the frozen
official tasks.jsonl, which is not part of the public clone.

    python tools/audit_official_test_signal.py --tasks .cache/main-track/official/tasks.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

FILE = re.compile(r"^\+\+\+ b/(.+)$", re.M)
NEW_TEST = re.compile(r"^\+def (test_[A-Za-z0-9_]+)", re.M)
DEF_CHANGE = re.compile(r"^[+-]\s*def ([A-Za-z0-9_]+)", re.M)


def parse(patch: str) -> tuple[set[str], set[str]]:
    files = {path.strip() for path in FILE.findall(patch or "")}
    names = {name for name in NEW_TEST.findall(patch or "")} | set(DEF_CHANGE.findall(patch or ""))
    return files, names


def tokens(text: str) -> set[str]:
    return {part.lower() for part in re.split(r"[^A-Za-z0-9]+", text) if part and part.lower() not in {"test", "tests"}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, default=Path(".cache/main-track/official/tasks.jsonl"))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    rows = [json.loads(line) for line in args.tasks.read_text(encoding="utf-8").splitlines() if line.strip()]
    stats: Counter = Counter()
    for row in rows:
        gold_files, gold_defs = parse(row.get("patch") or "")
        test_files, test_defs = parse(row.get("test_patch") or "")
        stats["tasks"] += 1
        stats["with_test_patch"] += bool(test_files)
        gold_stems = {Path(path).stem for path in gold_files}
        test_stems = {Path(path).stem.removeprefix("test_") for path in test_files}
        stats["stem_overlap"] += bool(gold_stems & test_stems)
        gold_tokens = set()
        for path in gold_files:
            gold_tokens |= tokens(Path(path).stem)
        for name in gold_defs:
            gold_tokens |= tokens(name)
        test_tokens = set()
        for name in test_defs:
            test_tokens |= tokens(name)
        stats["test_name_token_overlap"] += bool(test_tokens & gold_tokens)
        # test file lives in a directory named after a gold file's stem
        stats["test_dir_matches_gold_stem"] += any(
            stem in path for path in test_files for stem in gold_stems)
    total = stats["tasks"]
    for key, value in stats.items():
        print(f"{key}: {value}  ({value / total * 100:.1f}%)")
    if args.out:
        args.out.write_text(json.dumps(dict(stats), indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
