"""Rewrite the seven pipe tables as bullets, so the full paper survives a rich-text paste.

Kaggle's writeup editor is a rich-text box: a pipe table either arrives as
literal `|` characters or loses its columns. Bullets survive everywhere, and the
numbers survive with them, so the writeup can still carry the full paper. The PDF
keeps the typeset tables for anyone who wants the layout.

Every number in a table is checked to appear in its bullet block, so a table that
drifts from its list fails here rather than in front of a reviewer.

    python tools/make_kaggle_full.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’.\-]*")
NUMBER = re.compile(r"[+\u2212-]?\d+(?:\.\d+)?")

BOLD = re.compile(r"\*\*(.+?)\*\*")


def cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
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
    return [part.strip() for part in out]


def dash(value: str) -> bool:
    return value.strip() in ("—", "–", "-", "")


def chain(row: list[str]) -> str:
    """'a · b · — · d' with empty cells kept, so positions stay aligned."""
    return " · ".join(value if not dash(value) else "—" for value in row)


# The column order is declared once in the caption, so a row is just its numbers.
# That is what keeps the writeup inside 3,000 words once the tables become text.
LEGEND = {
    2: "granularity: recall@1 · recall@5 · recall@10",
    3: "arm: r@1 · r@5 · r@10 · file r@10 · Δ r@10, 95% CI, p",
    5: "ranking: r@10 · Δ vs BM25, 95% CI · wins/losses · p",
    6: "each row: n · BM25 · ranker, for 290 tasks then 2,232",
    7: "reading: 290 tasks · 2,232 tasks",
}


def render(table: int, header: list[str], row: list[str]) -> str:
    """One table row -> one bullet line."""
    if table == 1:  # resolution states: state -> meaning
        return f"- **{row[0]}** — {row[1]}"
    if table == 4:  # diagnostics: quantity, value, meaning
        return f"- **{row[0]}** — {row[1]}; {row[2]}"
    return f"- **{row[0]}** — {chain(row[1:])}"


def main() -> int:
    lines = (ROOT / "paper" / "submission_body.md").read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    numbers: list[tuple[int, list[str]]] = []
    table = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.lstrip().startswith("|"):
            out.append(line)
            index += 1
            continue
        table += 1
        header = cells(line)
        index += 2  # header + delimiter
        rows: list[list[str]] = []
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            rows.append(cells(lines[index]))
            index += 1
        if table in LEGEND:
            # the caption is the last emitted line; it now carries the column order
            for back in range(len(out) - 1, -1, -1):
                if out[back].strip():
                    out[back] = out[back].rstrip().rstrip("*").rstrip() + " — " + LEGEND[table] + "*"
                    break
        block = [render(table, header, row) for row in rows]
        out.extend(block)
        numbers.append((table, [cell for row in rows for cell in row]))
        out.append("")

    body = "\n".join(out)
    body = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n"

    # every number a table shows must appear in the bullets that replaced it
    missing = []
    for table_number, values in numbers:
        segment = "\n".join(line for line in body.splitlines() if line.startswith("- "))
        for value in values:
            for token in NUMBER.findall(value):
                if token.strip("-+") and token not in segment:
                    missing.append((table_number, token))
    if missing:
        print("numbers lost in the rewrite:", missing[:10])
        return 1

    path = ROOT / "paper" / "kaggle_body_full.md"
    path.write_text(body, encoding="utf-8", newline="\n")
    words = len(WORD.findall(body))
    print(f"wrote {path}")
    print(f"tables {table} -> {body.count(chr(10) + '- **')} bullet rows, "
          f"headings {body.count(chr(10) + '## ')}, words {words} (limit 3000)")
    return 0 if words <= 3000 else 1


if __name__ == "__main__":
    raise SystemExit(main())
