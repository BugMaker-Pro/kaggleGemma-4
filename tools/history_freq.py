"""Is the fix-history gain really about *similar* past issues?

The user's objection is the sharpest one available: the nearest past issue is
unlikely to be about this issue's subsystem, so what looks like "the repository
remembers where similar fixes went" might be nothing more than "these files get
changed a lot". Both predict a positive feature; only one supports the story.

Three priors are separable, all from the same past patches:

  sim     weighted by BM25 similarity to the issue, x recency          (the claim)
  freq    how many past fixes touched the file, similarity ignored    (popularity)
  recent  only the last fifty past fixes, no similarity              (activity)

If `sim` beats `freq`, similarity is doing work. If they tie, the honest name for
the feature is file popularity, and the paper must say so.

Also reported: the `sim` gain split by how similar the nearest past issue
actually is. A mechanism that needs similar issues should pay more where they
exist.

    python tools/history_freq.py --rows data/features_full.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import lightgbm as lgb  # noqa: E402
import numpy as np  # noqa: E402

from tools.analyse import bootstrap_ci, sign_test  # noqa: E402
from tools.run_combo_ltr import (LEARNING_RATE, ORDER, ROUNDS, SEEDS,  # noqa: E402
                                 order_from, recall_all)

TOP_K = 25
MIN_SIM = 0.08
RECENCY = 0.00004
RECENT_WINDOW = 50


def pr_number(instance_id: str) -> int:
    try:
        return int(instance_id.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return 0


def build(tasks: list[dict], index) -> dict[str, dict]:
    """Three views of the same past, per task."""
    out: dict[str, dict] = {}
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for task in tasks:
        by_repo[task["_repo"]].append(task)
    for group in by_repo.values():
        group.sort(key=lambda task: task["_pr"])
        for position, task in enumerate(group):
            past = group[:position]
            sim: dict[str, float] = defaultdict(float)
            freq: dict[str, float] = defaultdict(float)
            recent: dict[str, float] = defaultdict(float)
            best_similarity = 0.0
            if past and task["_text"]:
                scores = sorted(((index.score(task["_text"], i), past[i])
                                 for i in range(len(past))), key=lambda pair: -pair[0])
                head = scores[:TOP_K]
                best = head[0][0] if head else 0.0
                best_similarity = best
                for value, other in head:
                    if best <= 0:
                        continue
                    similarity = value / best
                    if similarity < MIN_SIM:
                        continue
                    decay = math.exp(-RECENCY * (task["_pr"] - other["_pr"]))
                    for path in other["_files"]:
                        sim[path] += similarity * similarity * decay
                for other in past:
                    gap = task["_pr"] - other["_pr"]
                    for path in other["_files"]:
                        freq[path] += 1.0
                        if gap <= RECENT_WINDOW * 20:
                            recent[path] += math.exp(-RECENCY * gap)
            out[task["instance_id"]] = {
                "sim": _normalise(sim), "freq": _normalise(freq),
                "recent": _normalise(recent), "best": best_similarity,
            }
    return out


def _normalise(weights: dict[str, float]) -> dict[str, float]:
    if not weights:
        return {}
    peak = max(weights.values())
    return {path: value / peak for path, value in weights.items()}


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


def add_columns(tasks, history) -> list[str]:
    """Append sim/freq/recent weights + ranks as columns; return their names."""
    for task in tasks:
        record = history.get(task["instance_id"], {"sim": {}, "freq": {}, "recent": {}})
        sim, freq, recent = record["sim"], record["freq"], record["recent"]
        sim_rank = {path: place for place, path in enumerate(sorted(sim, key=lambda p: -sim[p]))}
        for row, path in zip(task["rows"], task["files"]):
            row.extend([sim.get(path, 0.0),
                        1.0 / (1.0 + sim_rank.get(path, 999)),
                        freq.get(path, 0.0),
                        recent.get(path, 0.0)])
    return ["h_sim", "h_rank", "h_freq", "h_recent"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
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
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for task in raw:
        by_repo[task["repo"]].append(task)
    history: dict[str, dict] = {}
    for group in by_repo.values():
        history.update(build(group, BM25([task["_text"] for task in group])))

    tasks = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    tasks = [task for task in tasks if task.get("labels")]
    names = add_columns(tasks, history)
    base_len = len(ORDER)
    configs = {
        "16 base": list(range(base_len)),
        "+ sim": list(range(base_len)) + [base_len + 0, base_len + 1],
        "+ freq": list(range(base_len)) + [base_len + 2],
        "+ recent": list(range(base_len)) + [base_len + 3],
        "+ all four": list(range(base_len + len(names))),
    }

    repos = sorted({task["repo"] for task in tasks})
    half = set(repos[::2])
    folds = ((half, set(repos) - half), (set(repos) - half, half))
    scores: dict[str, dict[str, float]] = {name: {} for name in configs}
    best_similarity = {task["instance_id"]: history.get(
        task["instance_id"], {}).get("best", 0.0) for task in tasks}

    for train_repos, test_repos in folds:
        tr = [task for task in tasks if task["repo"] in train_repos]
        te = [task for task in tasks if task["repo"] in test_repos]
        models = {name: [train(tr, seed, columns) for seed in SEEDS]
                  for name, columns in configs.items()}
        for task in te:
            total = task.get("gold_total") or sum(task["labels"])
            for name, columns in configs.items():
                z = np.array([[row[i] for i in columns] for row in task["rows"]])
                prediction = np.mean([model.predict(z) for model in models[name]], axis=0)
                order = order_from(list(prediction), task["labels"])
                scores[name][task["instance_id"]] = recall_all(order, task["labels"], total)
            print(f"  {train_repos and len(train_repos)} repos done", flush=True) if False else None

    print(f"{'config':14s}{'symbol r@10':>13s}")
    for name in configs:
        print(f"{name:14s}{statistics.fmean(scores[name].values()):13.3f}")

    keys = sorted(scores["16 base"])
    print(f"\n{'comparison':22s}{'delta':>8s}{'95% CI':>20s}{'W/L':>12s}{'p':>9s}")
    for name in ("+ sim", "+ freq", "+ recent", "+ all four"):
        deltas = [scores[name][key] - scores["16 base"][key] for key in keys]
        wins = sum(1 for value in deltas if value > 0)
        losses = sum(1 for value in deltas if value < 0)
        lo, hi = bootstrap_ci(deltas)
        print(f"{name:22s}{statistics.fmean(deltas):+8.3f}   ({lo:+.3f},{hi:+.3f})   "
              f"{wins:4d}/{losses:<4d}   {sign_test(wins, losses):.4f}")

    deltas = [scores["+ sim"][key] - scores["+ freq"][key] for key in keys]
    wins = sum(1 for value in deltas if value > 0)
    losses = sum(1 for value in deltas if value < 0)
    lo, hi = bootstrap_ci(deltas)
    print(f"{'sim - freq':22s}{statistics.fmean(deltas):+8.3f}   ({lo:+.3f},{hi:+.3f})   "
          f"{wins:4d}/{losses:<4d}   {sign_test(wins, losses):.4f}")

    order = sorted(keys, key=lambda key: best_similarity[key])
    terciles = [order[: len(order) // 3], order[len(order) // 3: 2 * len(order) // 3],
                order[2 * len(order) // 3:]]
    print(f"\n{'nearest past issue':22s}{'n':>6s}{'best sim':>10s}{'sim gain':>10s}{'freq gain':>10s}")
    labels = ("dissimilar third", "middle third", "most similar third")
    for label, group in zip(labels, terciles):
        sim_gain = statistics.fmean(scores["+ sim"][key] - scores["16 base"][key] for key in group)
        freq_gain = statistics.fmean(scores["+ freq"][key] - scores["16 base"][key] for key in group)
        print(f"{label:22s}{len(group):6d}"
              f"{statistics.fmean(best_similarity[key] for key in group):10.2f}"
              f"{sim_gain:>+10.3f}{freq_gain:>+10.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
