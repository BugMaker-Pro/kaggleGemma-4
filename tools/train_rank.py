"""Learning to rank over every signal, with a repository split.

The paper's arms each use one signal. This trains a ranker that may use all of
them — including four graph statistics — and asks two questions:

  1. does a learned combination beat BM25 on repositories it has never seen?
  2. does removing the graph features change anything?

The split is by repository, not by task: six repositories train, six test, so a
memorised file name cannot help. No hyper-parameter is tuned on the test fold;
the round count is fixed before the run.

    python tools/train_rank.py
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

GRAPH = ("in_degree", "out_degree", "near_seed")
BODY = ("body_run", "body_line")
PATHY = ("path_in_issue", "path_overlap", "frame_hit", "frame_file", "named_file")

ROUNDS = 300
LEARNING_RATE = 0.05


def recall_at(order: list[int], labels: list[int], k: int) -> float:
    total = sum(labels)
    if total == 0:
        return float("nan")
    return sum(1 for index in order[:k] if labels[index]) / total


def evaluate(scores: list[float], labels: list[int]) -> dict:
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    return {f"recall@{k}": recall_at(order, labels, k) for k in (1, 5, 10)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features.jsonl"))
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    features = tasks[0]["features"]
    repos = sorted({task["repo"] for task in tasks})
    fold_a = set(repos[::2])
    print(f"tasks {len(tasks)}  repositories {len(repos)}")
    print(f"fold A repos ({len([r for r in repos if r in fold_a])}): {sorted(fold_a)}")

    def run(train_repos: set[str], test_repos: set[str], drop: tuple[str, ...] = ()) -> dict:
        keep = [i for i, name in enumerate(features) if name not in drop]
        train = [task for task in tasks if task["repo"] in train_repos]
        test = [task for task in tasks if task["repo"] in test_repos]

        x = np.array([[row[i] for i in keep] for task in train for row in task["rows"]])
        y = np.array([label for task in train for label in task["labels"]])
        group = [len(task["rows"]) for task in train]
        ranker = lgb.train(
            {"objective": "lambdarank", "metric": "ndcg", "ndcg_eval_at": [10],
             "learning_rate": LEARNING_RATE, "num_leaves": 15, "min_data_in_leaf": 20,
             "verbose": -1, "lambdarank_truncation_level": 30},
            lgb.Dataset(x, label=y, group=group, feature_name=[features[i] for i in keep]),
            num_boost_round=ROUNDS,
        )

        learned, base = {f"recall@{k}": [] for k in (1, 5, 10)}, {f"recall@{k}": [] for k in (1, 5, 10)}
        for task in test:
            z = np.array([[row[i] for i in keep] for row in task["rows"]])
            scores = ranker.predict(z)
            for key, value in evaluate(list(scores), task["labels"]).items():
                learned[key].append(value)
            for key, value in evaluate([row[0] for row in task["rows"]], task["labels"]).items():
                base[key].append(value)

        def mean(values):
            values = [value for value in values if value == value]
            return round(statistics.fmean(values), 3) if values else float("nan")

        return {
            "test_tasks": len(test),
            "learned": {key: mean(value) for key, value in learned.items()},
            "bm25": {key: mean(value) for key, value in base.items()},
            "importance": dict(sorted(zip([features[i] for i in keep],
                                          ranker.feature_importance("gain").tolist()),
                                      key=lambda kv: -kv[1])),
        }

    for name, train_repos, test_repos in (("fold A->B", fold_a, set(repos) - fold_a),
                                          ("fold B->A", set(repos) - fold_a, fold_a)):
        result = run(train_repos, test_repos)
        print(f"\n== {name} (test {result['test_tasks']} tasks)")
        print(f"{'ranking':10s}{'r@1':>7s}{'r@5':>7s}{'r@10':>7s}")
        for label, key in (("BM25", "bm25"), ("learned", "learned")):
            values = result[key]
            print(f"{label:10s}{values['recall@1']:7.3f}{values['recall@5']:7.3f}"
                  f"{values['recall@10']:7.3f}")
        print("  top features by gain: "
              + ", ".join(f"{k}={v:.0f}" for k, v in list(result["importance"].items())[:6]))

    print("\n== ablation: train without a feature group (average of both folds) ==")
    for label, drop in (("no graph features", GRAPH), ("no body features", BODY),
                        ("no path/frame features", PATHY)):
        picked = []
        for train_repos, test_repos in ((fold_a, set(repos) - fold_a),
                                        (set(repos) - fold_a, fold_a)):
            result = run(train_repos, test_repos, drop)
            picked.append(result["learned"]["recall@10"])
        print(f"{label:24s} recall@10 {statistics.fmean(picked):.3f} "
              f"(folds {picked[0]:.3f} / {picked[1]:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
