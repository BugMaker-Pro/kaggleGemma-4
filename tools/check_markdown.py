"""Report markdown that renders badly on Kaggle's writeup editor.

The editor is a rich-text box, not a CommonMark viewer: a stray pipe inside a
table cell shifts every column after it, `<module>` looks like an HTML tag and
can be swallowed, and a table that is not preceded by a blank line joins the
paragraph above it. This script finds those three, plus the general shape of
the document, before a human pastes it.

    python tools/check_markdown.py [path]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAG = re.compile(r"<(/?[A-Za-z][A-Za-z0-9 _\-]*)>")
LINK = re.compile(r"!?\[[^\]]*\]\([^)]*\)")


def cells(line: str) -> list[str]:
    """Split a table row on pipes that are neither escaped nor inside backticks."""
    out, current, in_code, index = [], "", False, 0
    while index < len(line):
        char = line[index]
        if char == "`":
            in_code = not in_code
        if char == "\\" and index + 1 < len(line) and line[index + 1] == "|":
            current += "|"
            index += 2
            continue
        if char == "|" and not in_code:
            out.append(current)
            current = ""
            index += 1
            continue
        current += char
        index += 1
    out.append(current)
    return [part.strip() for part in out[1:-1]] if line.strip().startswith("|") else [part.strip() for part in out]


def main(argv=None) -> int:
    path = Path(argv[1]) if argv and len(argv) > 1 else ROOT / "paper" / "submission_body.md"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    problems: list[str] = []

    in_code = False
    tables = 0
    header_cells = 0
    for number, line in enumerate(lines, 1):
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if line.strip().startswith("|"):
            width = len(cells(line))
            if not line.strip().endswith("|"):
                problems.append(f"{number}: table row has no closing pipe")
            if number == 1 or not lines[number - 2].strip():
                tables += 1
                header_cells = width
                if len(line) > 200:
                    problems.append(f"{number}: table is {len(line)} chars wide ({width} columns)")
            elif set(line.replace("|", "").replace(":", "").strip()) <= {"-", " "}:
                continue
            elif width != header_cells:
                problems.append(f"{number}: {width} cells against a {header_cells}-cell header "
                                f"(stray pipe inside a cell?)")
        # a `<name>` outside a code span is an HTML tag as far as a renderer is concerned
        outside_code = re.sub(r"`[^`]*`", "", line)
        for match in TAG.finditer(outside_code):
            problems.append(f"{number}: <{match.group(1)}> is an HTML-like token: "
                            f"wrap it in backticks")

    print(f"{path.name}: {len(lines)} lines, {len(text.split())} words, "
          f"{tables} tables, {len(LINK.findall(text))} links/images")
    if in_code:
        problems.append("unbalanced ``` fence")
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for problem in problems:
            print(f"  {problem}")
    else:
        print("\nno structural problems found")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
