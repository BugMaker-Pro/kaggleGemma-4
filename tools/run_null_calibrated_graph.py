"""Null-calibrated graph reranking using constrained rewired graphs.

The primary arm retains five seeds and promotes a real one-hop neighbour only
when its reach exceeds the mean reach under degree/file-preserving rewiring.
Ranking is label-free; gold is read only after each shortlist is constructed.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.graph_controls import SEEDS, adjacency, promote, reachable, rewire
from tools.analyse import sign_test

REPRESENTATIONS = ("metadata", "body", "dense")


def null_probabilities(context: dict, order: list[int], pair: bool = False) -> list[float]:
    edges = [tuple(edge) for edge in context["edges"]]
    counts = [0] * len(order)
    for seed in SEEDS:
        randomized, _ = rewire(edges, context["files"], context["instance_id"], seed, pair)
        for candidate in reachable(order, adjacency(randomized)):
            counts[candidate] += 1
    return [count / len(SEEDS) for count in counts]


def calibrated_order(order: list[int], real: set[int], null: list[float],
                     seeds: int = 5, k: int = 10) -> list[int]:
    """Promote only real neighbours with positive real-minus-null reach."""
    marked = {candidate for candidate in real if 1.0 - null[candidate] > 0.0}
    return promote(order, marked, seeds=seeds, k=k)


def residual_order(order: list[int], real: set[int], null: list[float],
                   seeds: int = 5, k: int = 10) -> list[int]:
    """Sensitivity arm: order the tail by signed topology residual."""
    head, tail = order[:seeds], order[seeds:]
    position = {candidate: rank for rank, candidate in enumerate(order)}
    tail.sort(key=lambda candidate: (-(float(candidate in real) - null[candidate]),
                                     position[candidate]))
    return (head + tail)[:k]


def score(order: list[int], context: dict) -> dict[str, float]:
    chosen = order[:10]
    total = context["gold_total"]
    files = {context["files"][candidate] for candidate in chosen}
    gold_files = set(context.get("gold_files") or [])
    return {
        "symbol": sum(context["labels"][candidate] for candidate in chosen) / total,
        "file": len(files & gold_files) / len(gold_files) if gold_files else 0.0,
    }


def evaluate_context(context: dict, representation: str) -> dict:
    order = context["orders"][representation]
    real = reachable(order, adjacency(tuple(edge) for edge in context["edges"]))
    null = null_probabilities(context, order)
    strict = null_probabilities(context, order, pair=True)
    rankings = {
        "base": order[:10],
        "real": promote(order, real),
        "calibrated": calibrated_order(order, real, null),
        "strict_calibrated": calibrated_order(order, real, strict),
        "residual": residual_order(order, real, null),
    }
    return {
        "instance_id": context["instance_id"], "repo": context["repo"],
        "representation": representation, "real_reachable": len(real),
        "positive_residual": sum(candidate in real and null[candidate] < 1.0
                                 for candidate in range(len(order))),
        "arms": {name: {**score(ranking, context), "top10": ranking}
                 for name, ranking in rankings.items()},
    }


def repository_interval(rows: list[dict], arm: str, base: str,
                        draws: int = 10000, seed: int = 20261107) -> tuple[float, float]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        grouped.setdefault(row["repo"], []).append(
            row["arms"][arm]["symbol"] - row["arms"][base]["symbol"]
        )
    repos = sorted(grouped)
    rng = random.Random(seed)
    samples = []
    for _ in range(draws):
        selected = rng.choices(repos, k=len(repos))
        samples.append(statistics.fmean(
            value for repo in selected for value in grouped[repo]
        ))
    samples.sort()
    return samples[int(0.025 * (draws - 1))], samples[int(0.975 * (draws - 1))]


def compare(rows: list[dict], arm: str, base: str) -> dict:
    deltas = [row["arms"][arm]["symbol"] - row["arms"][base]["symbol"] for row in rows]
    wins = sum(delta > 1e-12 for delta in deltas)
    losses = sum(delta < -1e-12 for delta in deltas)
    return {"delta": statistics.fmean(deltas),
            "repo_ci": repository_interval(rows, arm, base),
            "wins": wins, "losses": losses, "sign_p": sign_test(wins, losses)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=Path,
                        default=ROOT / "data/graph_controls_context.jsonl")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "data/null_calibrated_graph.jsonl")
    args = parser.parse_args(argv)
    contexts = [json.loads(line) for line in args.context.open(encoding="utf-8") if line.strip()]
    results = [evaluate_context(context, representation)
               for context in contexts for representation in REPRESENTATIONS]
    args.out.write_text("\n".join(json.dumps(row) for row in results) + "\n", encoding="utf-8")
    print(f"tasks {len(contexts)}; rows {len(results)}")
    for representation in REPRESENTATIONS:
        subset = [row for row in results if row["representation"] == representation]
        print(f"\n{representation}")
        for arm in ("base", "real", "calibrated", "strict_calibrated", "residual"):
            symbol = statistics.fmean(row["arms"][arm]["symbol"] for row in subset)
            file_score = statistics.fmean(row["arms"][arm]["file"] for row in subset)
            print(f"  {arm:18s} symbol {symbol:.4f}  file {file_score:.4f}")
        for arm, base in (("real", "base"), ("calibrated", "base"),
                          ("strict_calibrated", "base"), ("residual", "base"),
                          ("calibrated", "real")):
            result = compare(subset, arm, base)
            print(f"  {arm + ' - ' + base:18s} {result['delta']:+.4f}  "
                  f"repo CI ({result['repo_ci'][0]:+.3f},{result['repo_ci'][1]:+.3f})  "
                  f"W/L {result['wins']}/{result['losses']} p={result['sign_p']:.4f}")
    print(f"\nper-task -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
