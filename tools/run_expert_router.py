"""Nested routing between the learned+dense ranker and frozen dense retrieval.

The experts are complementary: the task-level oracle between them reaches
47.1% symbol recall versus 44.7% for the learned+dense ranker. This script uses
nested repository cross-fitting to learn when the simpler semantic expert is
preferable, without training the router on in-sample expert outcomes.
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

import numpy as np

from tools.analyse import sign_test
from tools.select_graph_intervention import mean, selector_features

RANKER_SEEDS = (0, 1, 2)
ROUTER_SEEDS = (0, 1, 2)


def fit_ranker(tasks, seed):
    import lightgbm as lgb
    x = np.asarray([row for task in tasks for row in task["rows"]])
    y = np.asarray([label for task in tasks for label in task["labels"]])
    groups = [len(task["rows"]) for task in tasks]
    return lgb.train({"objective": "lambdarank", "metric": "ndcg", "ndcg_eval_at": [10],
                      "learning_rate": .05, "num_leaves": 15, "min_data_in_leaf": 20,
                      "verbose": -1, "seed": seed, "deterministic": True},
                     lgb.Dataset(x, label=y, group=groups), num_boost_round=300)


def predict(models, task):
    matrix = np.asarray(task["rows"])
    scores = np.mean([model.predict(matrix) for model in models], axis=0)
    order = sorted(range(len(scores)), key=lambda candidate: -scores[candidate])
    return order, list(scores)


def fit_router(rows, field, seed):
    import lightgbm as lgb
    return lgb.train({"objective": "regression", "metric": "l2", "learning_rate": .03,
                      "num_leaves": 7, "min_data_in_leaf": 30, "feature_fraction": .9,
                      "verbose": -1, "seed": seed, "deterministic": True},
                     lgb.Dataset(np.asarray([row[field] for row in rows]),
                                 label=np.asarray([row["target"] for row in rows])),
                     num_boost_round=200)


def recall(order, task):
    return sum(task["labels"][candidate] for candidate in order[:10]) / task["gold_total"]


def file_recall(order, task):
    gold = set(task.get("gold_files") or [])
    selected = {task["files"][candidate] for candidate in order[:10]}
    return len(selected & gold) / len(gold) if gold else 0.0


def overlap(first, second, k):
    return len(set(first[:k]) & set(second[:k])) / k


def margin(scores, order, left, right):
    if not order:
        return 0.0
    a = scores[order[min(left, len(order) - 1)]]
    b = scores[order[min(right, len(order) - 1)]]
    span = max(scores) - min(scores)
    return (a - b) / span if span else 0.0


def task_features(task, context, dense_row, strong_order, strong_scores):
    dense_order = dense_row["candidates"]
    dense_scores = [0.0] * len(dense_order)
    for position, candidate in enumerate(dense_order):
        dense_scores[candidate] = dense_row["scores"][position]
    disagreement = [overlap(strong_order, dense_order, k) for k in (1, 5, 10, 20, 50)]
    inverse = {candidate: rank for rank, candidate in enumerate(dense_order)}
    disagreement.extend([
        mean([abs(rank - inverse[candidate]) / len(strong_order)
              for rank, candidate in enumerate(strong_order)]),
        len({task["files"][candidate] for candidate in strong_order[:10]}),
        len({task["files"][candidate] for candidate in dense_order[:10]}),
    ])
    for scores, order in ((strong_scores, strong_order), (dense_scores, dense_order)):
        disagreement.extend([margin(scores, order, 0, 4), margin(scores, order, 4, 9),
                             margin(scores, order, 9, 19),
                             statistics.pstdev([scores[candidate] for candidate in order[:20]])])
    evidence_columns = (2, 3, 4, 6, 8)
    disagreement.extend([sum(task["rows"][candidate][column] > 0
                               for candidate in strong_order[:10])
                         for column in evidence_columns])
    disagreement.extend([sum(row[column] > 0 for row in task["rows"]) / len(task["rows"])
                         for column in evidence_columns])
    routed = dict(context)
    routed["orders"] = {**context["orders"], "strong": strong_order}
    plain, counterfactual, uncertainty, _ = selector_features(
        routed, "strong", task, dense_row)
    return {"disagreement": disagreement + uncertainty,
            "cf_disagreement": disagreement + uncertainty + plain + counterfactual}


def prepare(task, context, dense_row, strong_order, strong_scores):
    features = task_features(task, context, dense_row, strong_order, strong_scores)
    dense_order = dense_row["candidates"]
    features.update({"task": task, "strong_order": strong_order, "dense_order": dense_order,
                     "target": recall(dense_order, task) - recall(strong_order, task)})
    return features


def choose_threshold(rows, predictions, robust=False):
    best = (0.0, float("inf"))
    for threshold in [float("inf"), *sorted(set(predictions))]:
        if robust:
            grouped = {}
            for row, prediction in zip(rows, predictions):
                grouped.setdefault(row["task"]["repo"], []).append(
                    row["target"] if prediction > threshold else 0.0)
            gains = [mean(values) for values in grouped.values()]
            gain = mean(gains)
            feasible = min(gains, default=0.0) >= -1e-12
        else:
            gain = mean([row["target"] if prediction > threshold else 0.0
                         for row, prediction in zip(rows, predictions)])
            feasible = True
        if feasible and (gain > best[0] + 1e-12 or
                         (abs(gain - best[0]) <= 1e-12 and threshold > best[1])):
            best = (gain, threshold)
    return best[1]


def repo_interval(rows, arm, base, draws=10000, seed=20261107):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["repo"], []).append(row[arm + "_symbol"] - row[base + "_symbol"])
    names = sorted(grouped)
    rng = random.Random(seed)
    samples = []
    for _ in range(draws):
        chosen = rng.choices(names, k=len(names))
        samples.append(mean([value for repo in chosen for value in grouped[repo]]))
    samples.sort()
    return samples[int(.025 * (draws - 1))], samples[int(.975 * (draws - 1))]


def report(rows, arm, base):
    values = [row[arm + "_symbol"] - row[base + "_symbol"] for row in rows]
    wins = sum(value > 1e-9 for value in values)
    losses = sum(value < -1e-9 for value in values)
    return mean(values), repo_interval(rows, arm, base), wins, losses, sign_test(wins, losses)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, default=ROOT / "data/features_full.jsonl")
    parser.add_argument("--dense", type=Path, default=ROOT / "data/embed_retrieval.jsonl")
    parser.add_argument("--context", type=Path, default=ROOT / "data/graph_controls_context.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "data/expert_router_scores.jsonl")
    args = parser.parse_args(argv)
    tasks = [json.loads(line) for line in args.features.open(encoding="utf-8") if line.strip()]
    dense = {row["instance_id"]: row for row in
             (json.loads(line) for line in args.dense.open(encoding="utf-8") if line.strip())}
    contexts = {row["instance_id"]: row for row in
                (json.loads(line) for line in args.context.open(encoding="utf-8") if line.strip())}
    kept = []
    for task in tasks:
        dense_row = dense.get(task["instance_id"])
        if dense_row is None or task["instance_id"] not in contexts or not task.get("labels"):
            continue
        cosine = [0.0] * len(task["rows"])
        for position, candidate in enumerate(dense_row["candidates"]):
            cosine[candidate] = dense_row["scores"][position]
        task["rows"] = [list(row) + [cosine[index]] for index, row in enumerate(task["rows"])]
        kept.append(task)
    by_repo = {}
    for task in kept:
        by_repo.setdefault(task["repo"], []).append(task)
    repos = sorted(by_repo)
    half = set(repos[::2])
    output = []
    for outer_train, outer_test in ((half, set(repos) - half), (set(repos) - half, half)):
        inner_rows = []
        for held_repo in sorted(outer_train):
            training = [task for task in kept
                        if task["repo"] in outer_train and task["repo"] != held_repo]
            models = [fit_ranker(training, seed) for seed in RANKER_SEEDS]
            for task in by_repo[held_repo]:
                order, scores = predict(models, task)
                instance = task["instance_id"]
                inner_rows.append(prepare(task, contexts[instance], dense[instance], order, scores))
        routers = {field: [fit_router(inner_rows, field, seed) for seed in ROUTER_SEEDS]
                   for field in ("disagreement", "cf_disagreement")}
        thresholds = {}
        for field, models in routers.items():
            predictions = [mean([float(model.predict([row[field]])[0]) for model in models])
                           for row in inner_rows]
            thresholds[field] = choose_threshold(inner_rows, predictions, robust=False)
            thresholds[field + "_robust"] = choose_threshold(inner_rows, predictions, robust=True)
        outer_models = [fit_ranker([task for task in kept if task["repo"] in outer_train], seed)
                        for seed in RANKER_SEEDS]
        for repo in outer_test:
            for task in by_repo[repo]:
                strong_order, strong_scores = predict(outer_models, task)
                instance = task["instance_id"]
                row = prepare(task, contexts[instance], dense[instance], strong_order, strong_scores)
                predictions = {field: mean([float(model.predict([row[field]])[0]) for model in models])
                               for field, models in routers.items()}
                orders = {"strong": row["strong_order"], "dense": row["dense_order"],
                          "oracle": row["dense_order"] if row["target"] > 0 else row["strong_order"]}
                for field, prediction in predictions.items():
                    orders[field] = row["dense_order"] if prediction > thresholds[field] else row["strong_order"]
                    orders[field + "_robust"] = (row["dense_order"] if prediction > thresholds[field + "_robust"]
                                                   else row["strong_order"])
                output.append({"instance_id": instance, "repo": repo, "target_delta": row["target"],
                               **predictions, **{name + "_threshold": value for name, value in thresholds.items()},
                               **{f"{name}_symbol": recall(order, task) for name, order in orders.items()},
                               **{f"{name}_file": file_recall(order, task) for name, order in orders.items()}})
    args.out.write_text("\n".join(json.dumps(row) for row in output) + "\n", encoding="utf-8")
    arms = ("strong", "dense", "disagreement", "cf_disagreement",
            "disagreement_robust", "cf_disagreement_robust", "oracle")
    print(f"tasks {len(output)}; repositories {len(repos)}")
    for arm in arms:
        print(f"{arm:24s} symbol {mean([row[arm + '_symbol'] for row in output]):.4f} "
              f"file {mean([row[arm + '_file'] for row in output]):.4f}")
    for arm in arms[2:-1]:
        delta, interval, wins, losses, p = report(output, arm, "strong")
        print(f"{arm + ' - strong':32s} {delta:+.4f} repo CI ({interval[0]:+.3f},{interval[1]:+.3f}) "
              f"W/L {wins}/{losses} p={p:.4f}")
    print(f"per-task -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
