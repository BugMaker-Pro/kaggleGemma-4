"""The writeup card image: one number, readable at 300 px wide.

Kaggle shows this at roughly 300-400 px, so the type has to survive a 3x
downscale: two numbers, one comparison, nothing else.

    python tools/make_thumbnail.py     # -> paper/thumbnail.png (1200x630)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def main() -> int:
    plt.rcParams.update({"font.family": "DejaVu Sans"})
    fig = plt.figure(figsize=(12, 6.3), facecolor="white")
    axes = fig.add_axes([0, 0, 1, 1])
    axes.set_xlim(0, 12)
    axes.set_ylim(0, 6.3)
    axes.axis("off")

    axes.text(0.7, 5.35, "File-level is not symbol-level",
              fontsize=34, fontweight="bold", color="#111111", va="top")
    axes.text(0.7, 4.45, "the same ranking, scored two ways",
              fontsize=21, color="#555555", va="top")

    axes.text(0.7, 3.05, "62.4%", fontsize=64, fontweight="bold",
              color="#9aa7b1", va="baseline")
    axes.text(0.7, 2.35, "of gold files at rank 10", fontsize=17, color="#333333")

    axes.text(5.35, 3.05, "27.5%", fontsize=64, fontweight="bold",
              color="#111111", va="baseline")
    axes.text(5.35, 2.35, "of gold symbols at rank 10", fontsize=17, color="#333333")

    axes.annotate("", xy=(5.05, 2.86), xytext=(4.15, 2.86),
                  arrowprops=dict(arrowstyle="-|>", lw=2.2, color="#c0392b"))
    axes.text(4.6, 3.28, "2.3×", fontsize=25, color="#c0392b", ha="center")

    axes.text(0.7, 1.35,
              "300 SWE-bench Lite tasks · 354 gold symbols · 8 graph arms · equal budget",
              fontsize=15, color="#666666")
    axes.text(0.7, 0.75,
              "no graph arm improves symbol recall; a file-level lexical vote adds 3 points",
              fontsize=15, color="#666666")

    axes.plot([0.7, 11.3], [1.12, 1.12], color="#e0e0e0", lw=1.2)

    out = ROOT / "paper" / "thumbnail.png"
    fig.savefig(out, dpi=100)
    print(f"wrote {out} (1200x630)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
