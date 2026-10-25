"""Read data/experiment.jsonl and print the tables the paper needs.

Paired by task: the two arms see the same candidate pool, so the interesting
statistic is the per-task difference, not the difference of two means.

    python tools/analyse.py
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.evalcov import aggregate, by_repo  # noqa: E402

METRICS = ("recall@1", "recall@5", "recall@10")


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def sign_test(wins: int, losses: int) -> float:
    """Two-sided exact binomial p-value under a fair coin."""
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(wins, losses) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def bootstrap_ci(deltas: list[float], n: int = 2000, alpha: float = 0.05) -> tuple[float, float]:
    if not deltas:
        return (float("nan"), float("nan"))
    rng = random.Random(0)
    means = [
        statistics.fmean(rng.choices(deltas, k=len(deltas)))
        for _ in range(n)
    ]
    means.sort()
    lo = means[int(n * (alpha / 2))]
    hi = means[int(n * (1 - alpha / 2)) - 1]
    return (lo, hi)


def paired(rows: list[dict], metric: str) -> dict:
    deltas = []
    wins = losses = ties = 0
    for row in rows:
        arms = row.get("arms")
        if not arms:
            continue
        delta = arms["graph"][metric] - arms["text"][metric]
        deltas.append(delta)
        if delta > 0:
            wins += 1
        elif delta < 0:
            losses += 1
        else:
            ties += 1
    lo, hi = bootstrap_ci(deltas)
    return {
        "metric": metric,
        "n": len(deltas),
        "text": statistics.fmean(
            [r["arms"]["text"][metric] for r in rows if r.get("arms")] or [0]
        ),
        "graph": statistics.fmean(
            [r["arms"]["graph"][metric] for r in rows if r.get("arms")] or [0]
        ),
        "delta": statistics.fmean(deltas) if deltas else float("nan"),
        "ci95": (round(lo, 4), round(hi, 4)),
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "sign_p": round(sign_test(wins, losses), 4),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "experiment.jsonl"))
    args = ap.parse_args(argv)

    rows = [row for row in load(Path(args.rows)) if "arms" in row or "coverage" in row]
    print(f"rows: {len(rows)}")

    cov = aggregate(rows)
    print("\n== coverage of gold symbols by the rebuilt graph ==")
    print(f"tasks {cov['tasks']}  gold symbols {cov['gold_symbols']}  "
          f"found {cov['found']}  coverage {cov['coverage']:.3f}")
    print("  " + "  ".join(f"{k}={v}" for k, v in cov["counts"].items()))

    scored = [row for row in rows if row.get("arms")]
    print(f"\n== localisation (paired, n={len(scored)}) ==")
    print(f"{'metric':10s} {'text':>7s} {'graph':>7s} {'delta':>7s} {'95% CI':>18s} "
          f"{'W/L/T':>10s} {'sign p':>7s}")
    for metric in METRICS:
        stats = paired(rows, metric)
        print(f"{stats['metric']:10s} {stats['text']:7.3f} {stats['graph']:7.3f} "
              f"{stats['delta']:+7.3f} {str(stats['ci95']):>18s} "
              f"{stats['wins']:3d}/{stats['losses']:3d}/{stats['ties']:3d} "
              f"{stats['sign_p']:7.3f}")

    head = [row["graph_headroom"] for row in scored if "graph_headroom" in row]
    pool = [row["pool_recall"] for row in scored if "pool_recall" in row]
    if head:
        print(f"\nheadroom: {statistics.fmean(head):.3f} of gold targets are one hop "
              f"from a text-derived seed")
    if pool:
        print(f"pool recall (top-60 BM25): {statistics.fmean(pool):.3f}  "
              f"-- the ceiling both arms share")

    unreachable = sum(1 for row in rows if row.get("gold") and not row.get("gold_nodes"))
    if unreachable:
        print(f"tasks whose gold symbols match no graph node: {unreachable}")

    print("\n== per repo ==")
    print(f"{'repo':28s} {'n':>3s} {'cov':>6s} {'r@1 t':>7s} {'r@1 g':>7s} "
          f"{'r@10 t':>7s} {'r@10 g':>7s}")
    for repo, group in sorted(_group(rows).items(), key=lambda kv: -len(kv[1])):
        stats = aggregate(group)
        scored_group = [row for row in group if row.get("arms")]
        def mean_arm(arm, metric):
            values = [row["arms"][arm][metric] for row in scored_group]
            return statistics.fmean(values) if values else float("nan")
        print(f"{repo:28s} {stats['tasks_with_gold']:3d} "
              f"{stats['coverage'] if stats['coverage'] is not None else float('nan'):6.3f} "
              f"{mean_arm('text', 'recall@1'):7.3f} {mean_arm('graph', 'recall@1'):7.3f} "
              f"{mean_arm('text', 'recall@10'):7.3f} {mean_arm('graph', 'recall@10'):7.3f}")
    return 0


def _group(rows: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row.get("repo", "?"), []).append(row)
    return groups


if __name__ == "__main__":
    raise SystemExit(main())
