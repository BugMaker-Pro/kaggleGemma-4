"""Read the bibliographic facts we are willing to print, from the PDFs themselves.

A reference list assembled from memory is an invitation to invent a title, so the
title, first author and first-page header of every cited paper are extracted from
the file in `docs/papers/` and printed for a human to paste into the paper.

    python tools/pdfmeta.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CITED = {
    "SWE-bench.pdf": "SWE-bench",
    "LocAgent.pdf": "LocAgent",
    "ARISE.pdf": "ARISE",
    "PyCG_callgraph_python.pdf": "PyCG",
    "SWE-agent_ACI.pdf": "SWE-agent",
    "CodexGraph.pdf": "CodexGraph",
    "Jarvis_callgraph_python.pdf": "Jarvis",
    "RepoAtlas.pdf": "RepoAtlas",
}


def first_lines(path: Path, count: int = 12) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    meta = reader.metadata or {}
    text = reader.pages[0].extract_text() or ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [f"  meta title: {meta.get('/Title')!r}",
            f"  meta author: {meta.get('/Author')!r}"] + lines[:count]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # pragma: no cover - older interpreters
        pass
    for name, label in CITED.items():
        path = ROOT / "docs" / "papers" / name
        print(f"=== {label}  ({name})")
        if not path.exists():
            print("  MISSING")
            continue
        for line in first_lines(path):
            print(f"  {line.strip()[:160]}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
