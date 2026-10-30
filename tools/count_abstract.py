"""Count the abstract with the same regex the submission counter uses."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’.\-]*")
text = (ROOT / "paper" / "main.md").read_text(encoding="utf-8")
abstract = text.split("## Abstract")[1].split("## 1.")[0]
print("abstract words:", len(WORD.findall(abstract)))
