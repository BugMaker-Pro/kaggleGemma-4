"""Learn when to apply graph reranking using counterfactual null features.

The selector predicts the task-level recall change from replacing a base top-10
with the fixed real-graph intervention. A positive prediction enables the graph;
otherwise the base ranking is retained. Models are trained on six repositories
and evaluated on the other six, using the paper's fixed folds.

Two feature sets isolate the proposed mechanism:

* plain: observable graph, file, seed, reach, and displacement statistics;
* counterfactual: plain plus reach and mobility under constrained rewiring.

Gold labels are used only as training targets and final evaluation outcomes.
Feature construction itself is label-free.
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

import numpy as np

from experiments.graph_controls import SEEDS, adjacency, promote, reachable, rewire
from tools.analyse import sign_test

REPRESENTATIONS = ("metadata", "body", "dense")
MODEL_SEEDS = (0, 1, 2)


def mean(values):
    return statistics.fmean(values) if values else 0.0


def spread(values):
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def overlap(first, second, k):
    return len(set(first[:k]) & set(second[:k])) / k


def uncertainty_features(context, representation, feature=None, dense=None):
    orders = context["orders"]
    current = orders[representation]
    others = [orders[name] for name in REPRESENTATIONS
              if name != representation and name in orders]
    values = []
    for other in others:
        values.extend([overlap(current, other, k) for k in (5, 10, 20, 50)])
        inverse = {candidate: rank for rank, candidate in enumerate(other)}
        values.append(mean([abs(rank - inverse[candidate]) / len(current)
                            for rank, candidate in enumerate(current)]))
    values.extend([0.0] * (10 - 5 * len(others)))
    body = context.get("body_scores") or []
    if body:
        ranked = sorted(body, reverse=True)
        span = (ranked[0] - ranked[-1]) or 1.0
        values.extend([(ranked[0] - ranked[min(4, len(ranked) - 1)]) / span,
                       (ranked[min(4, len(ranked) - 1)] - ranked[min(9, len(ranked) - 1)]) / span])
    else:
        values.extend([0.0, 0.0])
    if dense:
        ranked = dense["scores"]
        span = (ranked[0] - ranked[-1]) or 1.0
        values.extend([(ranked[0] - ranked[min(4, len(ranked) - 1)]) / span,
                       (ranked[min(4, len(ranked) - 1)] - ranked[min(9, len(ranked) - 1)]) / span])
    else:
        values.extend([0.0, 0.0])
    if feature:
        rows = feature["rows"]
        evidence = (3, 4, 6, 8)
        values.extend([sum(rows[candidate][column] > 0 for candidate in current[:10])
                       for column in evidence])
        values.extend([sum(row[column] > 0 for row in rows) / len(rows) for column in evidence])
        bm25 = [row[0] for row in rows]
        values.extend([bm25[current[0]] - bm25[current[min(4, len(current) - 1)]],
                       bm25[current[min(4, len(current) - 1)]] - bm25[current[min(9, len(current) - 1)]]])
    else:
        values.extend([0.0] * 10)
    return values


def selector_features(context: dict, representation: str, feature=None, dense=None):
    """Return plain features, counterfactual extras, and real-graph top ten."""
    order = context["orders"][representation]
    edges = [tuple(edge) for edge in context["edges"]]
    graph = adjacency(edges)
    real = reachable(order, graph)
    real_order = promote(order, real)
    n = len(order)
    rank = {candidate: position for position, candidate in enumerate(order)}
    seeds = order[:5]
    tail = order[5:]
    files = context["files"]
    file_counts = {}
    for path in files:
        file_counts[path] = file_counts.get(path, 0) + 1
    real_ranks = [rank[candidate] for candidate in real]
    base_top = set(order[:10])
    graph_top = set(real_order[:10])
    seed_degrees = [len(graph.get(candidate, ())) for candidate in seeds]
    plain = [
        math.log1p(n), math.log1p(len(edges)), len(edges) / max(n, 1),
        len(real), len(real) / max(len(tail), 1),
        mean([1.0 / (1.0 + value) for value in real_ranks]),
        min(real_ranks, default=n) / max(n, 1),
        sum(candidate in real for candidate in order[5:10]),
        len(graph_top - base_top), len(base_top - graph_top),
        mean(seed_degrees), max(seed_degrees, default=0), spread(seed_degrees),
        len({files[candidate] for candidate in seeds}),
        len(file_counts), max(file_counts.values(), default=0) / max(n, 1),
        len({files[candidate] for candidate in order[:10]}),
    ]

    null_sets, mobility = [], []
    for seed in SEEDS:
        randomized, diagnostics = rewire(edges, files, context["instance_id"], seed)
        null_sets.append(reachable(order, adjacency(randomized)))
        mobility.append(diagnostics["changed_fraction"])
    null_probability = [sum(candidate in values for values in null_sets) / len(null_sets)
                        for candidate in range(n)]
    null_sizes = [len(values) for values in null_sets]
    jaccard = [len(real & values) / len(real | values) if real | values else 1.0
               for values in null_sets]
    surplus = [1.0 - null_probability[candidate] for candidate in real]
    counterfactual = [
        mean(null_sizes), spread(null_sizes), mean(null_sizes) / max(len(tail), 1),
        mean(jaccard), spread(jaccard),
        sum(surplus), mean(surplus), spread(surplus),
        sum(value >= 0.5 for value in surplus),
        sum(value > 0.0 for value in surplus),
        mean(mobility), spread(mobility), min(mobility, default=0.0),
    ]
    uncertainty = uncertainty_features(context, representation, feature, dense)
    return plain, counterfactual, uncertainty, real_order


def symbol_recall(order: list[int], context: dict) -> float:
    return sum(context["labels"][candidate] for candidate in order[:10]) / context["gold_total"]


def file_recall(order: list[int], context: dict) -> float:
    gold = set(context.get("gold_files") or [])
    selected = {context["files"][candidate] for candidate in order[:10]}
    return len(selected & gold) / len(gold) if gold else 0.0


def fit(x, y, seed):
    import lightgbm as lgb
    return lgb.train({"objective": "regression", "metric": "l2", "learning_rate": 0.03,
                      "num_leaves": 7, "min_data_in_leaf": 30, "feature_fraction": 0.9,
                      "verbose": -1, "seed": seed, "deterministic": True},
                     lgb.Dataset(np.asarray(x), label=np.asarray(y)), num_boost_round=200)


def repo_interval(rows, arm, base, draws=10000, seed=20261107):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["repo"], []).append(row[arm + "_symbol"] - row[base + "_symbol"])
    repos = sorted(grouped)
    rng = random.Random(seed)
    samples = []
    for _ in range(draws):
        chosen = rng.choices(repos, k=len(repos))
        samples.append(statistics.fmean(value for repo in chosen for value in grouped[repo]))
    samples.sort()
    return samples[int(.025 * (draws - 1))], samples[int(.975 * (draws - 1))]


def report(rows, arm, base):
    deltas = [row[arm + "_symbol"] - row[base + "_symbol"] for row in rows]
    wins = sum(value > 1e-9 for value in deltas)
    losses = sum(value < -1e-9 for value in deltas)
    interval = repo_interval(rows, arm, base)
    return statistics.fmean(deltas), interval, wins, losses, sign_test(wins, losses)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=Path, default=ROOT / "data/graph_controls_context.jsonl")
    parser.add_argument("--features", type=Path, default=ROOT / "data/features_full.jsonl")
    parser.add_argument("--dense", type=Path, default=ROOT / "data/embed_retrieval.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "data/graph_intervention_selector.jsonl")
    args = parser.parse_args(argv)
    contexts = [json.loads(line) for line in args.context.open(encoding="utf-8") if line.strip()]
    features = {row["instance_id"]: row for row in
                (json.loads(line) for line in args.features.open(encoding="utf-8") if line.strip())}
    dense_rows = {row["instance_id"]: row for row in
                  (json.loads(line) for line in args.dense.open(encoding="utf-8") if line.strip())}
    repos = sorted({context["repo"] for context in contexts})
    half = set(repos[::2])
    folds = ((half, set(repos) - half), (set(repos) - half, half))
    output = []
    for representation in REPRESENTATIONS:
        prepared = []
        for context in contexts:
            plain, extra, uncertainty, real_order = selector_features(
                context, representation, features.get(context["instance_id"]),
                dense_rows.get(context["instance_id"]))
            base_order = context["orders"][representation][:10]
            base_symbol = symbol_recall(base_order, context)
            real_symbol = symbol_recall(real_order, context)
            prepared.append({"context": context, "plain": plain, "counterfactual": plain + extra,
                             "uncertainty": plain + uncertainty,
                             "cf_uncertainty": plain + extra + uncertainty,
                             "base_order": base_order, "real_order": real_order,
                             "target": real_symbol - base_symbol})
        for train_repos, test_repos in folds:
            training = [row for row in prepared if row["context"]["repo"] in train_repos]
            testing = [row for row in prepared if row["context"]["repo"] in test_repos]
            models = {}
            for name in ("plain", "counterfactual", "uncertainty", "cf_uncertainty"):
                models[name] = [fit([row[name] for row in training],
                                    [row["target"] for row in training], seed)
                                for seed in MODEL_SEEDS]
            for row in testing:
                context = row["context"]
                predictions = {name: mean([float(model.predict([row[name]])[0])
                                           for model in family])
                               for name, family in models.items()}
                chosen = {name: row["real_order"] if value > 0.0 else row["base_order"]
                          for name, value in predictions.items()}
                orders = {"base": row["base_order"], "real": row["real_order"],
                          "oracle": row["real_order"] if row["target"] > 0 else row["base_order"],
                          "plain": chosen["plain"], "counterfactual": chosen["counterfactual"],
                          "uncertainty": chosen["uncertainty"],
                          "cf_uncertainty": chosen["cf_uncertainty"]}
                output.append({"instance_id": context["instance_id"], "repo": context["repo"],
                               "representation": representation, "target_delta": row["target"],
                               "plain_prediction": predictions["plain"],
                               "counterfactual_prediction": predictions["counterfactual"],
                               "uncertainty_prediction": predictions["uncertainty"],
                               "cf_uncertainty_prediction": predictions["cf_uncertainty"],
                               **{f"{name}_symbol": symbol_recall(order, context)
                                  for name, order in orders.items()},
                               **{f"{name}_file": file_recall(order, context)
                                  for name, order in orders.items()}})
    args.out.write_text("\n".join(json.dumps(row) for row in output) + "\n", encoding="utf-8")
    for representation in REPRESENTATIONS:
        rows = [row for row in output if row["representation"] == representation]
        print(f"\n{representation} n={len(rows)}")
        for arm in ("base", "real", "plain", "counterfactual", "uncertainty",
                    "cf_uncertainty", "oracle"):
            print(f"  {arm:15s} symbol {mean([row[arm + '_symbol'] for row in rows]):.4f} "
                  f"file {mean([row[arm + '_file'] for row in rows]):.4f}")
        for arm, base in (("plain", "base"), ("counterfactual", "base"),
                          ("uncertainty", "base"), ("cf_uncertainty", "base"),
                          ("cf_uncertainty", "uncertainty"),
                          ("cf_uncertainty", "counterfactual"),
                          ("cf_uncertainty", "real")):
            delta, interval, wins, losses, p = report(rows, arm, base)
            print(f"  {arm + ' - ' + base:23s} {delta:+.4f} "
                  f"repo CI ({interval[0]:+.3f},{interval[1]:+.3f}) "
                  f"W/L {wins}/{losses} p={p:.4f}")
    print(f"\nper-task -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
