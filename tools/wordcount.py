"""Word budget for the draft: prose, tables and headings, counted separately.

    python tools/wordcount.py paper/main.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’.\-]*")


def sections(text: str) -> list[tuple[str, str]]:
    """Split on `## ` headings so the budget can be checked per section."""
    parts = re.split(r"^## ", text, flags=re.M)
    out = [("front", parts[0])]
    for part in parts[1:]:
        title, _, body = part.partition("\n")
        out.append((title.strip(), body))
    return out


def count(body: str) -> dict[str, int]:
    prose_lines, table_lines, heading_lines = [], [], []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") or stripped.startswith("*Table"):
            table_lines.append(stripped)
        elif stripped.startswith("#"):
            heading_lines.append(stripped)
        else:
            prose_lines.append(stripped)
    prose = len(WORD.findall("\n".join(prose_lines)))
    tables = len(WORD.findall(" ".join(table_lines)))
    return {"prose": prose, "tables": tables,
            "total": prose + tables + len(WORD.findall(" ".join(heading_lines)))}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = Path(argv[0] if argv else "paper/main.md")
    text = path.read_text(encoding="utf-8")
    totals = {"prose": 0, "tables": 0, "total": 0}
    print(f"{'section':38s}{'prose':>7s}{'tables':>8s}{'total':>7s}")
    for title, body in sections(text):
        stats = count(body)
        for key in totals:
            totals[key] += stats[key]
        print(f"{title[:37]:38s}{stats['prose']:7d}{stats['tables']:8d}{stats['total']:7d}")
    print("-" * 60)
    print(f"{'all':38s}{totals['prose']:7d}{totals['tables']:8d}{totals['total']:7d}")
    print(f"budget 3000, headroom {3000 - totals['total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
