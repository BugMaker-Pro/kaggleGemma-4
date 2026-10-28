"""Is the learned ranker better than BM25, and does the graph contribute?

The first pass compared fold means, which hides how noisy a two-fold estimate is.
This version reports paired per-task deltas with a bootstrap interval, repeats
training over several seeds, and compares each ablation against the full model on
the same test tasks.

    python tools/train_rank2.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import lightgbm as lgb  # noqa: E402
import numpy as np  # noqa: E402

from tools.analyse import bootstrap_ci, sign_test  # noqa: E402

GRAPH = ("in_degree", "out_degree", "near_seed")
BODY = ("body_run", "body_line")
PATHY = ("path_in_issue", "path_overlap", "frame_hit", "frame_file", "named_file")

ROUNDS = 300
LEARNING_RATE = 0.05
SEEDS = (0, 1, 2)


def recall(order, labels, k: int) -> float:
    total = sum(labels)
    if total == 0:
        return float("nan")
    return sum(1 for index in order[:k] if labels[index]) / total


def evaluate(scores, labels, k: int = 10) -> float:
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    return recall(order, labels, k)


def train(tasks, keep, seed: int):
    x = np.array([[row[i] for i in keep] for task in tasks for row in task["rows"]])
    y = np.array([label for task in tasks for label in task["labels"]])
    group = [len(task["rows"]) for task in tasks]
    return lgb.train(
        {"objective": "lambdarank", "metric": "ndcg", "ndcg_eval_at": [10],
         "learning_rate": LEARNING_RATE, "num_leaves": 15, "min_data_in_leaf": 20,
         "verbose": -1, "seed": seed, "deterministic": True},
        lgb.Dataset(x, label=y, group=group), num_boost_round=ROUNDS,
    )


def scores_for(model, tasks, keep):
    out = {}
    for task in tasks:
        z = np.array([[row[i] for i in keep] for row in task["rows"]])
        out[task["instance_id"]] = (list(model.predict(z)), task["labels"])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features.jsonl"))
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    features = tasks[0]["features"]
    repos = sorted({task["repo"] for task in tasks})
    half = set(repos[::2])
    folds = ((half, set(repos) - half), (set(repos) - half, half))

    full, ablated = {}, {}
    for fold_index, (train_repos, test_repos) in enumerate(folds):
        train_tasks = [task for task in tasks if task["repo"] in train_repos]
        test_tasks = [task for task in tasks if task["repo"] in test_repos]
        keep = list(range(len(features)))

        seed_scores = [scores_for(train(train_tasks, keep, seed), test_tasks, keep)
                       for seed in SEEDS]
        for instance_id in seed_scores[0]:
            full[instance_id] = {
                "scores": [statistics.fmean(run[instance_id][0][i] for run in seed_scores)
                           for i in range(len(seed_scores[0][instance_id][0]))],
                "labels": seed_scores[0][instance_id][1],
                "bm25": None,
            }
        for task in test_tasks:
            full[task["instance_id"]]["bm25"] = [row[0] for row in task["rows"]]

        for label, drop in (("no graph", GRAPH), ("no body", BODY), ("no path", PATHY)):
            keep_drop = [i for i, name in enumerate(features) if name not in drop]
            run = scores_for(train(train_tasks, keep_drop, 0), test_tasks, keep_drop)
            for instance_id, (scores, _) in run.items():
                ablated.setdefault(label, {})[instance_id] = scores

    def paired(candidate: dict, base: dict) -> None:
        deltas = []
        wins = losses = 0
        for instance_id, entry in candidate.items():
            labels = full[instance_id]["labels"]
            delta = evaluate(entry, labels) - evaluate(base[instance_id] if isinstance(base, dict) else base, labels)
            if delta != delta:
                continue
            deltas.append(delta)
            wins += delta > 0
            losses += delta < 0
        lo, hi = bootstrap_ci(deltas)
        print(f"{statistics.fmean(deltas):+.3f}  CI ({lo:+.3f},{hi:+.3f})  "
              f"W/L {wins}/{losses}  p={sign_test(wins, losses):.4f}")

    learned = {key: value["scores"] for key, value in full.items()}
    bm25 = {key: value["bm25"] for key, value in full.items()}

    print(f"test tasks: {len(full)}\n")
    for name, entry in (("BM25", bm25), ("learned (3 seeds)", learned)):
        values = [evaluate(entry[i], full[i]["labels"]) for i in entry]
        values = [v for v in values if v == v]
        print(f"{name:20s} recall@10 {statistics.fmean(values):.3f}  (n={len(values)})")

    print("\nlearned vs BM25:")
    paired(learned, bm25)
    for label in ("no graph", "no body", "no path"):
        print(f"full vs {label} features removed:")
        paired(learned, ablated[label])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
