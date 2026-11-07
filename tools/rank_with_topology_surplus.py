"""Add counterfactual topology-surplus features to the paper's best ranker.

For each candidate, under both metadata and dense seed orders, append:

  real_reach   whether the real graph connects it to a top-five seed
  null_reach   fraction of constrained rewired graphs that connect it
  surplus      real_reach - null_reach

The comparison separates a plain real-reach feature from the full
counterfactual feature set. All predictions use repository-held-out folds.
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

from experiments.graph_controls import SEEDS, adjacency, reachable, rewire
from tools.analyse import bootstrap_ci, sign_test
LEARNING_RATE = 0.05
ROUNDS = 300
MODEL_SEEDS = (0, 1, 2)
ORDER = ("bm25_score", "bm25_rank", "body_run", "body_line", "path_in_issue",
         "path_overlap", "frame_hit", "frame_file", "named_file", "in_degree",
         "out_degree", "near_seed", "file_best", "file_size", "span_lines", "doc_tokens")


def order_from(scores, labels):
    return sorted(range(len(scores)), key=lambda i: -scores[i])


def recall_all(order, labels, gold_total, k=10):
    if not gold_total:
        return 0.0
    return sum(1 for index in order[:k] if labels[index]) / gold_total


def train(tasks, seed, columns):
    import lightgbm as lgb
    x = np.array([[row[i] for i in columns] for task in tasks for row in task["rows"]])
    y = np.array([label for task in tasks for label in task["labels"]])
    group = [len(task["rows"]) for task in tasks]
    return lgb.train({"objective": "lambdarank", "metric": "ndcg", "ndcg_eval_at": [10],
                      "learning_rate": LEARNING_RATE, "num_leaves": 15,
                      "min_data_in_leaf": 20, "verbose": -1, "seed": seed,
                      "deterministic": True},
                     lgb.Dataset(x, label=y, group=group), num_boost_round=ROUNDS)


def topology_columns(context, order):
    edges = [tuple(edge) for edge in context["edges"]]
    real = reachable(order, adjacency(edges))
    counts = [0] * len(order)
    for seed in SEEDS:
        randomized, _ = rewire(edges, context["files"], context["instance_id"], seed)
        for candidate in reachable(order, adjacency(randomized)):
            counts[candidate] += 1
    null = [count / len(SEEDS) for count in counts]
    return [[float(i in real), null[i], float(i in real) - null[i]] for i in range(len(order))]


def file_recall(order, files, gold_files, k=10):
    if not gold_files:
        return 0.0
    selected = {files[index] for index in order[:k] if files[index]}
    return len(selected & set(gold_files)) / len(set(gold_files))


def repo_interval(deltas, repos, draws=10000, seed=20261107):
    grouped = {}
    for task, delta in deltas.items():
        grouped.setdefault(repos[task], []).append(delta)
    names = sorted(grouped)
    rng = random.Random(seed)
    samples = []
    for _ in range(draws):
        chosen = rng.choices(names, k=len(names))
        samples.append(statistics.fmean(v for repo in chosen for v in grouped[repo]))
    samples.sort()
    return samples[int(.025 * (draws - 1))], samples[int(.975 * (draws - 1))]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, default=ROOT / "data/features_full.jsonl")
    parser.add_argument("--dense", type=Path, default=ROOT / "data/embed_retrieval.jsonl")
    parser.add_argument("--context", type=Path, default=ROOT / "data/graph_controls_context.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "data/topology_surplus_scores.jsonl")
    args = parser.parse_args(argv)

    tasks = [json.loads(line) for line in args.rows.open(encoding="utf-8") if line.strip()]
    dense = {row["instance_id"]: row for row in
             (json.loads(line) for line in args.dense.open(encoding="utf-8") if line.strip())}
    contexts = {row["instance_id"]: row for row in
                (json.loads(line) for line in args.context.open(encoding="utf-8") if line.strip())}
    assert tuple(tasks[0]["features"]) == ORDER

    kept = []
    for task in tasks:
        context, dense_row = contexts.get(task["instance_id"]), dense.get(task["instance_id"])
        if context is None or dense_row is None or not task.get("labels"):
            continue
        if task["ids"] != context["ids"]:
            raise ValueError("candidate identity mismatch")
        cosine = [0.0] * len(task["rows"])
        for rank, index in enumerate(dense_row["candidates"]):
            cosine[index] = dense_row["scores"][rank]
        meta_topology = topology_columns(context, context["orders"]["metadata"])
        dense_topology = topology_columns(context, context["orders"]["dense"])
        task["rows"] = [list(row) + [cosine[i]] + meta_topology[i] + dense_topology[i]
                        for i, row in enumerate(task["rows"])]
        kept.append(task)

    base = list(range(len(ORDER)))
    cosine = len(ORDER)
    meta = cosine + 1
    dense_graph = meta + 3
    configs = {
        "dense": base + [cosine],
        "dense_real": base + [cosine, dense_graph],
        "dense_surplus": base + [cosine, dense_graph, dense_graph + 1, dense_graph + 2],
        "dual_surplus": base + [cosine] + list(range(meta, dense_graph + 3)),
    }
    repos = sorted({task["repo"] for task in kept})
    half = set(repos[::2])
    folds = ((half, set(repos) - half), (set(repos) - half, half))
    results = {name: {} for name in configs}
    repo_of = {task["instance_id"]: task["repo"] for task in kept}
    for train_repos, test_repos in folds:
        training = [task for task in kept if task["repo"] in train_repos]
        testing = [task for task in kept if task["repo"] in test_repos]
        models = {name: [train(training, seed, columns) for seed in MODEL_SEEDS]
                  for name, columns in configs.items()}
        for task in testing:
            total = task.get("gold_total") or sum(task["labels"])
            for name, columns in configs.items():
                matrix = np.array([[row[index] for index in columns] for row in task["rows"]])
                prediction = np.mean([model.predict(matrix) for model in models[name]], axis=0)
                order = order_from(list(prediction), task["labels"])
                results[name][task["instance_id"]] = {
                    "symbol": recall_all(order, task["labels"], total),
                    "file": file_recall(order, task["files"], task.get("gold_files") or []),
                }

    ids = sorted(results["dense"])
    print(f"tasks {len(ids)}; repositories {len(repos)}")
    for name in configs:
        symbol = statistics.fmean(results[name][task]["symbol"] for task in ids)
        file_score = statistics.fmean(results[name][task]["file"] for task in ids)
        print(f"{name:15s} symbol {symbol:.4f} file {file_score:.4f}")
    for name in ("dense_real", "dense_surplus", "dual_surplus"):
        by_task = {task: results[name][task]["symbol"] - results["dense"][task]["symbol"]
                   for task in ids}
        values = list(by_task.values())
        task_ci = bootstrap_ci(values)
        repository_ci = repo_interval(by_task, repo_of)
        wins = sum(value > 1e-9 for value in values)
        losses = sum(value < -1e-9 for value in values)
        print(f"{name + ' - dense':22s} {statistics.fmean(values):+.4f} "
              f"task CI ({task_ci[0]:+.3f},{task_ci[1]:+.3f}) "
              f"repo CI ({repository_ci[0]:+.3f},{repository_ci[1]:+.3f}) "
              f"W/L {wins}/{losses} p={sign_test(wins, losses):.4f}")
    args.out.write_text("\n".join(json.dumps({"instance_id": task, "repo": repo_of[task],
        **{f"{name}_{metric}": results[name][task][metric]
           for name in configs for metric in ("symbol", "file")}}) for task in ids) + "\n",
        encoding="utf-8")
    print(f"per-task -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
