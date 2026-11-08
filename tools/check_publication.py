"""Check submission sources, generated PDF text, and publication structure.

Run after generating the PDF and both writeup variants. Numeric correctness is
checked separately by audit_numbers.py; this check targets publication drift.
"""
from __future__ import annotations

import re
import json
import subprocess
import sys
import unicodedata
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’.\-]*")


def plain(text: str) -> str:
    text = re.sub(r"!\[[^]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    return text.replace("*", "").replace("`", "")


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", "", text).replace("\u00ad", "")


def main() -> int:
    problems = []
    result = subprocess.run([sys.executable, str(ROOT / "tools/make_submission.py"), "--check"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        problems.append(result.stdout.strip() or result.stderr.strip())
    submission = (ROOT / "paper/submission.md").read_text(encoding="utf-8")
    body = (ROOT / "paper/submission_body.md").read_text(encoding="utf-8")
    words = len(WORD.findall(submission))
    if words > 3000:
        problems.append(f"Submission exceeds 3000 words: {words}")
    references = re.findall(r"^\[(\d+)\]", body, flags=re.M)
    cited = set(re.findall(r"\[(\d+)\]", body.split("## References")[0]))
    if cited != set(references) or references != [str(i) for i in range(1, len(references)+1)]:
        problems.append("References are missing, unused, duplicated, or not consecutive")
    tables = re.findall(r"^\*Table (\d+)", body, flags=re.M)
    if tables != [str(i) for i in range(1, len(tables)+1)]:
        problems.append(f"Table numbering is not consecutive: {tables}")
    for heading in ["## Abstract", "## 1. Introduction", "## 2. Related Work", "## 3. Setup",
                    "## 4. Method", "## 5. Results", "## 7. Limitations", "## References"]:
        if heading not in body:
            problems.append(f"Required heading absent: {heading}")
    for phrase in ["6?10", "with ? =", "equal character budget", "Eight ways of adding a code graph",
                   "the graph is not", "gap is invariant", "assertion check"]:
        if phrase in body:
            problems.append(f"Stale claim: {phrase}")
    control_summary = ROOT / "data/graph_controls_summary.json"
    if control_summary.exists() and "Primary experiment: topology versus intervention" in body:
        controls = json.loads(control_summary.read_text(encoding="utf-8"))["full"]
        for representation in ("metadata", "body", "dense"):
            values = [f"{controls['arms'][representation][arm]['symbol']:.4f}"
                      for arm in ("base", "real", "file", "rewired", "rewired_pair")]
            values.append(f"{controls['primary'][representation+':real-rewired']['holm_p']:.4f}")
            expected_row = "| " + representation + " | " + " | ".join(values) + " |"
            if expected_row not in body:
                problems.append(f"Topology-control Table 1 differs from audited summary: {representation}")
        for representation in ("body", "dense"):
            p_value = controls['primary'][f'interaction:{representation}-metadata']['holm_p']
            if f"{p_value:.3f}" not in body:
                problems.append(f"Topology interaction p-value missing: {representation}")
    ablation_summary = ROOT / "experiments/runs/dense-graph-ablation-20261108-v1/summary.json"
    if ablation_summary.exists() and "fusion without topology features" in body:
        ablation = json.loads(ablation_summary.read_text(encoding="utf-8"))
        reduced = ablation["arms"]["without_graph"]
        expected = (f"| fusion without topology features | — | — | "
                    f"{reduced['symbol']:.3f} | {reduced['file']:.3f} |")
        if expected not in body:
            problems.append("Strong-fusion ablation row differs from audited result")
        effect = ablation["symbol"]
        for value in (f"{100*effect['delta']:.2f}", f"{effect['repository_signflip_p']:.4f}",
                      f"{100*effect['cluster_ci95'][0]:.2f}", f"{100*effect['cluster_ci95'][1]:.2f}"):
            if value not in body:
                problems.append(f"Strong-fusion ablation statistic missing: {value}")
    reader = PdfReader(ROOT / "paper/submission.pdf")
    pages = []
    for page_number, page in enumerate(reader.pages, 1):
        lines = (page.extract_text() or "").splitlines()
        pages.append("\n".join(line for line in lines if line.strip() != str(page_number)))
    pdf_text = normalized("\n".join(pages))
    checked = 0
    # Paragraphs and captions must agree, even if they span page boundaries.
    for block in re.split(r"\n\s*\n", submission):
        if block.lstrip().startswith(("|", "![")):
            continue
        expected = normalized(plain(block))
        if expected and expected not in pdf_text:
            problems.append(f"PDF differs from source: {plain(block)[:110]}")
        checked += bool(expected)
    # Every non-delimiter table row must appear in its printed row order.
    from tools.make_kaggle_full import cells
    for line in body.splitlines():
        if not line.startswith("|") or set(line.replace("|", "").replace(":", "").strip()) <= {"-", " "}:
            continue
        row = normalized(" ".join(plain(cell) for cell in cells(line)))
        if row not in pdf_text:
            problems.append(f"PDF table differs from source: {line[:110]}")
    image_body = (ROOT / "paper/kaggle_body_img.md").read_text(encoding="utf-8")
    for image in re.findall(r"!\[[^]]*\]\(([^)]+)\)", image_body):
        if not (ROOT / "paper" / image).is_file():
            problems.append(f"Missing writeup image: {image}")
    print(f"{words} words; {len(reader.pages)} PDF pages; {len(tables)} numbered tables; "
          f"{len(references)} references; {checked} source blocks checked against PDF")
    for problem in problems:
        print(f"FAIL: {problem}")
    print(f"{len(problems)} publication failure(s)")
    return bool(problems)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
