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


def load_rows(path: Path) -> dict[str, dict]:
    return {row["instance_id"]: row for row in
            (json.loads(line) for line in path.open(encoding="utf-8") if line.strip())}


def bucket(task: dict) -> str:
    """What the issue offers, from the features file alone (both scales agree).

    quotes  the gold symbol's body contains a line the issue pastes
    names   the issue names a file or prints a traceback frame
    neither no source in the issue at all
    """
    rows, labels = task["rows"], task["labels"]
    for index, label in enumerate(labels):
        if label and rows[index][3]:
            return "quotes"
    for index, label in enumerate(labels):
        if label and (rows[index][4] or rows[index][6] or rows[index][8]):
            return "names"
    return "neither"


def split_numbers(rows_path: Path, results_path: Path) -> dict[str, tuple[int, float]]:
    tasks = load_rows(rows_path)
    results = load_rows(results_path)
    groups: dict[str, list[str]] = {}
    for instance_id, task in tasks.items():
        if instance_id in results and task.get("labels"):
            groups.setdefault(bucket(task), []).append(instance_id)
    out = {}
    for name, ids in groups.items():
        gain = sum(results[i]["ltr"] - results[i]["bm25"] for i in ids) / len(ids)
        out[name] = (len(ids), gain)
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

    # right: where the ranker's gain lives, at both scales
    lite = split_numbers(ROOT / "data" / "features.jsonl", ROOT / "data" / "combo_ltr.jsonl")
    full = split_numbers(ROOT / "data" / "features_full.jsonl",
                         ROOT / "data" / "combo_ltr_full.jsonl")
    names = ("quotes", "names", "neither")
    xs = [0, 1, 2]
    lite_gain = [lite[name][1] for name in names]
    full_gain = [full[name][1] for name in names]
    right.bar([x - 0.19 for x in xs], lite_gain, 0.36, color="#c9ccd1", label="290 tasks")
    right.bar([x + 0.19 for x in xs], full_gain, 0.36, color="#c0392b", label="2,232 tasks")
    for x, value in zip(xs, lite_gain):
        right.text(x - 0.19, value + 0.010, f"{value * 100:+.0f}", ha="center", fontsize=5.6)
    for x, value in zip(xs, full_gain):
        right.text(x + 0.19, value + 0.010, f"{value * 100:+.0f}", ha="center", fontsize=5.6)
    right.set_xticks(xs)
    right.set_xticklabels([f"{name}\n{lite[name][0]} · {full[name][0]}" for name in names],
                          fontsize=5.6)
    right.set_ylim(-0.03, 0.52)
    right.set_ylabel("ranker gain, points", fontsize=6.8)
    right.tick_params(labelsize=6.2)
    right.axhline(0, color="#888888", lw=0.5)
    right.set_title("gain by what the issue offers", fontsize=7.2, pad=3)
    right.legend(frameon=False, fontsize=5.5, loc="upper center", ncol=2,
                 handlelength=1.2, columnspacing=1.0, borderaxespad=0.0)

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
