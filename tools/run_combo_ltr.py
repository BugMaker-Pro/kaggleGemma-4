"""Learn the ranking, then let the evidence channels override it.

The ranker reorders the pool and is bounded by it; the evidence channels can pull
a symbol the pool never ranked. This combines them: train the ranker exactly as
in `train_rank2.py` (repository split, three seeds), then prepend the candidates
whose body quotes the issue or whose line the traceback names.

All numbers are reported on the paper's scale: a task whose gold symbol is not in
the pool scores zero, so 0.275 is the BM25 reference and 0.352 the evidence arm.

    python tools/run_combo_ltr.py
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

ROUNDS = 300
LEARNING_RATE = 0.05
SEEDS = (0, 1, 2)
FEATURES_INDEX = {}

# feature order as written by tools/features.py
ORDER = ("bm25_score", "bm25_rank", "body_run", "body_line", "path_in_issue",
         "path_overlap", "frame_hit", "frame_file", "named_file", "in_degree",
         "out_degree", "near_seed", "file_best", "file_size", "span_lines",
         "doc_tokens")
IDX = {name: position for position, name in enumerate(ORDER)}


def train(tasks, seed: int):
    x = np.array([row for task in tasks for row in task["rows"]])
    y = np.array([label for task in tasks for label in task["labels"]])
    group = [len(task["rows"]) for task in tasks]
    return lgb.train(
        {"objective": "lambdarank", "metric": "ndcg", "ndcg_eval_at": [10],
         "learning_rate": LEARNING_RATE, "num_leaves": 15, "min_data_in_leaf": 20,
         "verbose": -1, "seed": seed, "deterministic": True},
        lgb.Dataset(x, label=y, group=group), num_boost_round=ROUNDS,
    )


def recall_all(order, labels, gold_total: int, k: int = 10) -> float:
    """Fraction of the task's *whole* gold set found in the top k.

    `labels` only covers pool candidates, so dividing by its sum would inflate
    every arm whenever a task has a gold symbol outside the pool.
    """
    if not gold_total:
        return 0.0
    return sum(1 for index in order[:k] if labels[index]) / gold_total


def order_from(scores, labels) -> list[int]:
    return sorted(range(len(scores)), key=lambda i: -scores[i])


def evidence_strength(row) -> float:
    return (2.0 * row[IDX["body_line"]] + 2.0 * row[IDX["frame_hit"]]
            + row[IDX["body_run"]] + 0.5 * row[IDX["named_file"]])


def prepend(order: list[int], rows, cap: int) -> list[int]:
    """Candidate indices sorted by evidence, up to `cap`, ahead of the learned order.

    `order` is a permutation of candidate indices; the evidence lookup must use
    the candidate index, not the position inside `order`.
    """
    strengths = [evidence_strength(row) for row in rows]
    ranked = sorted(range(len(rows)), key=lambda i: -strengths[i])
    head = [i for i in ranked[:cap] if strengths[i] >= 0.3]
    rest = [i for i in order if i not in set(head)]
    return head + rest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features.jsonl"))
    ap.add_argument("--gold", default=str(ROOT / "data" / "experiment_v3.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "data" / "combo_ltr.jsonl"))
    ap.add_argument("--orders-out", default=str(ROOT / "data" / "combo_ltr_orders.jsonl"))
    ap.add_argument("--skip-ablation", action="store_true")
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    gold_total = {row["instance_id"]: len(row.get("gold_nodes") or []) for row in
                  (json.loads(line) for line in Path(args.gold).open(encoding="utf-8") if line.strip())}
    # a features file carries its own gold count, which is what a full-benchmark run has
    for task in tasks:
        if task.get("gold_total"):
            gold_total.setdefault(task["instance_id"], task["gold_total"])
    features = tasks[0]["features"]
    assert tuple(features) == ORDER, features
    repos = sorted({task["repo"] for task in tasks})
    half = set(repos[::2])
    folds = ((half, set(repos) - half), (set(repos) - half, half))

    results: dict[str, dict[str, list[float]]] = {}
    orders: dict[str, dict] = {}
    for train_repos, test_repos in folds:
        train_tasks = [task for task in tasks if task["repo"] in train_repos]
        test_tasks = [task for task in tasks if task["repo"] in test_repos]
        models = [train(train_tasks, seed) for seed in SEEDS]

        for task in test_tasks:
            z = np.array(task["rows"])
            scores = np.mean([model.predict(z) for model in models], axis=0)
            labels = task["labels"]

            arms = {
                "bm25": [row[0] for row in task["rows"]],
                "ltr": list(scores),
                "ltr_ev5": None,
            }
            base_order = order_from(scores, labels)
            for name, cap in (("ltr_ev5", 5),):
                combined = prepend(base_order, task["rows"], cap)
                # encode a permutation as scores: candidate at position p scores -p
                values = [0.0] * len(combined)
                for position, candidate in enumerate(combined):
                    values[candidate] = -float(position)
                arms[name] = values

            orders[task["instance_id"]] = {
                "gold_total": gold_total.get(task["instance_id"], 0),
                "labels": labels,
                "orders": {name: order_from(values, labels) for name, values in arms.items()},
            }
            for name, values in arms.items():
                order = order_from(values, labels)
                results.setdefault(name, {}).setdefault(
                    task["instance_id"],
                    recall_all(order, labels, gold_total.get(task["instance_id"], 0)))

    print(f"tasks: {len(results['bm25'])}\n")
    print(f"{'arm':10s}{'r@10 (all tasks)':>18s}")
    for name in ("bm25", "ltr", "ltr_ev5"):
        values = list(results[name].values())
        print(f"{name:10s}{statistics.fmean(values):18.3f}")

    def paired(candidate: str, base: str) -> None:
        keys = sorted(results[candidate])
        deltas = [results[candidate][key] - results[base][key] for key in keys]
        wins = sum(1 for delta in deltas if delta > 0)
        losses = sum(1 for delta in deltas if delta < 0)
        lo, hi = bootstrap_ci(deltas)
        print(f"{candidate:10s} vs {base:8s} {statistics.fmean(deltas):+.3f}  "
              f"CI ({lo:+.3f},{hi:+.3f})  W/L {wins}/{losses}  p={sign_test(wins, losses):.4f}")

    print()
    paired("ltr", "bm25")
    paired("ltr_ev5", "ltr")
    paired("ltr_ev5", "bm25")

    out = Path(args.out)
    with out.open("w", encoding="utf-8") as fh:
        for instance_id in sorted(results["bm25"]):
            fh.write(json.dumps({
                "instance_id": instance_id,
                **{name: round(values[instance_id], 4) for name, values in results.items()},
            }) + "\n")
    print(f"\nper-task results -> {out}")

    # full curve data for the figure: store the ordering, not just r@10
    curve_out = Path(args.orders_out)
    with curve_out.open("w", encoding="utf-8") as fh:
        for instance_id, entry in orders.items():
            fh.write(json.dumps({
                "instance_id": instance_id,
                "gold_total": entry["gold_total"],
                "labels": entry["labels"],
                "orders": entry["orders"],
            }) + "\n")
    print(f"per-task orders -> {curve_out}")

    # ablation on the same scale: does the ranker need the graph features?
    if args.skip_ablation:
        return 0
    print("\n== ablation (all-task recall@10) ==")
    keep = [i for i, name in enumerate(ORDER)
            if name not in ("in_degree", "out_degree", "near_seed")]
    ablated: dict[str, float] = {}
    for train_repos, test_repos in folds:
        train_tasks = [task for task in tasks if task["repo"] in train_repos]
        test_tasks = [task for task in tasks if task["repo"] in test_repos]
        models = []
        for seed in SEEDS:
            x = np.array([[row[i] for i in keep] for task in train_tasks for row in task["rows"]])
            y = np.array([label for task in train_tasks for label in task["labels"]])
            group = [len(task["rows"]) for task in train_tasks]
            models.append(lgb.train(
                {"objective": "lambdarank", "metric": "ndcg", "ndcg_eval_at": [10],
                 "learning_rate": LEARNING_RATE, "num_leaves": 15, "min_data_in_leaf": 20,
                 "verbose": -1, "seed": seed, "deterministic": True},
                lgb.Dataset(x, label=y, group=group), num_boost_round=ROUNDS))
        for task in test_tasks:
            z = np.array([[row[i] for row in task["rows"]] for i in [0]] * 0)  # placeholder
            z = np.array([[row[i] for i in keep] for row in task["rows"]])
            scores = np.mean([model.predict(z) for model in models], axis=0)
            ablated[task["instance_id"]] = recall_all(
                order_from(scores, task["labels"]), task["labels"],
                gold_total.get(task["instance_id"], 0))

    keys = sorted(ablated)
    deltas = [results["ltr"][key] - ablated[key] for key in keys]
    wins = sum(1 for delta in deltas if delta > 0)
    losses = sum(1 for delta in deltas if delta < 0)
    lo, hi = bootstrap_ci(deltas)
    print(f"{'with graph':12s}{statistics.fmean(list(results['ltr'].values())):.3f}")
    print(f"{'without':12s}{statistics.fmean(list(ablated.values())):.3f}")
    print(f"graph features contribute {statistics.fmean(deltas):+.3f}  "
          f"CI ({lo:+.3f},{hi:+.3f})  W/L {wins}/{losses}  "
          f"p={sign_test(wins, losses):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
