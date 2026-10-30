"""Write the full writeup body with the tables as images.

`paper/kaggle_body_full.md` chains the numbers as bullets, which a reader has to
decode; `paper/kaggle_body_img.md` puts the typeset table where the table was.
Each table image already carries its caption, so the caption line is dropped from
the text: the same words reach the reader, they just arrive as pixels.

    python tools/make_kaggle_images.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’.\-]*")
CAPTION = re.compile(r"^\*Table \d+ — ")
NUMBER = re.compile(r"[+\u2212-]?\d+(?:\.\d+)?")


def main() -> int:
    lines = (ROOT / "paper" / "submission_body.md").read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    missing: list[str] = []
    index = 0
    ordinal = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("|"):
            out.append(lines[index])
            index += 1
            continue
        ordinal += 1
        caption = ""
        for back in range(len(out) - 1, -1, -1):
            if out[back].strip():
                caption = out[back].strip().strip("*").strip()
                break
        match = re.match(r"^Table (\d+)", caption)
        label = match.group(1) if match else "resolution"
        if match:
            # the image carries the caption already
            for back in range(len(out) - 1, -1, -1):
                if out[back].strip():
                    out[back] = ""
                    break
        rows: list[list[str]] = []
        index += 2
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            rows.append(lines[index])
            index += 1
        image = ROOT / "paper" / f"table_{label}.png"
        if not image.exists():
            missing.append(image.name)
        # the alt text doubles as the upload instruction: a pasted writeup shows
        # a broken-image placeholder whose caption names the file to upload
        out.append(f"![paper/table_{label}.png](table_{label}.png)")
        out.append("")

    body = "\n".join(out)
    body = body.replace("![Figure 1](fig1.png)", "![paper/fig1.png](fig1.png)")
    body = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n"
    path = ROOT / "paper" / "kaggle_body_img.md"
    path.write_text(body, encoding="utf-8", newline="\n")
    words = len(WORD.findall(body))
    images = body.count("![")
    print(f"wrote {path}  tables {ordinal} images {images} words {words} (limit 3000)")
    if missing:
        print("missing table images:", missing)
        return 1
    return 0 if words <= 3000 else 1


if __name__ == "__main__":
    raise SystemExit(main())
