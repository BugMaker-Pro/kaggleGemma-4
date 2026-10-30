"""Dump the pipe tables of the submission body, for authoring list equivalents."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
lines = (ROOT / "paper" / "submission_body.md").read_text(encoding="utf-8").splitlines()
index = 0
number = 0
while index < len(lines):
    if lines[index].lstrip().startswith("|"):
        number += 1
        caption = ""
        for back in range(index - 1, -1, -1):
            if lines[back].strip():
                caption = lines[back][:80]
                break
        print(f"--- table {number}: {caption}")
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            print("   ", lines[index])
            index += 1
        print()
    else:
        index += 1
