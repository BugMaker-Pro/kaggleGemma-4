"""The whole stack: cheap features, the fix-history prior, and the model score.

Each block was measured on its own; this measures them together, which is the
only number that answers "what is the best we can do with what we have". Same
folds, same seeds, same denominator as every other arm in the paper.

    python tools/rank_full_stack.py
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
from tools.history_freq import build, pr_number  # noqa: E402
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
        lgb.Dataset(x, label=y, group=group), num_boost_round=ROUNDS,
    )


def bucket_of(task):
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
    ap.add_argument("--model", default=str(ROOT / "data" / "rerank_full_1024.jsonl"))
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_full.jsonl"))
    args = ap.parse_args(argv)

    from experiments.retrieve import tokenize  # noqa: PLC0415
    from tools.history_features import BM25, patch_files  # noqa: PLC0415
    raw = [json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip()]
    for task in raw:
        task["_files"] = patch_files(task.get("patch") or "")
        task["_text"] = set(tokenize(task.get("problem_statement") or ""))
        task["_pr"] = pr_number(task["instance_id"])
        task["_repo"] = task["repo"]
    raw = [task for task in raw if task["_files"]]
    by_repo: dict[str, list[dict]] = {}
    for task in raw:
        by_repo.setdefault(task["repo"], []).append(task)
    history = {}
    for group in by_repo.values():
        history.update(build(group, BM25([task["_text"] for task in group])))

    model = {row["instance_id"]: row for row in
             (json.loads(line) for line in Path(args.model).open(encoding="utf-8") if line.strip())}
    tasks = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]

    kept = []
    for task in tasks:
        record = model.get(task["instance_id"])
        if not record or not task.get("labels"):
            continue
        scores = [0.0] * len(task["rows"])
        for position, index in enumerate(record["candidates"]):
            scores[index] = float(record["scores"][position])
        low, high = min(scores), max(scores)
        spread = (high - low) or 1.0
        hist = history.get(task["instance_id"], {"sim": {}, "freq": {}, "recent": {}})
        freq, recent = hist["freq"], hist["recent"]
        for row, raw_score, path in zip(task["rows"], scores, task["files"]):
            row.extend([(raw_score - low) / spread, freq.get(path, 0.0), recent.get(path, 0.0)])
        kept.append(task)
    tasks = kept

    base = list(range(len(ORDER)))
    graph_names = ("in_degree", "out_degree", "near_seed")
    nograph = [i for i, name in enumerate(ORDER) if name not in graph_names]
    model_col = len(ORDER)
    freq_col, recent_col = len(ORDER) + 1, len(ORDER) + 2
    configs = {
        "16 features": base,
        "+ model": base + [model_col],
        "+ prior": base + [freq_col, recent_col],
        "+ model + prior": base + [model_col, freq_col, recent_col],
        "no graph, all else": nograph + [model_col, freq_col, recent_col],
    }

    repos = sorted({task["repo"] for task in tasks})
    half = set(repos[::2])
    folds = ((half, set(repos) - half), (set(repos) - half, half))
    scores = {name: {} for name in configs}
    file_scores = {name: [] for name in configs}
    groups: dict[str, list[str]] = {}
    for train_repos, test_repos in folds:
        tr = [task for task in tasks if task["repo"] in train_repos]
        te = [task for task in tasks if task["repo"] in test_repos]
        models = {name: [train(tr, seed, columns) for seed in SEEDS]
                  for name, columns in configs.items()}
        for task in te:
            total = task.get("gold_total") or sum(task["labels"])
            gold_files = task.get("gold_files") or []
            for name, columns in configs.items():
                z = np.array([[row[i] for i in columns] for row in task["rows"]])
                prediction = np.mean([model.predict(z) for model in models[name]], axis=0)
                order = order_from(list(prediction), task["labels"])
                scores[name][" " + task["instance_id"]] = recall_all(order, task["labels"], total)
                if gold_files:
                    seen = []
                    for index in order[:10]:
                        path = task["files"][index]
                        if path and path not in seen:
                            seen.append(path)
                    file_scores[name].append(len(set(seen) & set(gold_files)) / len(set(gold_files)))
            groups.setdefault(bucket_of(task), []).append(" " + task["instance_id"])

    print(f"{'config':22s}{'symbol r@10':>13s}{'file r@10':>12s}")
    for name in configs:
        print(f"{name:22s}{statistics.fmean(scores[name].values()):13.3f}"
              f"{statistics.fmean(file_scores[name]):12.3f}")
    keys = sorted(scores["16 features"])
    for name in list(configs)[1:]:
        deltas = [scores[name][key] - scores["16 features"][key] for key in keys]
        wins = sum(1 for value in deltas if value > 0)
        losses = sum(1 for value in deltas if value < 0)
        lo, hi = bootstrap_ci(deltas)
        print(f"{name + ' vs 16':22s}{statistics.fmean(deltas):+8.3f}  CI ({lo:+.3f},{hi:+.3f})  "
              f"W/L {wins}/{losses}  p={sign_test(wins, losses):.4f}")

    best = max(configs, key=lambda name: statistics.fmean(scores[name].values()))
    print(f"\n{'bucket':10s}{'n':>6s}" + "".join(f"{name:>10s}" for name in ("16 features", best)))
    for name in ("quotes", "names", "neither"):
        ids = groups.get(name, [])
        if not ids:
            continue
        print(f"{name:10s}{len(ids):6d}"
              f"{statistics.fmean(scores['16 features'][key] for key in ids):10.3f}"
              f"{statistics.fmean(scores[best][key] for key in ids):10.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
