"""Build an arXiv-ready PDF of the submission body: markdown -> docx -> PDF.

The Kaggle writeup editor is a rich-text box, and a paper with seven tables
survives it badly. The Paper Track also accepts a PDF, and a PDF is what a
reviewer will actually read, so this produces one from the same
`paper/submission_body.md` the writeup uses.

Layout follows the convention a reviewer expects: a table's caption sits above
the table (it introduces the columns), a figure's caption below the figure (the
image is read first). Labels are bold-italic in both cases so the two read as
one family, the table rules are light and horizontal only, and a caption never
gets separated from what it labels.

    python tools/make_pdf.py        # writes paper/submission.pdf
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import docx  # noqa: E402
from docx.enum.section import WD_ORIENT  # noqa: E402
from docx.enum.table import WD_TABLE_ALIGNMENT  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Cm, Pt, RGBColor  # noqa: E402

TOKEN = re.compile(r"(\*\*.+?\*\*|(?<![\*\w])\*[^*\n]+?\*(?![\*\w])|`[^`]+`)")
CAPTION = re.compile(r"^(Figure \d+|Table \d+)\s*[—–-]\s*(.*)$")
NODE = r"D:\deepseekharness\resources\runtime\primary-runtime\dependencies\node\bin\node.exe"
CLI = ("D:\\deepseekharness\\resources\\app.asar.unpacked\\dsh\\node_modules\\"
       "@deepseek-ai\\libreoffice-kit\\lib\\cli.js")

INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x44, 0x44, 0x44)
RULE = "BFBFBF"


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


def add_runs(paragraph, text: str, size: float, color: RGBColor | None = None) -> None:
    for piece in TOKEN.split(text):
        if not piece:
            continue
        run = paragraph.add_run()
        if piece.startswith("**") and piece.endswith("**"):
            run.text, run.bold = piece[2:-2], True
        elif piece.startswith("`") and piece.endswith("`"):
            run.text, run.font.name, run.font.size = piece[1:-1], "Consolas", Pt(size - 0.8)
        elif piece.startswith("*") and piece.endswith("*"):
            run.text, run.italic = piece[1:-1], True
        else:
            run.text = piece
        if run.font.size is None:
            run.font.size = Pt(size)
        run.font.color.rgb = color if color is not None else INK


def caption(document, text: str, keep_with_next: bool) -> None:
    """'Figure 1 — ...' / 'Table 2 — ...' with the label bold-italic."""
    match = CAPTION.match(text)
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(6)
    paragraph.paragraph_format.space_after = Pt(2)
    paragraph.paragraph_format.keep_with_next = keep_with_next
    if match:
        label = paragraph.add_run(f"{match.group(1)} — ")
        label.bold = label.italic = True
        label.font.size = Pt(8.6)
        label.font.color.rgb = MUTED
        add_runs(paragraph, match.group(2), 8.6, MUTED)
        for run in paragraph.runs[1:]:
            run.italic = True
    else:
        add_runs(paragraph, text, 8.6, MUTED)
        for run in paragraph.runs:
            run.italic = True


def light_rules(table) -> None:
    """Horizontal rules only: a top rule, a rule under the header, a bottom rule."""
    properties = OxmlElement("w:tblBorders")
    for edge, size, color in (("top", 8, "555555"), ("bottom", 8, "555555"),
                              ("insideH", 4, RULE), ("left", 0, "auto"),
                              ("right", 0, "auto"), ("insideV", 0, "auto")):
        element = OxmlElement(f"w:{edge}")
        element.set(qn("w:val"), "single" if size else "none")
        element.set(qn("w:sz"), str(size))
        element.set(qn("w:color"), color)
        properties.append(element)
    table._tbl.tblPr.append(properties)


def keep_rows_together(table) -> None:
    for row in table.rows:
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))


def rule_under(paragraph) -> None:
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "4")
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), "D0D0D0")
    borders.append(bottom)
    paragraph._p.get_or_add_pPr().append(borders)


def footer(section) -> None:
    paragraph = section.footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def field(name: str) -> None:
        run = paragraph.add_run()
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0x90, 0x90, 0x90)
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        instruction = OxmlElement("w:instrText")
        instruction.set(qn("xml:space"), "preserve")
        instruction.text = f" {name} "
        run._r.append(begin)
        run._r.append(instruction)
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        run._r.append(end)

    field("PAGE")


def column_widths(rows: list[list[str]], header: list[str], total: float) -> list[float]:
    """Proportional widths, so a confidence interval does not wrap while 'arm' fits."""
    columns = max(len(header), max((len(row) for row in rows), default=0))
    longest = []
    for position in range(columns):
        values = [header[position] if position < len(header) else ""]
        values += [row[position] for row in rows if position < len(row)]
        longest.append(max(len(value) for value in values) + 2)
    weight = sum(longest)
    widths = [total * value / weight for value in longest]
    return [max(width, 1.35) for width in widths]


def build(body: Path, out_docx: Path, title: str, subtitle: str) -> dict:
    document = docx.Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    for attr in ("left_margin", "right_margin"):
        setattr(section, attr, Cm(1.9))
    section.top_margin, section.bottom_margin = Cm(1.8), Cm(1.7)
    footer(section)

    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(10)
    normal.paragraph_format.space_after = Pt(4.5)
    normal.paragraph_format.line_spacing = 1.14

    heading = document.styles["Heading 1"]
    heading.font.name = "Times New Roman"
    heading.font.size = Pt(12.5)
    heading.font.bold = True
    heading.font.color.rgb = INK
    heading.paragraph_format.space_before = Pt(13)
    heading.paragraph_format.space_after = Pt(5)
    heading.paragraph_format.keep_with_next = True

    head = document.add_paragraph()
    head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    head.paragraph_format.space_after = Pt(3)
    run = head.add_run(title)
    run.bold, run.font.size = True, Pt(15.5)
    sub = document.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.paragraph_format.space_after = Pt(12)
    add_runs(sub, subtitle, 9.5, MUTED)
    for run in sub.runs:
        run.italic = True

    lines = body.read_text(encoding="utf-8").splitlines()
    image = ROOT / "paper" / "fig1.png"
    tables = figures = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith("## "):
            heading_paragraph = document.add_heading(line[3:].strip(), level=1)
            rule_under(heading_paragraph)
            index += 1
            continue
        if line.lstrip().startswith("|"):
            header = split_cells(line)
            rows = []
            index += 2  # header + delimiter
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                rows.append(split_cells(lines[index]))
                index += 1
            width = max(len(header), max((len(row) for row in rows), default=0))
            table = document.add_table(rows=1, cols=width)
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table.autofit = False
            widths = column_widths(rows, header, 17.0)
            for position, column in enumerate(table.columns):
                column.width = Cm(widths[position])
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
            property_ = OxmlElement("w:tblHeader")
            property_.set(qn("w:val"), "true")
            table.rows[0]._tr.get_or_add_trPr().append(property_)
            for row in rows:
                cells = table.add_row().cells
                for position, cell in enumerate(cells):
                    cell.text = ""
                    paragraph = cell.paragraphs[0]
                    paragraph.paragraph_format.space_after = Pt(0)
                    if position < len(row):
                        add_runs(paragraph, row[position], size)
                        plain = row[position].replace("+", "").replace("-", "").replace(".", "")
                        if plain.isdigit():
                            paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            keep_rows_together(table)
            tables += 1
            spacer = document.add_paragraph()
            spacer.paragraph_format.space_after = Pt(0)
            spacer.paragraph_format.line_spacing = 0.6
            continue
        if line.lstrip().startswith("!["):
            paragraph = document.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.space_before = Pt(4)
            paragraph.paragraph_format.space_after = Pt(2)
            paragraph.paragraph_format.keep_with_next = True  # its caption follows
            if image.exists():
                paragraph.add_run().add_picture(str(image), width=Cm(16.4))
                figures += 1
            index += 1
            continue
        if line.startswith("*") and line.rstrip().endswith("*") and not line.startswith("**"):
            inner = line.strip()[1:-1]
            is_table = inner.lstrip().startswith("Table ")
            # a table caption belongs to the table below it; a figure caption
            # belongs to the figure above it, which already keeps with next
            caption(document, inner, keep_with_next=is_table)
            index += 1
            continue
        paragraph_lines = [line]
        index += 1
        while index < len(lines) and lines[index].strip() and not lines[index].lstrip().startswith("|"):
            paragraph_lines.append(lines[index])
            index += 1
        paragraph = document.add_paragraph()
        add_runs(paragraph, " ".join(paragraph_lines), 10)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        if paragraph_lines[0].startswith("["):
            paragraph.paragraph_format.left_indent = Cm(0.55)
            paragraph.paragraph_format.first_line_indent = Cm(-0.55)
            paragraph.paragraph_format.space_after = Pt(2)
            for run in paragraph.runs:
                run.font.size = Pt(9)

    out_docx.parent.mkdir(parents=True, exist_ok=True)
    document.save(out_docx)
    return {"tables": tables, "figures": figures}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body", default=str(ROOT / "paper" / "submission_body.md"))
    ap.add_argument("--out", default=str(ROOT / "paper" / "submission.docx"))
    ap.add_argument("--keep-docx", action="store_true")
    args = ap.parse_args(argv)

    submission = (ROOT / "paper" / "submission.md").read_text(encoding="utf-8").splitlines()
    title = submission[0].strip().strip("*")
    subtitle = next(line for line in submission[1:] if line.strip()).strip().strip("*")

    out = Path(args.out)
    stats = build(Path(args.body), out, title, subtitle)
    print(f"wrote {out}  ({stats['tables']} tables, {stats['figures']} figure)")

    pdf = out.with_suffix(".pdf")
    if pdf.exists():  # the converter refuses to overwrite
        pdf.unlink()
    result = subprocess.run([NODE, CLI, "convert", "--input", str(out), "--output", str(pdf)],
                            capture_output=True, text=True)
    if result.returncode != 0 or not pdf.exists():
        print(result.stderr.strip() or result.stdout.strip())
        return 1
    signature = pdf.open("rb").read(5)
    print(f"wrote {pdf}  ({pdf.stat().st_size / 1024:.0f} KB, {signature!r})")
    if not args.keep_docx:
        out.unlink()
        print("removed the intermediate docx (pass --keep-docx to keep it)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
