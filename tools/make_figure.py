"""Figure 1: the same ranking scored at two granularities, and four arms over k.

Sized for a 730 px column: 4.4 in wide at 220 dpi is ~970 px, so the figure is
displayed at roughly 0.75 scale and the 9 pt labels land near 7 pt — readable.
The panels are stacked rather than side by side because a two-up layout at
column width squeezes each panel to ~360 px and the labels to 2.5 pt.

    python tools/make_figure.py
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
    "text": dict(color="#1a1a1a", lw=2.0, ls="-", label="text (BM25)"),
    "graph_rerank": dict(color="#1f6fb4", lw=1.7, ls="-", label="graph_rerank"),
    "graph_open": dict(color="#c0392b", lw=1.5, ls="--", label="graph_open, 1 hop"),
    "graph_ppr": dict(color="#2e8b57", lw=1.5, ls=":", label="graph_ppr"),
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
        "font.size": 9,
        "font.family": "DejaVu Sans",
        "axes.linewidth": 0.7,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
    })
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(4.4, 5.6))

    for arm, style in STYLE.items():
        top.plot(ks, curves[arm], **style)
        top.plot([10], [curves[arm][9]], marker="o", ms=3.2, color=style["color"])
    top.axvline(10, color="#888888", lw=0.8, ls=(0, (2, 2)))
    top.annotate("budget = 10 slots", xy=(10.8, 0.10), fontsize=8, color="#555555")
    top.set_xlabel("shortlist slots $k$")
    top.set_ylabel("symbol recall@$k$")
    top.set_xlim(1, 50)
    top.set_ylim(0.08, 0.50)
    top.set_title("four arms, one candidate pool, one budget", fontsize=9, pad=5)
    top.legend(frameon=False, fontsize=8, loc="lower right", handlelength=2.0)

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
        bottom.text(idx - width / 2, s + 0.02, f"{s:.3f}", ha="center", fontsize=8.5)
        bottom.text(idx + width / 2, f + 0.02, f"{f:.3f}", ha="center", fontsize=8.5)
    bottom.set_xticks(positions)
    bottom.set_xticklabels(groups, fontsize=9)
    bottom.set_ylim(0, 0.80)
    bottom.set_ylabel("recall")
    bottom.set_title("one ranking, two granularities", fontsize=9, pad=5)
    bottom.legend(frameon=False, fontsize=8, loc="upper left")
    bottom.annotate("2.3×", xy=(1, 0.42), fontsize=11, color="#c0392b", ha="center")

    for axes in (top, bottom):
        axes.spines["top"].set_visible(False)
        axes.spines["right"].set_visible(False)
        axes.grid(axis="y", lw=0.5, color="#dddddd")
        axes.set_axisbelow(True)

    fig.tight_layout(pad=0.5)
    out = ROOT / "paper" / "fig1.png"
    fig.savefig(out, dpi=220)
    fig.savefig(out.with_suffix(".pdf"))
    print(f"wrote {out} at {fig.get_size_inches()[0] * 220:.0f} px wide")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
