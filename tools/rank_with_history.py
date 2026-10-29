"""Does the repository's fix history add anything the ranking cannot see?

Two questions, in order:

  1. on its own, how good is "the files that earlier similar fixes touched"?
     Reported as file recall@10, against BM25's 0.564, with the same denominator.
  2. added to the sixteen-feature ranker as three columns, does it improve
     symbol recall@10 over 0.361 — overall and in the buckets where the issue
     states nothing at all?

    python tools/rank_with_history.py --rows data/features_full.jsonl
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

HISTORY = ("hist_weight", "hist_rank", "hist_seen")
GUARD = 0


def bucket_of(task: dict) -> str:
    rows, labels = task["rows"], task["labels"]
    for index, label in enumerate(labels):
        if label and rows[index][3]:
            return "quotes"
    for index, label in enumerate(labels):
        if label and (rows[index][4] or rows[index][6] or rows[index][8]):
            return "names"
    return "neither"


def train(tasks, seed: int, columns=None):
    x = np.array([([row[i] for i in columns] if columns else row)
                  for task in tasks for row in task["rows"]])
    y = np.array([label for task in tasks for label in task["labels"]])
    group = [len(task["rows"]) for task in tasks]
    return lgb.train(
        {"objective": "lambdarank", "metric": "ndcg", "ndcg_eval_at": [10],
         "learning_rate": LEARNING_RATE, "num_leaves": 15, "min_data_in_leaf": 20,
         "verbose": -1, "seed": seed, "deterministic": True},
        lgb.Dataset(x, label=y, group=group), num_boost_round=ROUNDS,
    )


def file_recall(order, files, gold_files) -> float:
    if not gold_files:
        return float("nan")
    seen = []
    for index in order[:10]:
        path = files[index]
        if path and path not in seen:
            seen.append(path)
    return len(set(seen) & set(gold_files)) / len(set(gold_files))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
    ap.add_argument("--history", default=str(ROOT / "data" / "history_scores.jsonl"))
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    history = {row["instance_id"]: row for row in
               (json.loads(line) for line in Path(args.history).open(encoding="utf-8") if line.strip())}

    # 1. the history as a ranking of files, no learning
    history_file, bm25_file = [], []
    for task in tasks:
        record = history.get(task["instance_id"]) or {"files": {}, "seen": 0}
        weight = record["files"]
        gold_files = task.get("gold_files") or []
        if not gold_files:
            continue
        order = sorted(range(len(task["files"])),
                       key=lambda i: -weight.get(task["files"][i], 0.0))
        history_file.append(file_recall(order, task["files"], gold_files))
        bm25_file.append(file_recall(list(range(len(task["files"]))), task["files"], gold_files))
        task["_hist"] = weight
        task["_rank"] = {path: place for place, path in enumerate(
            [path for path in sorted(weight, key=lambda p: -weight[p])])}
        task["_seen"] = min(record["seen"], 25) / 25.0
    print(f"history alone, file r@10: {statistics.fmean(history_file):.3f}   "
          f"(BM25: {statistics.fmean(bm25_file):.3f})")

    # 2. as three columns on the ranker
    for task in tasks:
        weight = task.get("_hist", {})
        rank_map = task.get("_rank", {})
        seen = task.get("_seen", 0.0)
        for row, path in zip(task["rows"], task["files"]):
            row.extend([weight.get(path, 0.0),
                        1.0 / (1.0 + rank_map.get(path, 999)),
                        seen])
    extended = list(ORDER) + list(HISTORY)
    tasks = [task for task in tasks if task.get("labels")]

    repos = sorted({task["repo"] for task in tasks})
    half = set(repos[::2])
    folds = ((half, set(repos) - half), (set(repos) - half, half))

    base, full, base_bucket, full_bucket = {}, {}, {}, {}
    without_graph = {}
    graph_names = ("in_degree", "out_degree", "near_seed")
    columns_nograph = [i for i, name in enumerate(ORDER) if name not in graph_names] + \
                      [len(ORDER) + offset for offset in range(len(HISTORY))]
    for train_repos, test_repos in folds:
        tr = [task for task in tasks if task["repo"] in train_repos]
        te = [task for task in tasks if task["repo"] in test_repos]
        models_full = [train(tr, seed) for seed in SEEDS]
        models_base = [train(tr, seed, list(range(len(ORDER)))) for seed in SEEDS]
        models_nograph = [train(tr, seed, columns_nograph) for seed in SEEDS]
        for task in te:
            total = task.get("gold_total") or sum(task["labels"])
            z_full = np.array(task["rows"])
            z_base = np.array([row[: len(ORDER)] for row in task["rows"]])
            z_nograph = np.array([[row[i] for i in columns_nograph] for row in task["rows"]])
            for store, models, z in ((full, models_full, z_full),
                                     (base, models_base, z_base),
                                     (without_graph, models_nograph, z_nograph)):
                scores = np.mean([model.predict(z) for model in models], axis=0)
                order = order_from(list(scores), task["labels"])
                store[task["instance_id"]] = recall_all(order, task["labels"], total)
            key = bucket_of(task)
            base_bucket.setdefault(key, []).append(base[task["instance_id"]])
            full_bucket.setdefault(key, []).append(full[task["instance_id"]])

    print(f"\n16 features           {statistics.fmean(base.values()):.3f}")
    print(f"19, + fix history     {statistics.fmean(full.values()):.3f}")
    print(f"16, history, no graph {statistics.fmean(without_graph.values()):.3f}")
    graph_delta = [full[key] - without_graph[key] for key in sorted(full)]
    wins_g = sum(1 for value in graph_delta if value > 0)
    losses_g = sum(1 for value in graph_delta if value < 0)
    lo_g, hi_g = bootstrap_ci(graph_delta)
    print(f"graph features, with history present: {statistics.fmean(graph_delta):+.3f}  "
          f"CI ({lo_g:+.3f},{hi_g:+.3f})  W/L {wins_g}/{losses_g}  "
          f"p={sign_test(wins_g, losses_g):.4f}")
    keys = sorted(base)
    deltas = [full[key] - base[key] for key in keys]
    wins = sum(1 for value in deltas if value > 0)
    losses = sum(1 for value in deltas if value < 0)
    lo, hi = bootstrap_ci(deltas)
    print(f"delta {statistics.fmean(deltas):+.3f}  CI ({lo:+.3f},{hi:+.3f})  "
          f"W/L {wins}/{losses}  p={sign_test(wins, losses):.4f}")

    print(f"\n{'bucket':10s}{'n':>6s}{'16 feats':>10s}{'+ history':>11s}{'delta':>9s}")
    for key in ("quotes", "names", "neither"):
        if key not in base_bucket:
            continue
        print(f"{key:10s}{len(base_bucket[key]):6d}{statistics.fmean(base_bucket[key]):10.3f}"
              f"{statistics.fmean(full_bucket[key]):11.3f}"
              f"{statistics.fmean(full_bucket[key]) - statistics.fmean(base_bucket[key]):+9.3f}")

    # file-level: does the history help pick files, or only symbols inside them?
    orders = {row["instance_id"]: row for row in
              (json.loads(line) for line in (ROOT / "data" / "combo_ltr_orders_full.jsonl").open(encoding="utf-8") if line.strip())}
    score = []
    for task in tasks:
        record = orders.get(task["instance_id"])
        if record and task.get("gold_files"):
            score.append(file_recall(record["orders"]["ltr"], task["files"], task["gold_files"]))
    print(f"\nranker file r@10 (reference): {statistics.fmean(score):.3f}")

    # how much is left on the table: is the gold file absent from the pool, and
    # does the history point at it anyway? that is the case a reranker cannot fix
    absent = [task for task in tasks
              if task.get("gold_files")
              and not (set(task["gold_files"]) & {path for path in task["files"] if path})]
    hit = 0
    for task in absent:
        weight = task.get("_hist", {})
        ranked = sorted(weight, key=lambda path: -weight[path])[:10]
        if set(ranked) & set(task["gold_files"]):
            hit += 1
    print(f"gold file absent from the 200-candidate pool: {len(absent)} tasks; "
          f"history puts it in its top 10 for {hit} ({hit / max(len(absent), 1):.1%})")

    top1 = 0
    for task in tasks:
        if not task.get("gold_files"):
            continue
        weight = task.get("_hist", {})
        if not weight:
            continue
        best = max(weight, key=lambda path: weight[path])
        top1 += int(best in set(task["gold_files"]))
    print(f"history's single best file is a gold file: {top1} tasks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
