"""Produce the text that goes into the Kaggle writeup editor.

`paper/main.md` carries scaffolding that must not be submitted: the protocol
header, the claim-evidence table, and the submission checklist. This script
extracts everything a judge should see, renumbers the section headings without
their word budgets, and counts the words of the result — a different number from
the draft's body count, because it is what Kaggle will measure.

    python tools/make_submission.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’.\-]*")
HEADING = re.compile(r"^## (.+?)(?:\s*\(\d+ words\))?$")


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # pragma: no cover
        pass

    source = (ROOT / "paper" / "main.md").read_text(encoding="utf-8")
    body = source.split("## Claim → evidence")[0]

    lines: list[str] = []
    started = False
    for line in body.splitlines():
        if line.startswith("## Title"):
            started = True
        if not started:
            continue
        if line.strip() == "---":
            continue
        match = HEADING.match(line)
        if match:
            title = match.group(1).strip()
            lines.append(f"## {title}")
            continue
        lines.append(line)

    # The image is uploaded through the editor, so the placeholder tells the
    # author where it goes without shipping a dead relative path.
    text = "\n".join(lines)
    text = text.replace(
        "![Figure 1](fig1.png)",
        "⟨upload fig1.png here⟩",
    )
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    text = text.replace("⟨upload fig1.png here⟩", "![Figure 1](fig1.png)")
    # Kaggle takes the title and subtitle in their own fields: emit them as
    # plain lines rather than as a labelled section.
    text = text.replace("## Title\n\n", "")
    text = text.replace("Subtitle: ", "")

    # Markdown joins consecutive lines into one paragraph, so reference entries
    # need their own blocks or the whole bibliography renders as a single run-on.
    head, _, refs = text.partition("## References\n")
    if refs:
        entries = [entry.strip() for entry in refs.splitlines() if entry.strip()]
        text = head + "## References\n\n" + "\n\n".join(entries) + "\n"

    out = ROOT / "paper" / "submission.md"
    out.write_text(text, encoding="utf-8", newline="\n")

    # Kaggle takes the title and subtitle in their own fields, so the body that
    # gets pasted must not start with them. Emitting it separately removes a
    # hand edit from the submission step -- the kind of edit that ships the
    # title twice.
    lines = text.splitlines()
    first = next((i for i, line in enumerate(lines) if line.strip()), 0)
    second = next((i for i in range(first + 1, len(lines)) if lines[i].strip()), None)
    body = "\n".join(lines[second + 1:]).lstrip("\n") if second is not None else text
    body_out = ROOT / "paper" / "submission_body.md"
    body_out.write_text(body, encoding="utf-8", newline="\n")

    words = len(WORD.findall(text))
    print(f"wrote {out}")
    print(f"wrote {body_out}   (title and subtitle removed: paste this one)")
    print(f"words as Kaggle will count them: {words}  (limit 3000)")
    print(f"headroom: {3000 - words}")
    print(f"body words: {len(WORD.findall(body))}")
    for line in text.splitlines():
        if line.startswith("## "):
            print(f"  {line}")
    return 0 if words <= 3000 else 1


if __name__ == "__main__":
    raise SystemExit(main())
