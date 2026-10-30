"""Render the submission body to HTML, because Kaggle's editor does not parse markdown on paste.

The writeup editor is a rich-text box: a bulk paste of markdown arrives as
literal `##`, `**` and pipes. Pasting *rendered* rich text instead carries the
headings, bold runs and real tables across, so this produces a standalone HTML
preview: open it in a browser, select all, copy, paste into the writeup.

Only the constructs the paper actually uses are handled -- headings, bold,
italic, inline code, pipe tables, images, paragraphs -- which is less code than
pulling in a markdown package and keeps the environment unchanged.

    python tools/make_html.py
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOLD = re.compile(r"\*\*(.+?)\*\*")
ITALIC = re.compile(r"(?<![\*\w])\*([^*\n]+?)\*(?![\*\w])")
CODE = re.compile(r"`([^`]+)`")
IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")

STYLE = """
body { margin: 0; background: #ffffff; }
main { max-width: 780px; margin: 0 auto; padding: 32px 28px 64px;
       font: 16px/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       color: #1a1a1a; }
h2 { font-size: 21px; margin: 34px 0 10px; padding-bottom: 4px;
     border-bottom: 1px solid #e6e6e6; }
p { margin: 0 0 12px; }
em { color: #333; }
code { font: 14px/1.4 "Cascadia Mono", Consolas, monospace; background: #f4f4f6;
       padding: 1px 4px; border-radius: 3px; }
table { border-collapse: collapse; width: 100%; margin: 4px 0 18px;
        font-size: 13.5px; }
th, td { border: 1px solid #dcdce0; padding: 3px 7px; }
th { background: #f6f6f8; text-align: left; font-weight: 600; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
img { max-width: 100%; display: block; margin: 6px auto 4px; }
.caption { font-size: 14px; color: #444; }
"""


def inline(text: str) -> str:
    """Escape, then put the markup back in. Code spans are protected first."""
    spans: list[str] = []

    def keep(match: re.Match[str]) -> str:
        spans.append(html.escape(match.group(1)))
        return f"\x00{len(spans) - 1}\x00"

    text = CODE.sub(keep, text)
    text = html.escape(text)
    text = IMAGE.sub(lambda m: f'<img src="{html.escape(m.group(2))}" alt="{html.escape(m.group(1))}">', text)
    text = LINK.sub(lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', text)
    text = BOLD.sub(r"<strong>\1</strong>", text)
    text = ITALIC.sub(r"<em>\1</em>", text)
    for index, span in enumerate(spans):
        text = text.replace(f"\x00{index}\x00", f"<code>{span}</code>")
    return text


def split_cells(line: str) -> list[str]:
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


def alignment(delimiter: str) -> list[str]:
    styles = []
    for cell in split_cells(delimiter):
        left, right = cell.startswith(":"), cell.endswith(":")
        styles.append("center" if left and right else "right" if right else "left")
    return styles


def render(markdown: str) -> str:
    lines = markdown.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith("## "):
            out.append(f"<h2>{inline(line[3:].strip())}</h2>")
            index += 1
            continue
        if line.lstrip().startswith("|"):
            header = split_cells(line)
            delimiter = lines[index + 1] if index + 1 < len(lines) else ""
            align = alignment(delimiter)
            out.append("<table>")
            out.append("<thead><tr>" + "".join(
                f'<th class="{"n" if align[i] == "right" else ""}">{inline(cell)}</th>'
                for i, cell in enumerate(header)) + "</tr></thead><tbody>")
            index += 2
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                cells = split_cells(lines[index])
                out.append("<tr>" + "".join(
                    f'<td class="{"n" if i < len(align) and align[i] == "right" else ""}">'
                    f"{inline(cell)}</td>" for i, cell in enumerate(cells)) + "</tr>")
                index += 1
            out.append("</tbody></table>")
            continue
        paragraph = [line]
        index += 1
        while index < len(lines) and lines[index].strip() and not lines[index].lstrip().startswith("|"):
            paragraph.append(lines[index])
            index += 1
        text = inline("\n".join(paragraph))
        if len(paragraph) == 1 and paragraph[0].startswith("*") and paragraph[0].rstrip().endswith("*"):
            out.append(f'<p class="caption">{inline(paragraph[0].strip()[1:-1])}</p>')
        else:
            out.append(f"<p>{text}</p>")
    return "\n".join(out)


def main(argv=None) -> int:
    import base64

    source = ROOT / "paper" / "submission_body.md"
    body = render(source.read_text(encoding="utf-8"))
    # A relative <img> is dead once the markup leaves this directory. Inlining
    # the PNG as a data URI keeps the file self-contained, so a browser copy
    # carries the pixels and the editor has a chance to import them.
    png = ROOT / "paper" / "fig1.png"
    if png.exists():
        encoded = base64.b64encode(png.read_bytes()).decode("ascii")
        body = body.replace('src="fig1.png"', f'src="data:image/png;base64,{encoded}"')

    page = (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">\n"
        "<title>File-Level Is Not Symbol-Level</title>\n"
        f"<style>{STYLE}</style></head>\n<body><main>\n{body}\n</main></body></html>\n"
    )
    out = ROOT / "paper" / "submission_body.html"
    out.write_text(page, encoding="utf-8", newline="\n")
    tables = body.count("<table>")
    print(f"wrote {out}  ({len(page) / 1024:.0f} KB, {body.count('<h2>')} headings, "
          f"{tables} tables, {body.count('<img')} image, "
          f"{body.count('class=\"caption\"')} captions)")
    leftovers = [token for token in ("**", "](", "`") if token in body]
    if leftovers:
        print(f"unconverted markup still present: {leftovers}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
