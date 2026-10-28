"""Figure 1 for the v13 paper: the ladder, the granularity gap, and the split.

Top: symbol recall@k for BM25, the best graph arm, the learned ranker, and the
ranker with evidence overrides — one pool, one budget. Bottom left: the same
ranking scored by file and by symbol. Bottom right: the arm split by what the
issue offers.

    python tools/make_figure_v2.py     # -> paper/fig1.png (4:3)
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

KS = tuple(range(1, 21))
COLORS = {"bm25": "#1a1a1a", "graph_rerank": "#1f6fb4",
          "ltr": "#e08a1e", "ltr_ev5": "#c0392b"}
LABELS = {"bm25": "BM25", "graph_rerank": "best graph arm",
          "ltr": "learned ranker", "ltr_ev5": "ranker + evidence"}


def load_orders() -> dict[str, dict]:
    rows = [json.loads(line) for line in
            (ROOT / "data" / "combo_ltr_orders.jsonl").open(encoding="utf-8") if line.strip()]
    return {row["instance_id"]: row for row in rows}


def curve(orders: dict[str, dict], arm: str) -> list[float]:
    values = []
    for k in KS:
        total = 0.0
        for row in orders.values():
            if not row["gold_total"]:
                continue
            order = row["orders"][arm]
            total += sum(1 for index in order[:k] if row["labels"][index]) / row["gold_total"]
        values.append(total / len(orders))
    return values


def graph_curve(path: Path) -> dict[str, list[float]]:
    curves: dict[str, list[float]] = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            for key, value in row.items():
                if key != "k":
                    curves.setdefault(key, []).append(float(value))
    return curves


def split_numbers() -> list[tuple[str, int, float, float]]:
    results = {row["instance_id"]: row for row in
               (json.loads(line) for line in (ROOT / "data" / "combo_ltr.jsonl").open(encoding="utf-8") if line.strip())}
    quoted = {row["instance_id"]: row for row in
              (json.loads(line) for line in (ROOT / "data" / "body_evidence.jsonl").open(encoding="utf-8") if line.strip())}
    named = {row["instance_id"]: row for row in
             (json.loads(line) for line in (ROOT / "data" / "issue_evidence.jsonl").open(encoding="utf-8") if line.strip())}

    def bucket(instance_id: str) -> str:
        if quoted.get(instance_id, {}).get("line_quote"):
            return "quotes code"
        info = named.get(instance_id, {})
        if info.get("paths") or info.get("frames"):
            return "names only"
        return "no signal"

    groups: dict[str, list[str]] = {}
    for instance_id in results:
        groups.setdefault(bucket(instance_id), []).append(instance_id)
    out = []
    for name in ("quotes code", "names only", "no signal"):
        ids = groups.get(name, [])
        base = sum(results[i]["bm25"] for i in ids) / len(ids)
        arm = sum(results[i]["ltr_ev5"] for i in ids) / len(ids)
        out.append((name, len(ids), base, arm))
    return out


def main() -> int:
    orders = load_orders()
    plt.rcParams.update({"font.size": 7, "font.family": "DejaVu Sans",
                         "axes.linewidth": 0.6, "xtick.major.width": 0.5,
                         "ytick.major.width": 0.5})
    fig = plt.figure(figsize=(4.8, 3.6))
    grid = fig.add_gridspec(2, 2, height_ratios=(1.35, 1.0), hspace=0.55, wspace=0.34)
    top = fig.add_subplot(grid[0, :])
    left = fig.add_subplot(grid[1, 0])
    right = fig.add_subplot(grid[1, 1])

    curves = graph_curve(ROOT / "paper" / "curves.csv")
    for arm in ("bm25", "ltr", "ltr_ev5"):
        values = curve(orders, arm)
        top.plot(KS, values, color=COLORS[arm], lw=1.7 if arm != "bm25" else 1.4,
                 label=LABELS[arm], zorder=3 if arm == "ltr_ev5" else 2)
        top.plot([10], [values[9]], "o", ms=2.8, color=COLORS[arm])
    top.plot(range(1, len(curves["graph_rerank"]) + 1)[:20], curves["graph_rerank"][:20],
             color=COLORS["graph_rerank"], lw=1.1, ls=(0, (4, 2)),
             label=LABELS["graph_rerank"])
    top.axvline(10, color="#888888", lw=0.7, ls=(0, (2, 2)))
    top.annotate("budget = 10", xy=(10.6, 0.115), fontsize=6.5, color="#555555")
    top.annotate("0.361", xy=(10.8, 0.368), fontsize=6.4, color=COLORS["ltr_ev5"])
    top.annotate("0.332", xy=(12.8, 0.322), fontsize=6.4, color=COLORS["ltr"])
    top.annotate("0.275", xy=(10.8, 0.248), fontsize=6.4, color=COLORS["bm25"])
    top.set_xlabel("shortlist slots $k$", fontsize=7, labelpad=1)
    top.set_ylabel("symbol recall@$k$", fontsize=7)
    top.set_xlim(1, 20)
    top.set_ylim(0.05, 0.42)
    top.tick_params(labelsize=6.5)
    top.set_title("one pool, one budget: what the ranking buys", fontsize=7.5, pad=3)
    top.legend(frameon=False, fontsize=6.2, loc="lower right", handlelength=1.6,
               borderaxespad=0.1, labelspacing=0.25)

    # left: the granularity gap
    groups = ("recall@5", "recall@10")
    symbol, files = (0.2135, 0.2750), (0.5483, 0.6241)
    positions = [0, 1]
    width = 0.34
    left.bar([p - width / 2 for p in positions], symbol, width, color="#1a1a1a", label="symbol")
    left.bar([p + width / 2 for p in positions], files, width, color="#9aa7b1", label="file")
    for idx, (s, f) in enumerate(zip(symbol, files)):
        left.text(idx - width / 2, s + 0.02, f"{s:.2f}", ha="center", fontsize=6.2)
        left.text(idx + width / 2, f + 0.02, f"{f:.2f}", ha="center", fontsize=6.2)
    left.set_xticks(positions)
    left.set_xticklabels(groups, fontsize=6.5)
    left.set_ylim(0, 0.85)
    left.set_ylabel("recall", fontsize=6.8)
    left.tick_params(labelsize=6.2)
    left.set_title("one ranking, two granularities", fontsize=7.2, pad=3)
    left.legend(frameon=False, fontsize=6, loc="upper left", borderaxespad=0.1)
    left.annotate("2.3×", xy=(0.5, 0.40), fontsize=7.5, color="#c0392b", ha="center")

    # right: where the gain lives
    rows = split_numbers()
    xs = [0, 1, 2]
    base = [row[2] for row in rows]
    arm = [row[3] for row in rows]
    right.bar([x - 0.19 for x in xs], base, 0.36, color="#c9ccd1", label="BM25")
    right.bar([x + 0.19 for x in xs], arm, 0.36, color="#c0392b", label="ranker + evidence")
    for x, value in zip(xs, arm):
        right.text(x + 0.19, value + 0.02, f"{value:.2f}", ha="center", fontsize=6.2)
    right.set_xticks(xs)
    right.set_xticklabels([name.replace(" ", "\n") + f"\n(n={count})"
                           for name, count, _, _ in rows], fontsize=5.6)
    right.set_ylim(0, 0.88)
    right.set_ylabel("recall@10", fontsize=6.8)
    right.tick_params(labelsize=6.2)
    right.set_title("split by what the issue offers", fontsize=7.2, pad=3)
    right.legend(frameon=False, fontsize=5.8, loc="upper right", borderaxespad=0.1)

    for axes in (top, left, right):
        axes.spines["top"].set_visible(False)
        axes.spines["right"].set_visible(False)
        axes.grid(axis="y", lw=0.35, color="#dddddd")
        axes.set_axisbelow(True)

    fig.tight_layout(pad=0.3)
    out = ROOT / "paper" / "fig1.png"
    fig.savefig(out, dpi=240)
    print(f"wrote {out} ({4.8 * 240:.0f}x{3.6 * 240:.0f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
