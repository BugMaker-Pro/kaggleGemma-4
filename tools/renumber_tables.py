"""Renumber the tables after the gap: 5 -> 4, 6 -> 5, 7 -> 6.

The paper lost a table during trimming and the later ones were never renumbered,
so a reviewer would ask where Table 4 went. Ascending order is safe: each pass
only creates numbers that have already been handled.

    python tools/renumber_tables.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = [ROOT / "paper" / "main.md", ROOT / "tools" / "audit_numbers.py"]


def main() -> int:
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        before = text
        for old, new in ((5, 4), (6, 5), (7, 6)):
            text = re.sub(rf"\bTable {old}\b", f"Table {new}", text)
        if text != before:
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"renumbered {path.relative_to(ROOT)}")
    remaining = sorted(set(re.findall(r"Table \d", (ROOT / "paper" / "main.md").read_text(encoding="utf-8"))))
    print("table numbers now:", remaining)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
