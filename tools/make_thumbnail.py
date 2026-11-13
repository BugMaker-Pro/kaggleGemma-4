"""The writeup card image: one number, readable at 300 px wide.

Kaggle shows this at roughly 300-400 px, so the type has to survive a 3x
downscale: two numbers, one comparison, nothing else. Both bars are drawn on
the same scale (10 axis units = 100%), so the 2.3x ratio stays visible even
when the small type does not.

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

FILES = 62.4
SYMBOLS = 27.5
BAR_SCALE = 11.4  # axis units spanned by a 100% bar
BAR_HEIGHT = 0.36


def _bar(axes, top: float, pct: float, color: str) -> None:
    axes.add_patch(
        plt.Rectangle(
            (0.7, top - BAR_HEIGHT), pct / 100.0 * BAR_SCALE, BAR_HEIGHT,
            facecolor=color, edgecolor="none",
        )
    )


def main() -> int:
    plt.rcParams.update({"font.family": "DejaVu Sans"})
    fig = plt.figure(figsize=(12, 6.3), facecolor="white")
    axes = fig.add_axes([0, 0, 1, 1])
    axes.set_xlim(0, 12)
    axes.set_ylim(0, 6.3)
    axes.axis("off")

    axes.text(0.7, 5.58, "File-level is not symbol-level",
              fontsize=40, fontweight="bold", color="#10151a", va="baseline")
    axes.text(0.7, 5.18, "the same top-10 shortlist, scored two ways",
              fontsize=21, color="#5b6673", va="baseline")

    axes.text(0.7, 4.20, f"{FILES}%", fontsize=68, fontweight="bold",
              color="#5a6672", va="baseline")
    _bar(axes, 3.94, FILES, "#c2cdd6")
    axes.text(0.7, 3.28, "of gold files at rank 10", fontsize=21,
              color="#333333", va="baseline")

    axes.text(0.7, 2.24, f"{SYMBOLS}%", fontsize=68, fontweight="bold",
              color="#c0392b", va="baseline")
    _bar(axes, 1.98, SYMBOLS, "#c0392b")
    axes.text(0.7, 1.32, "of gold symbols at rank 10", fontsize=21,
              color="#333333", va="baseline")
    axes.text(4.05, 1.81, "2.3\u00d7 fewer", fontsize=27, fontweight="bold",
              color="#c0392b", va="center")

    axes.text(0.7, 0.48, "290 SWE-bench Lite tasks  \u00b7  BM25  \u00b7  top-10",
              fontsize=18, color="#8a949e", va="baseline")

    out = ROOT / "paper" / "thumbnail.png"
    fig.savefig(out, dpi=100)
    print(f"wrote {out} (1200x630)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
