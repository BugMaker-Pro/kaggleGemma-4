"""Figure 1 in a 4:3 box: two panels stacked, tight margins, 4.0 x 3.0 in.

The portrait build (0.79 aspect) is legible but some renderers refuse very tall
images. 4:3 is the safest aspect a writeup can use, so this variant trades a
little breathing room for a shape that cannot be cropped into emptiness.

    python tools/make_figure_43.py     # -> paper/fig1_43.png
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

STYLE = {
    "text": dict(color="#1a1a1a", lw=1.8, ls="-", label="text (BM25)"),
    "graph_rerank": dict(color="#1f6fb4", lw=1.5, ls="-", label="graph_rerank"),
    "graph_open": dict(color="#c0392b", lw=1.3, ls="--", label="graph_open, 1 hop"),
    "graph_ppr": dict(color="#2e8b57", lw=1.3, ls=":", label="graph_ppr"),
}


def read_curves(path: Path) -> dict[str, list[float]]:
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    curves: dict[str, list[float]] = {}
    for row in rows:
        for key, value in row.items():
            if key == "k":
                continue
            curves.setdefault(key, []).append(float(value))
    return curves


def main() -> int:
    curves = read_curves(ROOT / "paper" / "curves.csv")
    ks = list(range(1, len(next(iter(curves.values()))) + 1))

    plt.rcParams.update({
        "font.size": 8,
        "font.family": "DejaVu Sans",
        "axes.linewidth": 0.6,
        "xtick.major.width": 0.5,
        "ytick.major.width": 0.5,
    })
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(4.8, 3.6))

    for arm, style in STYLE.items():
        top.plot(ks, curves[arm], **style)
        top.plot([10], [curves[arm][9]], marker="o", ms=2.6, color=style["color"])
    top.axvline(10, color="#888888", lw=0.7, ls=(0, (2, 2)))
    top.annotate("budget = 10", xy=(11, 0.105), fontsize=7, color="#555555")
    top.set_xlabel("shortlist slots $k$", fontsize=7.5, labelpad=1)
    top.set_ylabel("symbol recall@$k$", fontsize=7.5)
    top.set_xlim(1, 50)
    top.set_ylim(0.08, 0.50)
    top.tick_params(labelsize=7)
    top.set_title("four arms, one pool, one budget", fontsize=8, pad=3)
    top.legend(frameon=False, fontsize=6.8, loc="lower right", handlelength=1.8,
               borderaxespad=0.1)

    groups = ("recall@5", "recall@10")
    symbol = (0.2135, 0.2750)
    files = (0.5483, 0.6241)
    positions = list(range(len(groups)))
    width = 0.34
    bottom.bar([p - width / 2 for p in positions], symbol, width,
               color="#1a1a1a", label="symbol")
    bottom.bar([p + width / 2 for p in positions], files, width,
               color="#9aa7b1", label="file")
    for idx, (s, f) in enumerate(zip(symbol, files)):
        bottom.text(idx - width / 2, s + 0.02, f"{s:.3f}", ha="center", fontsize=7)
        bottom.text(idx + width / 2, f + 0.02, f"{f:.3f}", ha="center", fontsize=7)
    bottom.set_xticks(positions)
    bottom.set_xticklabels(groups, fontsize=7.5)
    bottom.set_ylim(0, 0.82)
    bottom.set_ylabel("recall", fontsize=7.5)
    bottom.tick_params(labelsize=7)
    bottom.set_title("one ranking, two granularities", fontsize=8, pad=3)
    bottom.legend(frameon=False, fontsize=6.8, loc="upper left", borderaxespad=0.1)
    bottom.annotate("2.3×", xy=(1, 0.44), fontsize=9, color="#c0392b", ha="center")

    for axes in (top, bottom):
        axes.spines["top"].set_visible(False)
        axes.spines["right"].set_visible(False)
        axes.grid(axis="y", lw=0.4, color="#dddddd")
        axes.set_axisbelow(True)

    fig.tight_layout(pad=0.35)
    out = ROOT / "paper" / "fig1_43.png"
    fig.savefig(out, dpi=240)
    print(f"wrote {out} ({4.8 * 240:.0f}x{3.6 * 240:.0f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
