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
FILE_METRICS = ("file_recall@5", "file_recall@10")
TREATMENTS = ("graph_rerank", "graph_open", "graph_fuse", "graph_fuse_precise")


def treatment_of(row: dict, arm: str) -> dict | None:
    """Arm lookup with a shim for files written before the arms were split."""
    arms = row.get("arms")
    if not arms:
        return None
    if arm in arms:
        return arms[arm]
    if arm == "graph_rerank" and "graph" in arms:
        return arms["graph"]
    return None


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


def paired(rows: list[dict], metric: str, arm: str = "graph_open") -> dict:
    deltas = []
    wins = losses = ties = 0
    for row in rows:
        base = treatment_of(row, "text")
        other = treatment_of(row, arm)
        if base is None or other is None:
            continue
        delta = other[metric] - base[metric]
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
        "arm": arm,
        "n": len(deltas),
        "text": statistics.fmean(
            [treatment_of(r, "text")[metric] for r in rows if treatment_of(r, "text")]
        ),
        "graph": statistics.fmean(
            [treatment_of(r, arm)[metric] for r in rows if treatment_of(r, arm)]
        ) if deltas else float("nan"),
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
    for arm in TREATMENTS:
        print(f"\n== localisation: {arm} vs text (paired, n={len(scored)}) ==")
        print(f"{'metric':14s} {'text':>7s} {'graph':>7s} {'delta':>7s} {'95% CI':>18s} "
              f"{'W/L/T':>10s} {'sign p':>7s}")
        for metric in METRICS + FILE_METRICS:
            stats = paired(rows, metric, arm)
            if stats["n"] == 0:
                continue
            print(f"{stats['metric']:14s} {stats['text']:7.3f} {stats['graph']:7.3f} "
                  f"{stats['delta']:+7.3f} {str(stats['ci95']):>18s} "
                  f"{stats['wins']:3d}/{stats['losses']:3d}/{stats['ties']:3d} "
                  f"{stats['sign_p']:7.3f}")

    head = [row["graph_headroom"] for row in scored if "graph_headroom" in row]
    pool = [row["pool_recall"] for row in scored if "pool_recall" in row]
    pool_size = max((row.get("pool", 0) for row in scored), default=0)
    oracle = [row["oracle@10"] for row in scored if "oracle@10" in row]
    if head:
        print(f"\nheadroom: {statistics.fmean(head):.3f} of gold targets are one hop "
              f"from a text-derived seed")
    if pool:
        label = f"top-{pool_size} BM25" if pool_size else "BM25 pool"
        print(f"pool recall ({label}): {statistics.fmean(pool):.3f}  "
              f"-- the ceiling both arms share")
    if oracle:
        print(f"oracle@10: {statistics.fmean(oracle):.3f}  "
              f"-- best a perfect reranker could do over pool + seed neighbours")

    unreachable = sum(1 for row in rows if row.get("gold") and not row.get("gold_nodes"))
    if unreachable:
        print(f"tasks whose gold symbols match no graph node: {unreachable}")

    print("\n== per repo ==")
    print(f"{'repo':28s} {'n':>3s} {'cov':>6s} {'r@10':>6s} {'r@10 open':>10s} "
          f"{'file@10':>8s} {'file@10 open':>13s}")
    for repo, group in sorted(_group(rows).items(), key=lambda kv: -len(kv[1])):
        stats = aggregate(group)
        scored_group = [row for row in group if row.get("arms")]

        def mean_arm(arm, metric):
            values = [treatment_of(row, arm)[metric] for row in scored_group
                      if treatment_of(row, arm) and metric in treatment_of(row, arm)]
            return statistics.fmean(values) if values else float("nan")

        print(f"{repo:28s} {stats['tasks_with_gold']:3d} "
              f"{stats['coverage'] if stats['coverage'] is not None else float('nan'):6.3f} "
              f"{mean_arm('text', 'recall@10'):6.3f} {mean_arm('graph_open', 'recall@10'):10.3f} "
              f"{mean_arm('text', 'file_recall@10'):8.3f} "
              f"{mean_arm('graph_open', 'file_recall@10'):13.3f}")
    return 0


def _group(rows: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row.get("repo", "?"), []).append(row)
    return groups


if __name__ == "__main__":
    raise SystemExit(main())
