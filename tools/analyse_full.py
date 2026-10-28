"""The headline claims, recomputed at whatever scale a features file holds.

The Lite study is 290 scored tasks out of 300; the full SWE-bench test split is
2,294. This script answers "was 300 enough" with the same code path the paper
already uses: file recall against symbol recall for one ranking, the graph arm
against BM25 at the same pool, and — when a results file is supplied — the
learned ranker with and without the evidence channels.

    python tools/analyse_full.py --rows data/features_full.jsonl \
        --results data/combo_ltr_full.jsonl

Both intervals are reported. The per-task bootstrap treats tasks as independent;
the cluster bootstrap resamples the twelve repositories, which is the honest unit
because tasks inside one repository share files and conventions.
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

from tools.analyse import bootstrap_ci, sign_test  # noqa: E402

K = 10
RESAMPLES = 4000
SEED = 20261029


def symbol_recall(order: list[int], labels: list[int], gold_total: int, k: int = K) -> float:
    """Share of the task's whole gold set inside the top k.

    The denominator is the task's gold total, never the positives that happen to
    be in the pool: gold outside the pool must count as a miss.
    """
    if not gold_total:
        return 0.0
    return sum(1 for index in order[:k] if labels[index]) / gold_total


def file_recall(order: list[int], files: list[str], gold_files: list[str], k: int = K) -> float:
    if not gold_files:
        return float("nan")
    seen: list[str] = []
    for index in order[:k]:
        path = files[index] if index < len(files) else ""
        if path and path not in seen:
            seen.append(path)
    return len(set(seen) & set(gold_files)) / len(set(gold_files))


def cluster_ci(by_repo: dict[str, list[float]]) -> tuple[float, float]:
    rng = random.Random(SEED)
    repos = list(by_repo)
    means = []
    for _ in range(RESAMPLES):
        picked = [rng.choice(repos) for _ in repos]
        means.append(statistics.fmean([v for repo in picked for v in by_repo[repo]]))
    means.sort()
    return means[int(0.025 * RESAMPLES)], means[int(0.975 * RESAMPLES) - 1]


def report(name: str, deltas: dict[str, float], repo_of: dict[str, str]) -> None:
    values = list(deltas.values())
    wins = sum(1 for v in values if v > 0)
    losses = sum(1 for v in values if v < 0)
    lo, hi = bootstrap_ci(values)
    by_repo: dict[str, list[float]] = defaultdict(list)
    for instance_id, delta in deltas.items():
        by_repo[repo_of.get(instance_id, "?")].append(delta)
    clo, chi = cluster_ci(by_repo)
    positives = sum(1 for group in by_repo.values() if statistics.fmean(group) > 0)
    print(f"{name:22s}{statistics.fmean(values):+8.3f}  CI ({lo:+.3f},{hi:+.3f})  "
          f"cluster ({clo:+.3f},{chi:+.3f})  W/L {wins}/{losses}  "
          f"p={sign_test(wins, losses):.4f}  repos+ {positives}/{len(by_repo)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
    ap.add_argument("--results", default=str(ROOT / "data" / "combo_ltr_full.jsonl"))
    ap.add_argument("--orders", default=str(ROOT / "data" / "combo_ltr_orders_full.jsonl"))
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    tasks = [task for task in tasks if task.get("labels")]
    repo_of = {task["instance_id"]: task["repo"] for task in tasks}
    print(f"tasks {len(tasks)}  repositories {len(set(repo_of.values()))}")

    symbol, files_of_ranking = {}, {}
    for task in tasks:
        labels, files = task["labels"], task["files"]
        total = task.get("gold_total") or sum(labels)
        if not total:
            continue
        instance_id = task["instance_id"]
        bm25_order = list(range(len(labels)))
        graph_order = task["rerank_top10"]
        symbol[instance_id] = {
            "bm25": symbol_recall(bm25_order, labels, total),
            "graph": symbol_recall(graph_order, labels, total),
        }
        files_of_ranking[instance_id] = {
            "bm25": file_recall(bm25_order, files, task.get("gold_files") or []),
            "graph": file_recall(graph_order, files, task.get("gold_files") or []),
        }

    print(f"\n{'ranking':12s}{'symbol r@10':>14s}{'file r@10':>12s}")
    for arm in ("bm25", "graph"):
        sym = statistics.fmean([v[arm] for v in symbol.values()])
        fil = [v[arm] for v in files_of_ranking.values() if v[arm] == v[arm]]
        print(f"{arm:12s}{sym:14.3f}{statistics.fmean(fil):12.3f}")
    sym = statistics.fmean([v["bm25"] for v in symbol.values()])
    fil = statistics.fmean([v["bm25"] for v in files_of_ranking.values() if v["bm25"] == v["bm25"]])
    print(f"\ngap {fil:.3f} / {sym:.3f} = {fil / sym:.2f}x")

    print("\n== paired, per task ==")
    report("graph - bm25 (symbol)", {k: v["graph"] - v["bm25"] for k, v in symbol.items()}, repo_of)
    report("graph - bm25 (file)",
           {k: v["graph"] - v["bm25"] for k, v in files_of_ranking.items()
            if v["graph"] == v["graph"] and v["bm25"] == v["bm25"]}, repo_of)

    results_path = Path(args.results)
    if not results_path.exists():
        print(f"\nno results file at {results_path}; skipped the learned arms")
        return 0

    results = {row["instance_id"]: row for row in
               (json.loads(line) for line in results_path.open(encoding="utf-8") if line.strip())}
    print(f"\n== learned arms ({len(results)} tasks) ==")
    for arm in ("ltr", "ltr_ev5"):
        for base in ("bm25",):
            deltas = {key: row[arm] - row[base] for key, row in results.items()
                      if key in symbol and arm in row and base in row}
            report(f"{arm} - {base}", deltas, repo_of)
    deltas = {key: row["ltr_ev5"] - row["ltr"] for key, row in results.items()
              if key in symbol and "ltr_ev5" in row}
    report("ltr_ev5 - ltr", deltas, repo_of)

    print(f"\n{'arm':12s}{'symbol r@10':>14s}")
    for arm in ("bm25", "ltr", "ltr_ev5"):
        print(f"{arm:12s}{statistics.fmean([row[arm] for row in results.values()]):14.3f}")

    orders_path = Path(args.orders)
    if not orders_path.exists():
        return 0
    files_of = {task["instance_id"]: task["files"] for task in tasks}
    gold_of = {task["instance_id"]: task.get("gold_files") or [] for task in tasks}
    by_arm: dict[str, list[float]] = defaultdict(list)
    for row in (json.loads(line) for line in orders_path.open(encoding="utf-8") if line.strip()):
        instance_id = row["instance_id"]
        if instance_id not in files_of:
            continue
        for arm, order in row["orders"].items():
            value = file_recall(order, files_of[instance_id], gold_of[instance_id])
            if value == value:
                by_arm[arm].append(value)
    print(f"\n{'arm':12s}{'file r@10':>14s}")
    for arm in ("bm25", "ltr", "ltr_ev5"):
        if arm in by_arm:
            print(f"{arm:12s}{statistics.fmean(by_arm[arm]):14.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
