"""The combination the paper never ran: sixteen features + dense + cross-encoder.

`rank_with_dense.py` showed a frozen bi-encoder score adds +8.6 points on top of
the sixteen features (0.361 -> 0.447). `rank_full_stack.py` added the
cross-encoder and the fix-history prior but never the dense score. This script
puts all three expensive signals into the same LightGBM ranker, on the same
repository-held-out folds, seeds, and hyperparameters as every other arm, so the
result is directly comparable with the paper's Table 2.

    python tools/rank_with_dense_model.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from tools.analyse import bootstrap_ci, sign_test  # noqa: E402
from tools.rank_with_dense import train, file_recall  # noqa: E402
from tools.run_combo_ltr import ORDER, SEEDS, order_from, recall_all  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
    ap.add_argument("--embed", default=str(ROOT / "data" / "embed_retrieval.jsonl"))
    ap.add_argument("--model", default=str(ROOT / "data" / "rerank_full_1024.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "data" / "dense_model_scores.jsonl"))
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    embed = {row["instance_id"]: row for row in
             (json.loads(line) for line in Path(args.embed).open(encoding="utf-8") if line.strip())}
    model = {row["instance_id"]: row for row in
             (json.loads(line) for line in Path(args.model).open(encoding="utf-8") if line.strip())}
    assert tuple(tasks[0]["features"]) == ORDER

    kept = []
    for task in tasks:
        dense_row = embed.get(task["instance_id"])
        model_row = model.get(task["instance_id"])
        if dense_row is None or model_row is None or not task.get("labels"):
            continue
        cosine = [0.0] * len(task["rows"])
        for rank, index in enumerate(dense_row["candidates"]):
            cosine[index] = dense_row["scores"][rank]
        cross = [0.0] * len(task["rows"])
        for rank, index in enumerate(model_row["candidates"]):
            cross[index] = float(model_row["scores"][rank])
        low, high = min(cross), max(cross)
        spread = (high - low) or 1.0
        task["rows"] = [list(observation) + [cosine[i], (cross[i] - low) / spread]
                        for i, observation in enumerate(task["rows"])]
        task["cosine"] = cosine
        kept.append(task)
    print(f"tasks with dense + cross-encoder scores: {len(kept)}/{len(tasks)}")

    base_columns = list(range(len(ORDER)))
    dense_col, model_col = len(ORDER), len(ORDER) + 1
    configs = {
        "base": base_columns,
        "dense": base_columns + [dense_col],
        "model": base_columns + [model_col],
        "dense+model": base_columns + [dense_col, model_col],
    }
    repos = sorted({task["repo"] for task in kept})
    half = set(repos[::2])
    folds = ((half, set(repos) - half), (set(repos) - half, half))

    per_task: dict[str, dict[str, float]] = {}
    for train_repos, test_repos in folds:
        train_tasks = [task for task in kept if task["repo"] in train_repos]
        test_tasks = [task for task in kept if task["repo"] in test_repos]
        models = {name: [train(train_tasks, seed, columns) for seed in SEEDS]
                  for name, columns in configs.items()}
        for task in test_tasks:
            predictions = {
                name: np.mean([m.predict(np.array([[row[i] for i in columns]
                                                   for row in task["rows"]]))
                               for m in models[name]], axis=0)
                for name, columns in configs.items()
            }
            total = task.get("gold_total") or 0
            orders = {name: order_from(list(value), task["labels"])
                      for name, value in predictions.items()}
            per_task[task["instance_id"]] = {
                f"{name}_symbol": recall_all(orders[name], task["labels"], total)
                for name in configs
            }
            per_task[task["instance_id"]].update({
                f"{name}_file": file_recall(orders[name], task["files"],
                                            task.get("gold_files") or [])
                for name in configs
            })

    ids = sorted(per_task)
    print(f"tasks {len(ids)}")
    for name in configs:
        symbol = statistics.fmean(per_task[i][f"{name}_symbol"] for i in ids)
        file = statistics.fmean(per_task[i][f"{name}_file"] for i in ids)
        print(f"  {name:12s} symbol {symbol:.4f}  file {file:.4f}")
    # the paper's arm is "dense" (0.447); the new candidate is "dense+model"
    for challenger in ("model", "dense+model"):
        deltas = [per_task[i][f"{challenger}_symbol"] - per_task[i]["dense_symbol"] for i in ids]
        wins = sum(1 for d in deltas if d > 1e-9)
        losses = sum(1 for d in deltas if d < -1e-9)
        lo, hi = bootstrap_ci(deltas)
        print(f"  {challenger:12s} - dense {statistics.fmean(deltas):+.4f}  "
              f"CI ({lo:+.3f},{hi:+.3f})  W/L {wins}/{losses}  p={sign_test(wins, losses):.4f}")

    Path(args.out).write_text(
        "\n".join(json.dumps({"instance_id": i, **per_task[i]}) for i in ids) + "\n",
        encoding="utf-8")
    print(f"per-task -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
