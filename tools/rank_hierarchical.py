"""Hierarchical ranking: choose the file, then the symbol inside it.

The flat ranker scores 200 candidates at once and has to learn the file prior
implicitly from 1-3 positive labels. The decomposition we measured says the
problem is a product -- recall@10 is P(right file) x E[recovered | right file],
66.5% for the second factor -- so the model should be a product too:

    score(symbol) = z(file score of its file) + z(symbol score within the task)

Two rankers, same folds, same seeds, same pool:

  file model    one row per file in the pool, label = the file holds a gold
                symbol. Supervision is dense (a few dozen files per task).
  symbol model  one row per candidate, features plus three within-file
                normalisations (score / best in file, rank in file, is best).

Both scores are z-scored inside the task before they are added, so the two
models' arbitrary score scales cannot tilt the sum; nothing is tuned on the test
folds.

    python tools/rank_hierarchical.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import lightgbm as lgb  # noqa: E402
import numpy as np  # noqa: E402

from tools.analyse import bootstrap_ci, sign_test  # noqa: E402
from tools.run_combo_ltr import LEARNING_RATE, ORDER, ROUNDS, SEEDS  # noqa: E402

FILE_COLUMNS = ("n_pool", "best_score", "best_rank", "mean_score", "body_run", "body_line",
                "in_issue", "frame_file", "named_file", "size", "in_degree", "out_degree",
                "near_seed", "max_doc")


def zscore(values: np.ndarray) -> np.ndarray:
    if len(values) < 2:
        return np.zeros_like(values)
    spread = float(values.std())
    if spread < 1e-9:
        return np.zeros_like(values)
    return (values - float(values.mean())) / spread


def file_matrix(task: dict) -> tuple[list[str], np.ndarray, np.ndarray, list[list[int]]]:
    """One row per file: aggregated features, label, and the indices it owns."""
    groups: dict[str, list[int]] = defaultdict(list)
    for index, path in enumerate(task["files"]):
        groups[path].append(index)
    paths = list(groups)
    rows, labels, members = [], [], []
    for path in paths:
        indices = groups[path]
        block = np.array([task["rows"][i] for i in indices], dtype=float)
        rows.append([
            len(indices),
            float(block[:, 0].max()),          # best normalised bm25
            float(block[:, 1].max()),          # best 1/rank
            float(block[:, 0].mean()),
            float(block[:, 2].max()),          # body_run
            float(block[:, 3].max()),          # body_line
            float(block[:, 4].max()),          # path_in_issue
            float(block[:, 6].max()),          # frame_file
            float(block[:, 8].max()),          # named_file
            float(block[:, 13].max()),         # file_size
            float(block[:, 9].max()),          # in_degree
            float(block[:, 10].max()),         # out_degree
            float(block[:, 11].sum()),         # near_seed count
            float(block[:, 15].max()),         # doc_tokens
        ])
        labels.append(1 if any(task["labels"][i] for i in indices) else 0)
        members.append(indices)
    return paths, np.array(rows), np.array(labels), members


def symbol_matrix(task: dict, members: list[list[int]]) -> np.ndarray:
    """The sixteen features plus three within-file normalisations."""
    extra = [np.zeros(len(task["rows"])), np.zeros(len(task["rows"])), np.zeros(len(task["rows"]))]
    for indices in members:
        block = np.array([task["rows"][i][0] for i in indices], dtype=float)
        best = float(block.max()) or 1.0
        order = block.argsort()[::-1]
        rank_of = {indices[position]: rank for rank, position in enumerate(order)}
        for position, index in enumerate(indices):
            extra[0][index] = block[position] / best
            extra[1][index] = 1.0 / (1.0 + rank_of[index])
            extra[2][index] = 1.0 if block[position] == block.max() else 0.0
    base = np.array(task["rows"], dtype=float)
    return np.column_stack([base] + extra)


def fit(x: np.ndarray, y: np.ndarray, groups: list[int], seed: int) -> lgb.Booster:
    return lgb.train(
        {"objective": "lambdarank", "metric": "ndcg", "ndcg_eval_at": [10],
         "learning_rate": LEARNING_RATE, "num_leaves": 15, "min_data_in_leaf": 20,
         "verbose": -1, "seed": seed, "deterministic": True},
        lgb.Dataset(x, label=y, group=groups), num_boost_round=ROUNDS)


def recall(order: list[int], labels: list[int], total: int, k: int = 10) -> float:
    if not total:
        return 0.0
    return sum(1 for index in order[:k] if labels[index]) / total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "data" / "hier_scores.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    if args.limit:
        tasks = tasks[: args.limit]
    assert tuple(tasks[0]["features"]) == ORDER
    repos = sorted({task["repo"] for task in tasks})
    half = set(repos[::2])
    folds = ((half, set(repos) - half), (set(repos) - half, half))

    per_task: dict[str, dict[str, float]] = {}
    for train_repos, test_repos in folds:
        train_tasks = [task for task in tasks if task["repo"] in train_repos]
        test_tasks = [task for task in tasks if task["repo"] in test_repos]

        flat_x = np.array([row for task in train_tasks for row in task["rows"]], dtype=float)
        flat_y = np.array([label for task in train_tasks for label in task["labels"]])
        flat_group = [len(task["rows"]) for task in train_tasks]

        file_x, file_y, file_group, symbol_x, symbol_y, symbol_group = [], [], [], [], [], []
        for task in train_tasks:
            _paths, matrix, labels, members = file_matrix(task)
            file_x.extend(matrix)
            file_y.extend(labels)
            file_group.append(len(matrix))
            features = symbol_matrix(task, members)
            symbol_x.extend(features)
            symbol_y.extend(task["labels"])
            symbol_group.append(len(features))

        flat_models = [fit(flat_x, flat_y, flat_group, seed) for seed in SEEDS]
        file_models = [fit(np.array(file_x), np.array(file_y), file_group, seed) for seed in SEEDS]
        symbol_models = [fit(np.array(symbol_x), np.array(symbol_y), symbol_group, seed) for seed in SEEDS]

        for task in test_tasks:
            paths, matrix, _labels, members = file_matrix(task)
            features = symbol_matrix(task, members)
            flat_scores = np.mean([model.predict(np.array(task["rows"], dtype=float))
                                   for model in flat_models], axis=0)
            file_scores = np.mean([model.predict(matrix) for model in file_models], axis=0)
            symbol_scores = np.mean([model.predict(features) for model in symbol_models], axis=0)

            file_of = np.zeros(len(task["rows"]), dtype=int)
            for position, indices in enumerate(members):
                for index in indices:
                    file_of[index] = position
            combined = zscore(file_scores)[file_of] + zscore(symbol_scores)

            total = task.get("gold_total") or 0
            per_task[task["instance_id"]] = {
                "gold_total": total,
                "labels": task["labels"],
                "flat": recall(sorted(range(len(flat_scores)), key=lambda i: -flat_scores[i]),
                               task["labels"], total),
                "hier": recall(sorted(range(len(combined)), key=lambda i: -combined[i]),
                               task["labels"], total),
            }

    ids = sorted(per_task)
    flat = [per_task[i]["flat"] for i in ids]
    hier = [per_task[i]["hier"] for i in ids]
    deltas = [h - f for h, f in zip(hier, flat)]
    wins = sum(1 for d in deltas if d > 1e-9)
    losses = sum(1 for d in deltas if d < -1e-9)
    lo, hi = bootstrap_ci(deltas)
    print(f"tasks {len(ids)}")
    print(f"  flat   {statistics.fmean(flat):.4f}")
    print(f"  hier   {statistics.fmean(hier):.4f}")
    print(f"  delta  {statistics.fmean(deltas):+.4f}  CI ({lo:+.3f},{hi:+.3f})  "
          f"W/L {wins}/{losses}  p={sign_test(wins, losses):.4f}")

    with Path(args.out).open("w", encoding="utf-8") as fh:
        for instance_id in ids:
            fh.write(json.dumps({"instance_id": instance_id, **per_task[instance_id]}) + "\n")
    print(f"per-task -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
