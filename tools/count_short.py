"""Count the short writeup with the same regex Kaggle's counter approximates."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’.\-]*")
text = (ROOT / "paper" / "kaggle_body.md").read_text(encoding="utf-8")
words = WORD.findall(text)
tables = sum(1 for line in text.splitlines() if line.lstrip().startswith("|"))
headings = sum(1 for line in text.splitlines() if line.startswith("## "))
images = text.count("![")
print(f"words {len(words)}  headings {headings}  tables {tables}  images {images}")
