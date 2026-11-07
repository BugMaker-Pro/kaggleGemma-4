"""Nested cross-fitted routing of graph intervention over the best ranker.

The outer fold trains the paper's 16-feature+dense LambdaMART ranker. Inside
the outer training repositories, leave-one-repository-out predictions create
unseen ranker orders for training a task-level graph router. The router then
chooses between the strong base order and its real-graph promotion on outer
test repositories. This prevents selector targets from being built on in-sample
ranker predictions.
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
from tools.select_graph_intervention import (file_recall, mean, selector_features,
                                             symbol_recall)

RANKER_SEEDS = (0, 1, 2)
ROUTER_SEEDS = (0, 1, 2)


def fit_ranker(tasks, seed):
    import lightgbm as lgb
    x = np.array([row for task in tasks for row in task["rows"]])
    y = np.array([label for task in tasks for label in task["labels"]])
    groups = [len(task["rows"]) for task in tasks]
    return lgb.train({"objective": "lambdarank", "metric": "ndcg", "ndcg_eval_at": [10],
                      "learning_rate": .05, "num_leaves": 15, "min_data_in_leaf": 20,
                      "verbose": -1, "seed": seed, "deterministic": True},
                     lgb.Dataset(x, label=y, group=groups), num_boost_round=300)


def rank(models, task):
    matrix = np.asarray(task["rows"])
    scores = np.mean([model.predict(matrix) for model in models], axis=0)
    return sorted(range(len(scores)), key=lambda candidate: -scores[candidate])


def fit_router(rows, field, seed):
    import lightgbm as lgb
    return lgb.train({"objective": "regression", "metric": "l2", "learning_rate": .03,
                      "num_leaves": 7, "min_data_in_leaf": 30, "feature_fraction": .9,
                      "verbose": -1, "seed": seed, "deterministic": True},
                     lgb.Dataset(np.asarray([row[field] for row in rows]),
                                 label=np.asarray([row["target"] for row in rows])),
                     num_boost_round=200)


def choose_threshold(rows, predictions, field):
    candidates = sorted(set(predictions))
    if not candidates:
        return 0.0
    best = (0.0, float("inf"), {})
    for threshold in [float("inf"), *candidates]:
        by_repo = {}
        for row, prediction in zip(rows, predictions):
            repo = row["context"]["repo"]
            by_repo.setdefault(repo, []).append(row["target"] if prediction > threshold else 0.0)
        repository_gains = {repo: mean(values) for repo, values in by_repo.items()}
        gain = mean(list(repository_gains.values()))
        safe = min(repository_gains.values(), default=0.0) >= -1e-12
        if safe and (gain > best[0] + 1e-12 or
                     (abs(gain - best[0]) <= 1e-12 and threshold > best[1])):
            best = (gain, threshold, repository_gains)
    return best[1]


def router_row(task, context, feature, dense, base_order):
    routed = dict(context)
    routed["orders"] = {**context["orders"], "strong": base_order}
    plain, counterfactual, uncertainty, real_order = selector_features(
        routed, "strong", feature, dense)
    target = symbol_recall(real_order, context) - symbol_recall(base_order, context)
    return {"task": task, "context": context, "base_order": base_order,
            "real_order": real_order, "target": target,
            "uncertainty": plain + uncertainty,
            "cf_uncertainty": plain + counterfactual + uncertainty}


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


def comparison(rows, arm, base):
    values = [row[arm + "_symbol"] - row[base + "_symbol"] for row in rows]
    wins = sum(value > 1e-9 for value in values)
    losses = sum(value < -1e-9 for value in values)
    return mean(values), repo_interval(rows, arm, base), wins, losses, sign_test(wins, losses)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, default=ROOT / "data/features_full.jsonl")
    parser.add_argument("--dense", type=Path, default=ROOT / "data/embed_retrieval.jsonl")
    parser.add_argument("--context", type=Path, default=ROOT / "data/graph_controls_context.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "data/counterfactual_router_scores.jsonl")
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
    folds = ((half, set(repos) - half), (set(repos) - half, half))
    output = []
    for outer_train, outer_test in folds:
        inner_rows = []
        for held_repo in sorted(outer_train):
            inner_training = [task for task in kept
                              if task["repo"] in outer_train and task["repo"] != held_repo]
            models = [fit_ranker(inner_training, seed) for seed in RANKER_SEEDS]
            for task in by_repo[held_repo]:
                instance = task["instance_id"]
                inner_rows.append(router_row(task, contexts[instance], task, dense[instance],
                                             rank(models, task)))
        routers = {field: [fit_router(inner_rows, field, seed) for seed in ROUTER_SEEDS]
                   for field in ("uncertainty", "cf_uncertainty")}
        thresholds = {}
        for field, models in routers.items():
            predictions = [mean([float(model.predict([row[field]])[0]) for model in models])
                           for row in inner_rows]
            thresholds[field] = choose_threshold(inner_rows, predictions, field)
        outer_training = [task for task in kept if task["repo"] in outer_train]
        rankers = [fit_ranker(outer_training, seed) for seed in RANKER_SEEDS]
        for repo in outer_test:
            for task in by_repo[repo]:
                instance = task["instance_id"]
                row = router_row(task, contexts[instance], task, dense[instance], rank(rankers, task))
                predictions = {field: mean([float(model.predict([row[field]])[0])
                                            for model in models])
                               for field, models in routers.items()}
                orders = {"base": row["base_order"], "real": row["real_order"],
                          "oracle": row["real_order"] if row["target"] > 0 else row["base_order"],
                          **{field: row["real_order"] if value > thresholds[field] else row["base_order"]
                             for field, value in predictions.items()}}
                context = row["context"]
                output.append({"instance_id": instance, "repo": repo,
                               "target_delta": row["target"], **predictions,
                               "uncertainty_threshold": thresholds["uncertainty"],
                               "cf_uncertainty_threshold": thresholds["cf_uncertainty"],
                               **{f"{name}_symbol": symbol_recall(order, context)
                                  for name, order in orders.items()},
                               **{f"{name}_file": file_recall(order, context)
                                  for name, order in orders.items()}})
    args.out.write_text("\n".join(json.dumps(row) for row in output) + "\n", encoding="utf-8")
    print(f"tasks {len(output)}; repositories {len(repos)}")
    for arm in ("base", "real", "uncertainty", "cf_uncertainty", "oracle"):
        print(f"{arm:15s} symbol {mean([row[arm + '_symbol'] for row in output]):.4f} "
              f"file {mean([row[arm + '_file'] for row in output]):.4f}")
    for arm, base in (("real", "base"), ("uncertainty", "base"),
                      ("cf_uncertainty", "base"), ("cf_uncertainty", "uncertainty"),
                      ("cf_uncertainty", "real")):
        delta, interval, wins, losses, p = comparison(output, arm, base)
        print(f"{arm + ' - ' + base:25s} {delta:+.4f} "
              f"repo CI ({interval[0]:+.3f},{interval[1]:+.3f}) "
              f"W/L {wins}/{losses} p={p:.4f}")
    print(f"per-task -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
