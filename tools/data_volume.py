"""Is the evidence override worth less because there is more data, or is it wrong?

The 2,232-task run says the hand-written override adds nothing over the learned
ranker, where at 290 tasks it added 2.9 points. Two explanations fit:

  H1  the rule was a substitute for training data, and more data retired it
  H2  the rule encodes real information, but hard-wiring five slots is the wrong
      mechanism once the model already ranks those candidates well

They are separable on one fixed test set. H1 predicts that the override's gain
falls monotonically as the ranker is trained on more tasks; H2 predicts that a
*guarded* override — prepend only what the model itself failed to rank in its top
ten — keeps a gain at every size, because it defers to the model instead of
overruling it.

This trains the same 16-feature lambdarank on 5%, 10%, 25%, 50% and 100% of the
training repositories, evaluates every model on the same held-out repositories,
and reports four arms:

  bm25        no learning (constant across sizes)
  ltr         the ranker
  ltr_ev5     ranker + the paper's override (prepend up to 5, evidence >= 0.3)
  ltr_guard   ranker + the guarded override (only candidates outside the top 10)

    python tools/data_volume.py --rows data/features_full.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
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
                                 evidence_strength, order_from, recall_all)

GUARD_CUTOFF = 10
GUARD_CAP = 5
EVIDENCE = ("body_line", "body_run", "frame_hit", "named_file")


def train(tasks, seed: int, columns: list[int] | None = None):
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


def prepend(order: list[int], rows, cap: int, cutoff: int = 0) -> list[int]:
    """Evidence-first order, optionally only for candidates the model placed late."""
    strengths = [evidence_strength(row) for row in rows]
    position = {candidate: index for index, candidate in enumerate(order)}
    ranked = sorted(range(len(rows)), key=lambda i: -strengths[i])
    head = [i for i in ranked[: cap * 4]
            if strengths[i] >= 0.3 and position.get(i, 0) >= cutoff][:cap]
    head_set = set(head)
    return head + [candidate for candidate in order if candidate not in head_set]


def values_of(order: list[int], size: int) -> list[float]:
    values = [0.0] * size
    for position, candidate in enumerate(order):
        values[candidate] = -float(position)
    return values


def has_quote(task: dict) -> bool:
    return any(label and task["rows"][index][3]
               for index, label in enumerate(task["labels"]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
    ap.add_argument("--fractions", default="0.05,0.10,0.25,0.50,1.00")
    args = ap.parse_args(argv)
    fractions = [float(value) for value in args.fractions.split(",")]

    tasks = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    gold = {task["instance_id"]: task.get("gold_total") or sum(task["labels"]) for task in tasks}
    repos = sorted({task["repo"] for task in tasks})
    half = set(repos[::2])
    folds = ((half, set(repos) - half), (set(repos) - half, half))

    arms = ("bm25", "ltr", "ltr_ev5", "ltr_guard")
    scores: dict[tuple[float, str], dict[str, float]] = {
        (fraction, arm): {} for fraction in fractions for arm in arms}

    for train_repos, test_repos in folds:
        train_tasks = [task for task in tasks if task["repo"] in train_repos]
        test_tasks = [task for task in tasks if task["repo"] in test_repos]
        print(f"train {len(train_repos)} repos / {len(train_tasks)} tasks  "
              f"test {len(test_repos)} repos / {len(test_tasks)} tasks", flush=True)
        for fraction in fractions:
            for seed in SEEDS:
                rng = random.Random(seed * 1000 + int(fraction * 100))
                sample = (train_tasks if fraction >= 1.0 else
                          rng.sample(train_tasks, max(int(len(train_tasks) * fraction), 20)))
                model = train(sample, seed)
                for task in test_tasks:
                    model_scores = list(model.predict(np.array(task["rows"])))
                    base = order_from(model_scores, task["labels"])
                    plain = prepend(base, task["rows"], GUARD_CAP, cutoff=0)
                    guard = prepend(base, task["rows"], GUARD_CAP, cutoff=GUARD_CUTOFF)
                    per_arm = {
                        "bm25": [row[0] for row in task["rows"]],
                        "ltr": model_scores,
                        "ltr_ev5": values_of(plain, len(task["rows"])),
                        "ltr_guard": values_of(guard, len(task["rows"])),
                    }
                    for arm, values in per_arm.items():
                        order = order_from(values, task["labels"])
                        key = (fraction, arm)
                        scores[key][task["instance_id"]] = recall_all(
                            order, task["labels"], gold[task["instance_id"]])
            print(f"  {fraction:5.0%}  ltr {statistics.fmean(scores[(fraction, 'ltr')].values()):.3f}"
                  f"  ev5 {statistics.fmean(scores[(fraction, 'ltr_ev5')].values()):.3f}"
                  f"  guard {statistics.fmean(scores[(fraction, 'ltr_guard')].values()):.3f}",
                  flush=True)

    print(f"\n{'training tasks':16s}" + "".join(f"{arm:>11s}" for arm in arms)
          + f"{'ev5-ltr':>10s}{'guard-ltr':>11s}{'guard-ev5':>11s}")
    for fraction in fractions:
        size = int(len(tasks) * 0.5 * fraction)
        row = f"{size:>10d} {fraction:4.0%}"
        for arm in arms:
            row += f"{statistics.fmean(scores[(fraction, arm)].values()):>11.3f}"
        keys = sorted(scores[(fraction, "ltr")])
        for left, right in (("ltr_ev5", "ltr"), ("ltr_guard", "ltr"), ("ltr_guard", "ltr_ev5")):
            deltas = [scores[(fraction, left)][key] - scores[(fraction, right)][key] for key in keys]
            row += f"{statistics.fmean(deltas):>+10.3f}" if left == "ltr_ev5" \
                else f"{statistics.fmean(deltas):>+11.3f}"
        print(row, flush=True)

    full = fractions[-1]
    keys = sorted(scores[(full, "ltr_guard")])
    deltas = [scores[(full, "ltr_guard")][key] - scores[(full, "ltr_ev5")][key] for key in keys]
    wins = sum(1 for value in deltas if value > 0)
    losses = sum(1 for value in deltas if value < 0)
    lo, hi = bootstrap_ci(deltas)
    print(f"\nguard - ev5 at full training: {statistics.fmean(deltas):+.3f}  "
          f"CI ({lo:+.3f},{hi:+.3f})  W/L {wins}/{losses}  p={sign_test(wins, losses):.4f}")

    print("\n== is the information in the features? drop the four evidence columns ==")
    keep = [i for i, name in enumerate(ORDER) if name not in EVIDENCE]
    quoting, other = [], []
    for train_repos, test_repos in folds:
        train_tasks = [task for task in tasks if task["repo"] in train_repos]
        test_tasks = [task for task in tasks if task["repo"] in test_repos]
        models = [train(train_tasks, seed, keep) for seed in SEEDS]
        for task in test_tasks:
            z = np.array([[row[i] for i in keep] for row in task["rows"]])
            model_scores = np.mean([model.predict(z) for model in models], axis=0)
            order = order_from(list(model_scores), task["labels"])
            value = recall_all(order, task["labels"], gold[task["instance_id"]])
            (quoting if has_quote(task) else other).append(value)
    print(f"all tasks:   {statistics.fmean(quoting + other):.3f}   (with the columns: 0.361)")
    print(f"quoting:     {statistics.fmean(quoting):.3f}   (with the columns: 0.755)")
    print(f"not quoting: {statistics.fmean(other):.3f}   (with the columns: "
          f"{statistics.fmean([v for v in other]):.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
