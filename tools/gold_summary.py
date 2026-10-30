"""One table: how the shipped gold set compares with the repaired and oracle sets."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def names(symbols) -> list[str]:
    return sorted(symbol.split("::", 1)[1] for symbol in symbols)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "gold_fixed.jsonl"
    rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
    buckets = Counter()
    examples: dict[str, list[str]] = {}
    for row in rows:
        a, b3, c = set(row["gold_a"]), set(row["gold_b3"]), set(row["gold_c"])
        stale = any(f["offset"] for f in row["files"])
        added = any(f["added"] for f in row["files"])
        if a == b3:
            kind = "identical"
        elif not a and b3:
            kind = "shipped empty, oracle has a symbol"
        elif a - b3 and not (b3 - a):
            kind = "shipped adds the enclosing class"
        elif b3 - a and not (a - b3):
            kind = "shipped misses a changed definition"
        else:
            kind = "both differ"
        key = kind + (" [stale hunk lines]" if stale else "")
        buckets[key] += 1
        if kind != "identical":
            examples.setdefault(key, []).append(
                f"{row['instance_id']}: shipped={names(a) or '-'} oracle={names(b3) or '-'} "
                f"repaired={names(c) or '-'}{' added_defs' if added else ''}")

    print(f"tasks {len(rows)}\n")
    for key, count in buckets.most_common():
        print(f"  {count:4d}  {key}")
    print()
    for key, items in examples.items():
        print(f"### {key} ({len(items)})")
        for item in sorted(items):
            print("   ", item)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
