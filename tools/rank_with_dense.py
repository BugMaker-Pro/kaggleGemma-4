"""Does a dense score add anything on top of the sixteen features?

The dense arm alone ties the ranker on symbols (0.366 against 0.361) and beats it
on files, so the obvious question is whether the two signals are complementary.
This appends one column -- the bi-encoder cosine between the issue and the
candidate -- to the same sixteen, retrains on the same folds, and pairs the
result with both parents.

    python tools/rank_with_dense.py
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


def file_recall(order: list[int], files: list[str], gold_files: list[str], k: int = 10) -> float:
    if not gold_files:
        return 0.0
    seen = []
    for index in order[:k]:
        name = files[index]
        if name and name not in seen:
            seen.append(name)
    return len(set(seen) & set(gold_files)) / len(gold_files)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
    ap.add_argument("--embed", default=str(ROOT / "data" / "embed_retrieval.jsonl"))
    ap.add_argument("--body-extra", default=str(ROOT / "data" / "body_rank_features.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "data" / "dense_scores.jsonl"))
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    embed = {row["instance_id"]: row for row in
             (json.loads(line) for line in Path(args.embed).open(encoding="utf-8") if line.strip())}
    body_extra = {}
    if Path(args.body_extra).exists():
        body_extra = {row["instance_id"]: row for row in
                      (json.loads(line) for line in Path(args.body_extra).open(encoding="utf-8")
                       if line.strip())}
    assert tuple(tasks[0]["features"]) == ORDER

    kept = []
    for task in tasks:
        row = embed.get(task["instance_id"])
        if row is None:
            continue
        cosine = [0.0] * len(task["rows"])
        for rank, index in enumerate(row["candidates"]):
            cosine[index] = row["scores"][rank]
        extra = body_extra.get(task["instance_id"])
        task["rows"] = [list(observation) + [cosine[i]]
                        + ([extra["body_in_pool"][i], extra["body_rank"][i]] if extra else [])
                        for i, observation in enumerate(task["rows"])]
        task["cosine"] = cosine
        task["has_body"] = bool(extra)
        kept.append(task)
    print(f"tasks with a dense score: {len(kept)}/{len(tasks)}"
          f", with body-rank columns: {sum(1 for t in kept if t['has_body'])}")

    base_columns = list(range(len(ORDER)))
    full_columns = base_columns + [len(ORDER)]
    both_columns = full_columns + [len(ORDER) + 1, len(ORDER) + 2]
    repos = sorted({task["repo"] for task in kept})
    half = set(repos[::2])
    folds = ((half, set(repos) - half), (set(repos) - half, half))

    per_task: dict[str, dict[str, float]] = {}
    for train_repos, test_repos in folds:
        train_tasks = [task for task in kept if task["repo"] in train_repos]
        test_tasks = [task for task in kept if task["repo"] in test_repos]
        models = {name: [train(train_tasks, seed, columns) for seed in SEEDS]
                  for name, columns in (("base", base_columns), ("dense", full_columns),
                                        ("both", both_columns))}
        for task in test_tasks:
            x_base = np.array([[row[i] for i in base_columns] for row in task["rows"]])
            x_full = np.array([[row[i] for i in full_columns] for row in task["rows"]])
            x_both = np.array([[row[i] for i in both_columns] for row in task["rows"]])
            scores = {
                "base": np.mean([m.predict(x_base) for m in models["base"]], axis=0),
                "dense": np.mean([m.predict(x_full) for m in models["dense"]], axis=0),
                "both": np.mean([m.predict(x_both) for m in models["both"]], axis=0),
                "cosine": np.array(task["cosine"]),
            }
            total = task.get("gold_total") or 0
            order = {name: order_from(list(value), task["labels"]) for name, value in scores.items()}
            per_task[task["instance_id"]] = {
                f"{name}_symbol": recall_all(order[name], task["labels"], total)
                for name in scores
            }
            per_task[task["instance_id"]].update({
                f"{name}_file": file_recall(order[name], task["files"], task.get("gold_files") or [])
                for name in scores
            })

    ids = sorted(per_task)
    print(f"tasks {len(ids)}")
    for name in ("base", "cosine", "dense", "both"):
        symbol = statistics.fmean(per_task[i][f"{name}_symbol"] for i in ids)
        file = statistics.fmean(per_task[i][f"{name}_file"] for i in ids)
        print(f"  {name:7s} symbol {symbol:.4f}  file {file:.4f}  gap {file / symbol:.2f}x")
    for base in ("base", "cosine", "dense"):
        deltas = [per_task[i]["dense_symbol"] - per_task[i][f"{base}_symbol"] for i in ids]
        wins = sum(1 for d in deltas if d > 1e-9)
        losses = sum(1 for d in deltas if d < -1e-9)
        lo, hi = bootstrap_ci(deltas)
        print(f"  dense - {base:6s} {statistics.fmean(deltas):+.4f}  CI ({lo:+.3f},{hi:+.3f})  "
              f"W/L {wins}/{losses}  p={sign_test(wins, losses):.4f}")

    Path(args.out).write_text("\n".join(json.dumps({"instance_id": i, **per_task[i]}) for i in ids) + "\n",
                              encoding="utf-8")
    print(f"per-task -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
