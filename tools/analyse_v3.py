"""Tables and the figure data for the diffusion pass (`data/experiment_v3.jsonl`).

Everything here is derived from one file, so every number in the paper's
results section can be regenerated with a single command.

    python tools/analyse_v3.py                 # tables on stdout, curves to paper/
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.analyse import paired  # noqa: E402

ARMS = ("text", "graph_rerank", "graph_open", "graph_open2", "graph_fuse",
        "graph_fuse_precise", "graph_ppr", "graph_ppr_text")


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def curve(rows: list[dict], arm: str, k: int) -> float:
    values = []
    for row in rows:
        top = row["arms"][arm]["top"][:k]
        targets = set(row["gold_nodes"])
        values.append(len(set(top) & targets) / len(targets))
    return statistics.fmean(values)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "experiment_v3.jsonl"))
    ap.add_argument("--curves", default=str(ROOT / "paper" / "curves.csv"))
    ap.add_argument("--top", type=int, default=50)
    args = ap.parse_args(argv)

    rows = [row for row in load(Path(args.rows)) if row.get("arms")]
    print(f"scored rows: {len(rows)}")

    print("\n== means (symbol unless marked) ==")
    print(f"{'arm':22s}{'r@1':>7s}{'r@5':>7s}{'r@10':>7s}{'file@5':>8s}"
          f"{'file@10':>8s}{'chars@10':>9s}")
    for arm in ARMS:
        stats = {m: statistics.fmean(row["arms"][arm][m] for row in rows)
                 for m in ("recall@1", "recall@5", "recall@10",
                           "file_recall@5", "file_recall@10", "chars@10")}
        print(f"{arm:22s}{stats['recall@1']:7.3f}{stats['recall@5']:7.3f}"
              f"{stats['recall@10']:7.3f}{stats['file_recall@5']:8.3f}"
              f"{stats['file_recall@10']:8.3f}{stats['chars@10']:9.0f}")

    print("\n== paired against text (per task) ==")
    print(f"{'arm':22s}{'metric':12s}{'delta':>8s}{'95% CI':>20s}{'W/L/T':>12s}{'sign p':>8s}")
    for arm in ARMS[1:]:
        for metric in ("recall@10", "file_recall@10"):
            stats = paired(rows, metric, arm)
            print(f"{arm:22s}{metric:12s}{stats['delta']:+8.3f}"
                  f"{str(stats['ci95']):>20s}"
                  f"{stats['wins']:5d}/{stats['losses']:3d}/{stats['ties']:3d}"
                  f"{stats['sign_p']:8.3f}")

    # --- recall@k curves (figure 1) ---------------------------------------
    out = Path(args.curves)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["k"] + list(ARMS))
        for k in range(1, args.top + 1):
            writer.writerow([k] + [f"{curve(rows, arm, k):.4f}" for arm in ARMS])
    print(f"\ncurves -> {out}")

    # --- conversion -------------------------------------------------------
    scored = [row for row in rows if row.get("ball")]
    sizes = [row["ball"]["size1"] for row in scored]
    two = [row["ball"]["size2"] for row in scored]
    gold1 = [row["ball"]["gold1"] for row in scored]
    gold2 = [row["ball"]["gold2"] for row in scored]
    print("\n== conversion ==")
    print(f"one-hop ball: median {statistics.median(sizes):.0f} nodes, "
          f"mean {statistics.fmean(sizes):.1f}")
    print(f"two-hop ball: median {statistics.median(two):.0f} nodes, "
          f"mean {statistics.fmean(two):.1f}")
    tasks_with_gold = sum(1 for value in gold1 if value)
    symbols = sum(gold1)
    print(f"gold symbols in a one-hop ball: {symbols} over {tasks_with_gold} tasks "
          f"({tasks_with_gold / len(scored):.1%})")
    print(f"that is {symbols / max(sum(sizes), 1):.3%} of the ball members")
    print(f"two-hop-only gold: {sum(gold2)} symbols over {sum(1 for v in gold2 if v)} tasks")

    ranks = [rank for row in scored for rank in row["ball"]["gold1_ppr_rank"]]
    hit = sum(1 for rank in ranks if 0 < rank <= 10)
    print(f"reachable gold in diffusion's top 10: {hit}/{len(ranks)} "
          f"({hit / max(len(ranks), 1):.1%})")
    if ranks:
        print(f"diffusion rank of a reachable gold: median {statistics.median(ranks):.0f}, "
              f"min {min(ranks)}, max {max(ranks)}")

    zero = [row["ball"]["gold1"] == 0 for row in scored]
    print(f"tasks with zero one-hop gold: {sum(zero)}/{len(scored)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
