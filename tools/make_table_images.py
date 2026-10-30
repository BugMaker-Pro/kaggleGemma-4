"""Render each table as its own PNG, because a rich-text editor cannot typeset a table.

Bullets of bare numbers were the wrong substitute: a reader has to remember the
column order to decode `0.103 · 0.217 · 0.287 · 0.614`. An image of the table is
what the PDF shows, and an image survives a paste everywhere.

Each table is built as a one-table docx with the paper's own styling, exported to
PDF by the LibreOffice kit, rendered at 200 dpi and cropped to its ink, so what
lands in the writeup has no page margins around it.

    python tools/make_table_images.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import docx  # noqa: E402
from docx.enum.table import WD_TABLE_ALIGNMENT  # noqa: E402
from docx.shared import Cm, Pt  # noqa: E402
from PIL import Image, ImageChops  # noqa: E402

from tools.make_pdf import (CLI, NODE, add_runs, caption, column_widths,  # noqa: E402
                            keep_rows_together, light_rules, split_cells as cells)

CAPTION = __import__("re").compile(r"^(Table \d+|Figure \d+)")
# the state table has no caption line of its own: its lead-in sentence is prose
CAPTION_OVERRIDE = {"resolution": "Resolution states — seven classes, never collapsed"}


def build_document(table_label: str, caption_text: str, header: list[str],
                   rows: list[list[str]], path: Path) -> None:
    document = docx.Document()
    section = document.sections[0]
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    for attr in ("left_margin", "right_margin"):
        setattr(section, attr, Cm(1.0))
    section.top_margin, section.bottom_margin = Cm(1.0), Cm(1.0)
    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(10)

    if caption_text:
        caption(document, caption_text, keep_with_next=True)

    width = max(len(header), max((len(row) for row in rows), default=0))
    table = document.add_table(rows=1, cols=width)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for position, column in enumerate(table.columns):
        column.width = Cm(column_widths(rows, header, 17.0)[position])
    light_rules(table)

    size = 7.0 if width >= 7 else 7.8 if width >= 5 else 8.4
    for position, cell in enumerate(table.rows[0].cells):
        cell.text = ""
        paragraph = cell.paragraphs[0]
        paragraph.paragraph_format.space_after = Pt(0)
        if position < len(header):
            add_runs(paragraph, header[position], size)
            for run in paragraph.runs:
                run.bold = True
    for row in rows:
        cells_ = table.add_row().cells
        for position, cell in enumerate(cells_):
            cell.text = ""
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(0)
            if position < len(row):
                add_runs(paragraph, row[position], size)
                plain = row[position].replace("+", "").replace("-", "").replace(".", "")
                if plain.isdigit():
                    paragraph.alignment = 3  # right
    keep_rows_together(table)
    document.save(path)


def crop(path: Path) -> None:
    image = Image.open(path).convert("RGB")
    background = Image.new("RGB", image.size, (255, 255, 255))
    box = ImageChops.difference(image, background).getbbox()
    if box is None:
        return
    padding = 6
    left, top, right, bottom = box
    image.crop((max(0, left - padding), max(0, top - padding),
                min(image.width, right + padding), min(image.height, bottom + padding))).save(path)


def main() -> int:
    import tempfile

    lines = (ROOT / "paper" / "submission_body.md").read_text(encoding="utf-8").splitlines()
    produced = []
    index = 0
    ordinal = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("|"):
            index += 1
            continue
        ordinal += 1
        caption_text = ""
        for back in range(index - 1, -1, -1):
            if lines[back].strip():
                caption_text = lines[back].strip().strip("*").strip()
                break
        match = CAPTION.match(caption_text)
        label = match.group(1).split(" ")[-1] if match else "resolution"
        caption_text = CAPTION_OVERRIDE.get(label, caption_text.replace("**", "").strip())
        header = cells(lines[index])
        index += 2
        rows: list[list[str]] = []
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            rows.append(cells(lines[index]))
            index += 1
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            docx_path = work / f"table_{label}.docx"
            pdf_path = work / f"table_{label}.pdf"
            build_document(label, caption_text, header, rows, docx_path)
            subprocess.run([NODE, CLI, "convert", "--input", str(docx_path),
                            "--output", str(pdf_path)], capture_output=True, text=True)
            if not pdf_path.exists():
                print(f"table {label}: conversion failed")
                return 1
            render_root = work / "render"
            result = subprocess.run([NODE, CLI, "render", "--input", str(pdf_path),
                                     "--output-dir", str(render_root), "--pages", "1",
                                     "--dpi", "200"], capture_output=True, text=True)
            page = render_root / "page-0001.png"
            if not page.exists():
                print(f"table {label}: render failed: {result.stderr[:200]}")
                return 1
            target = ROOT / "paper" / f"table_{label}.png"
            target.write_bytes(page.read_bytes())
            crop(target)
            produced.append((target.name, target.stat().st_size))

    for name, size in produced:
        print(f"{name:20s} {size / 1024:6.1f} KB")
    print(f"{len(produced)} table image(s) in paper/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
