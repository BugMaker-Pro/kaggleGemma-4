"""Figure 1: the same ranking scored at two granularities, and four arms over k.

Left panel answers "do the arms separate?" -- they do not, until the budget is
well past the ten slots the paper experiments with. Right panel answers "how
much of the gap is the granularity?" with one ranking scored two ways.

    python tools/make_figure.py        # -> paper/fig1.png
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
    "text": dict(color="#1a1a1a", lw=1.6, ls="-", label="text (BM25)"),
    "graph_rerank": dict(color="#1f6fb4", lw=1.4, ls="-", label="graph_rerank"),
    "graph_open": dict(color="#c0392b", lw=1.2, ls="--", label="graph_open, 1 hop"),
    "graph_ppr": dict(color="#2e8b57", lw=1.2, ls=":", label="graph_ppr"),
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
        "font.size": 7.5,
        "font.family": "DejaVu Sans",
        "axes.linewidth": 0.6,
        "xtick.major.width": 0.5,
        "ytick.major.width": 0.5,
    })
    fig, (left, right) = plt.subplots(
        1, 2, figsize=(7.0, 2.45), gridspec_kw={"width_ratios": (1.45, 1.0)}
    )

    for arm, style in STYLE.items():
        left.plot(ks, curves[arm], **style)
        left.plot([10], [curves[arm][9]], marker="o", ms=2.6, color=style["color"])
    left.axvline(10, color="#888888", lw=0.7, ls=(0, (2, 2)))
    left.annotate("budget = 10 slots", xy=(10, 0.115), xytext=(11.5, 0.115),
                  fontsize=6.5, color="#555555", va="bottom")
    left.set_xlabel("shortlist slots $k$")
    left.set_ylabel("symbol recall@$k$")
    left.set_xlim(1, 50)
    left.set_ylim(0.08, 0.50)
    left.set_title("four arms, one candidate pool, one budget", fontsize=7.5, pad=4)
    left.legend(frameon=False, fontsize=6.5, loc="lower right", handlelength=1.8)

    groups = ("recall@5", "recall@10")
    symbol = (0.2135, 0.2750)
    files = (0.5483, 0.6241)
    positions = range(len(groups))
    width = 0.34
    right.bar([p - width / 2 for p in positions], symbol, width,
              color="#1a1a1a", label="symbol")
    right.bar([p + width / 2 for p in positions], files, width,
              color="#9aa7b1", label="file")
    for idx, (s, f) in enumerate(zip(symbol, files)):
        right.text(idx - width / 2, s + 0.015, f"{s:.3f}", ha="center", fontsize=6.5)
        right.text(idx + width / 2, f + 0.015, f"{f:.3f}", ha="center", fontsize=6.5)
    right.set_xticks(list(positions))
    right.set_xticklabels(groups)
    right.set_ylim(0, 0.78)
    right.set_ylabel("recall")
    right.set_title("one ranking, two granularities", fontsize=7.5, pad=4)
    right.legend(frameon=False, fontsize=6.5, loc="upper left")
    right.annotate("2.3× at $k=10$", xy=(1, 0.70), fontsize=7, color="#c0392b",
                   ha="center")

    for axes in (left, right):
        axes.spines["top"].set_visible(False)
        axes.spines["right"].set_visible(False)
        axes.grid(axis="y", lw=0.4, color="#dddddd")
        axes.set_axisbelow(True)

    fig.tight_layout(pad=0.4)
    out = ROOT / "paper" / "fig1.png"
    fig.savefig(out, dpi=300)
    fig.savefig(out.with_suffix(".pdf"))
    print(f"wrote {out} and {out.with_suffix('.pdf')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
