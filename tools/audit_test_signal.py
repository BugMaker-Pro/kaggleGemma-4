"""Audit how much localization signal the failing-test ids carry (offline).

For every Lite task with a symbol answer key, compare the FAIL_TO_PASS test file
and test name with the gold module/qualname.  This is the cheap complement to
traceback parsing: a test id is always present, while a source frame is not.

    python tools/audit_test_signal.py
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STOP = {"test", "tests"}


def load(name: str) -> list[dict]:
    text = (ROOT / "data" / name).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def tokens(text: str) -> set[str]:
    return {part.lower() for part in re.split(r"[^A-Za-z0-9]+", text)
            if part and part.lower() not in STOP}


def audit() -> dict:
    tasks = {row["instance_id"]: row for row in load("swebench_lite.jsonl")}
    gold = {row["instance_id"]: row for row in load("gold_symbols.jsonl")}
    stats: Counter = Counter()
    for task, record in gold.items():
        if not record.get("has_symbols"):
            continue
        stats["tasks"] += 1
        modules: set[str] = set()
        names: set[str] = set()
        for file in record.get("files") or []:
            module = file["path"].removesuffix(".py").replace("/", ".")
            modules.add(module)
            for symbol in file.get("symbols") or []:
                modules.add(symbol.get("qualname", ""))
                names |= tokens(symbol.get("qualname", ""))
        f2p = tasks[task].get("FAIL_TO_PASS") or []
        stats["tasks_with_f2p"] += bool(f2p)
        test_files = {node.split("::")[0] for node in f2p}
        near = False
        for test_file in test_files:
            parent = (test_file.rsplit("/tests/", 1)[0] if "/tests/" in test_file
                      else test_file.rsplit("/", 1)[0]).replace("/", ".")
            if any(module == parent or module.startswith(parent + ".") or parent.startswith(module + ".")
                   for module in modules):
                near = True
        stats["test_file_near_gold_module"] += near
        test_names: set[str] = set()
        for node in f2p:
            test_names |= tokens(node.split("::")[-1].split("[")[0])
        stats["test_name_token_overlap"] += bool(test_names & names)
        stems = {Path(test_file).stem.removeprefix("test_") for test_file in test_files}
        leaves = {module.rsplit(".", 1)[-1] for module in modules if module}
        stats["test_stem_matches_gold_leaf"] += bool(stems & leaves)
    return dict(stats)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    stats = audit()
    total = stats.get("tasks", 0)
    for key, value in stats.items():
        print(f"{key}: {value}  ({value / total * 100:.1f}%)" if total else f"{key}: {value}")
    if args.out:
        args.out.write_text(json.dumps(stats, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
