"""The best stack we can build: cheap features, the fix-history prior, and a model.

`analyse_rerank.py` compares the cross-encoder against the feature ranker on the
same pool. This adds the model's score as one more column and retrains, so the
question becomes the practical one: what does the whole stack reach, and is the
model's contribution additive to the features or does it double-count them?

    python tools/rank_with_model.py
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
from tools.run_combo_ltr import (LEARNING_RATE, ORDER, ROUNDS, SEEDS,  # noqa: E402
                                 order_from, recall_all)


def train(tasks, seed: int, columns):
    x = np.array([[row[i] for i in columns] for task in tasks for row in task["rows"]])
    y = np.array([label for task in tasks for label in task["labels"]])
    group = [len(task["rows"]) for task in tasks]
    return lgb.train(
        {"objective": "lambdarank", "metric": "ndcg", "ndcg_eval_at": [10],
         "learning_rate": LEARNING_RATE, "num_leaves": 15, "min_data_in_leaf": 20,
         "verbose": -1, "seed": seed, "deterministic": True},
        lgb.Dataset(x, label=y, group=group), num_boost_round=ROUNDS,
    )


def bucket_of(task: dict) -> str:
    rows, labels = task["rows"], task["labels"]
    for index, label in enumerate(labels):
        if label and rows[index][3]:
            return "quotes"
    for index, label in enumerate(labels):
        if label and (rows[index][4] or rows[index][6] or rows[index][8]):
            return "names"
    return "neither"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
    ap.add_argument("--model", default=str(ROOT / "data" / "rerank_model.jsonl"))
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    scores = {row["instance_id"]: row for row in
              (json.loads(line) for line in Path(args.model).open(encoding="utf-8") if line.strip())}

    kept = []
    for task in tasks:
        record = scores.get(task["instance_id"])
        if not record or not task.get("labels"):
            continue
        value = [0.0] * len(task["rows"])
        for position, index in enumerate(record["candidates"]):
            value[index] = float(record["scores"][position])
        spread = max(value) - min(value)
        for row, raw in zip(task["rows"], value):
            row.append((raw - min(value)) / spread if spread else 0.0)
        kept.append(task)
    tasks = kept
    base = list(range(len(ORDER)))
    columns = base + [len(ORDER)]

    repos = sorted({task["repo"] for task in tasks})
    half = set(repos[::2])
    folds = ((half, set(repos) - half), (set(repos) - half, half))
    plain, stacked = {}, {}
    groups: dict[str, list[str]] = {}

    for train_repos, test_repos in folds:
        tr = [task for task in tasks if task["repo"] in train_repos]
        te = [task for task in tasks if task["repo"] in test_repos]
        models_plain = [train(tr, seed, base) for seed in SEEDS]
        models_stack = [train(tr, seed, columns) for seed in SEEDS]
        for task in te:
            total = task.get("gold_total") or sum(task["labels"])
            for store, models, cols in ((plain, models_plain, base), (stacked, models_stack, columns)):
                z = np.array([[row[i] for i in cols] for row in task["rows"]])
                prediction = np.mean([model.predict(z) for model in models], axis=0)
                order = order_from(list(prediction), task["labels"])
                store[task["instance_id"]] = recall_all(order, task["labels"], total)
            groups.setdefault(bucket_of(task), []).append(task["instance_id"])

    print(f"16 features            {statistics.fmean(plain.values()):.3f}")
    print(f"17, + model score      {statistics.fmean(stacked.values()):.3f}")
    keys = sorted(plain)
    deltas = [stacked[key] - plain[key] for key in keys]
    wins = sum(1 for value in deltas if value > 0)
    losses = sum(1 for value in deltas if value < 0)
    lo, hi = bootstrap_ci(deltas)
    print(f"delta {statistics.fmean(deltas):+.3f}  CI ({lo:+.3f},{hi:+.3f})  "
          f"W/L {wins}/{losses}  p={sign_test(wins, losses):.4f}")

    print(f"\n{'bucket':10s}{'n':>6s}{'16 feats':>10s}{'+ model':>10s}{'delta':>9s}")
    for name in ("quotes", "names", "neither"):
        ids = groups.get(name, [])
        if not ids:
            continue
        a = statistics.fmean(plain[key] for key in ids)
        b = statistics.fmean(stacked[key] for key in ids)
        print(f"{name:10s}{len(ids):6d}{a:10.3f}{b:10.3f}{b - a:+9.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
