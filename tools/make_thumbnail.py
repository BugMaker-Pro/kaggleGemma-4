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

    axes.text(0.9, 5.2, "File-level is not symbol-level",
              fontsize=36, fontweight="bold", color="#111111", va="top")
    axes.text(0.9, 4.35, "the same ranking, scored two ways",
              fontsize=22, color="#555555", va="top")

    axes.text(0.9, 2.25, "62.4%", fontsize=88, fontweight="bold",
              color="#9aa7b1", va="baseline")
    axes.text(0.9, 1.70, "of gold files at rank 10", fontsize=19,
              color="#333333")

    axes.text(6.1, 2.25, "27.5%", fontsize=88, fontweight="bold",
              color="#111111", va="baseline")
    axes.text(6.1, 1.70, "of gold symbols at rank 10", fontsize=19,
              color="#333333")

    axes.annotate("", xy=(5.75, 2.05), xytext=(4.75, 2.05),
                  arrowprops=dict(arrowstyle="-|>", lw=2.6, color="#c0392b"))
    axes.text(5.25, 2.55, "2.3×", fontsize=30, color="#c0392b", ha="center")

    out = ROOT / "paper" / "thumbnail.png"
    fig.savefig(out, dpi=100)
    print(f"wrote {out} (1200x630)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
