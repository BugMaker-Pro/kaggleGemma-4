"""Retrain the ranker with the body index's opinion as two extra features.

Same folds, same seeds, same pool, same 16 features -- plus, for each candidate:

  body_in_pool   whether a body-inclusive BM25 ranks it in its own top 200
  body_rank      1 / (1 + that rank)

The comparison is the 16-feature ranker against the same ranker with the two
columns appended, so the difference is the marginal value of an extra index, not
of a different pool.

    python tools/rank_with_body_rank.py
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


def train(tasks, seed, columns):
    x = np.array([[row[i] for i in columns] for task in tasks for row in task["rows"]])
    y = np.array([label for task in tasks for label in task["labels"]])
    group = [len(task["rows"]) for task in tasks]
    return lgb.train(
        {"objective": "lambdarank", "metric": "ndcg", "ndcg_eval_at": [10],
         "learning_rate": LEARNING_RATE, "num_leaves": 15, "min_data_in_leaf": 20,
         "verbose": -1, "seed": seed, "deterministic": True},
        lgb.Dataset(x, label=y, group=group), num_boost_round=ROUNDS)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
    ap.add_argument("--extra", default=str(ROOT / "data" / "body_rank_features.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "data" / "body_rank_scores.jsonl"))
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    extra = {row["instance_id"]: row for row in
             (json.loads(line) for line in Path(args.extra).open(encoding="utf-8") if line.strip())}
    assert tuple(tasks[0]["features"]) == ORDER

    kept = []
    for task in tasks:
        row = extra.get(task["instance_id"])
        if row is None or len(row["body_rank"]) != len(task["rows"]):
            continue
        task["rows"] = [list(observation) + [row["body_in_pool"][i], row["body_rank"][i]]
                        for i, observation in enumerate(task["rows"])]
        kept.append(task)
    print(f"tasks with the body index: {len(kept)}/{len(tasks)}")

    base_columns = list(range(len(ORDER)))
    full_columns = base_columns + [len(ORDER), len(ORDER) + 1]
    repos = sorted({task["repo"] for task in kept})
    half = set(repos[::2])
    folds = ((half, set(repos) - half), (set(repos) - half, half))

    per_task: dict[str, dict[str, float]] = {}
    for train_repos, test_repos in folds:
        train_tasks = [task for task in kept if task["repo"] in train_repos]
        test_tasks = [task for task in kept if task["repo"] in test_repos]
        models = {
            "base": [train(train_tasks, seed, base_columns) for seed in SEEDS],
            "with_body": [train(train_tasks, seed, full_columns) for seed in SEEDS],
        }
        for task in test_tasks:
            x_base = np.array([[row[i] for i in base_columns] for row in task["rows"]])
            x_full = np.array(task["rows"])
            scores = {name: np.mean([model.predict(x_full if name == "with_body" else x_base)
                                     for model in models[name]], axis=0)
                      for name in ("base", "with_body")}
            total = task.get("gold_total") or 0
            per_task[task["instance_id"]] = {
                name: recall_all(order_from(list(value), task["labels"]), task["labels"], total)
                for name, value in scores.items()
            }

    ids = sorted(per_task)
    base = [per_task[i]["base"] for i in ids]
    full = [per_task[i]["with_body"] for i in ids]
    deltas = [f - b for f, b in zip(full, base)]
    wins = sum(1 for d in deltas if d > 1e-9)
    losses = sum(1 for d in deltas if d < -1e-9)
    lo, hi = bootstrap_ci(deltas)
    print(f"tasks {len(ids)}")
    print(f"  16 features          {statistics.fmean(base):.4f}")
    print(f"  + body index opinion  {statistics.fmean(full):.4f}")
    print(f"  delta {statistics.fmean(deltas):+.4f}  CI ({lo:+.3f},{hi:+.3f})  "
          f"W/L {wins}/{losses}  p={sign_test(wins, losses):.4f}")

    Path(args.out).write_text("\n".join(json.dumps({"instance_id": i, **per_task[i]}) for i in ids) + "\n",
                              encoding="utf-8")
    print(f"per-task -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
