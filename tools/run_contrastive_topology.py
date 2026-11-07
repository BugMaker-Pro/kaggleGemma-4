"""Contrastive topology denoising from real versus constrained-rewired edges.

An edge classifier is trained without repair labels: real-only edges are
positive, while edges introduced by degree/file-preserving rewiring are
negative. On unseen repositories it scores real seed-to-candidate edges and
promotes only candidates supported by high-confidence topology.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from experiments.graph_controls import SEEDS, adjacency, promote, reachable, rewire
from tools.analyse import sign_test

REPRESENTATIONS = ("metadata", "body", "dense")
MODEL_SEEDS = (0, 1, 2)
TOKEN = re.compile(r"[A-Za-z0-9]+")


def pieces(text):
    return set(part.lower() for part in TOKEN.findall(text.replace("_", " ")))


def jaccard(first, second):
    union = first | second
    return len(first & second) / len(union) if union else 0.0


def common_prefix(first, second):
    count = 0
    for left, right in zip(first.split("."), second.split(".")):
        if left != right:
            break
        count += 1
    return count / max(len(first.split(".")), len(second.split(".")), 1)


def edge_features(context, a, b):
    ids, files, orders = context["ids"], context["files"], context["orders"]
    ranks = {name: {candidate: rank / max(len(order) - 1, 1)
                    for rank, candidate in enumerate(order)} for name, order in orders.items()}
    features = [float(files[a] == files[b]), jaccard(pieces(files[a]), pieces(files[b])),
                jaccard(pieces(ids[a]), pieces(ids[b])), common_prefix(ids[a], ids[b]),
                abs(math.log1p(len(ids[a])) - math.log1p(len(ids[b])))]
    for name in REPRESENTATIONS:
        features.extend([ranks[name][a], ranks[name][b], abs(ranks[name][a] - ranks[name][b])])
    return features


def edge_examples(context):
    original = {tuple(edge) for edge in context["edges"]}
    positive, negative = set(), set()
    for seed in SEEDS:
        randomized, _ = rewire(original, context["files"], context["instance_id"], seed)
        randomized = set(randomized)
        positive.update(original - randomized)
        negative.update(randomized - original)
    return [(edge_features(context, *edge), 1) for edge in positive] + \
           [(edge_features(context, *edge), 0) for edge in negative]


def fit(examples, seed):
    import lightgbm as lgb
    x = np.asarray([features for features, _ in examples])
    y = np.asarray([label for _, label in examples])
    return lgb.train({"objective": "binary", "metric": "binary_logloss", "learning_rate": .05,
                      "num_leaves": 15, "min_data_in_leaf": 30, "feature_fraction": .9,
                      "verbose": -1, "seed": seed, "deterministic": True},
                     lgb.Dataset(x, label=y), num_boost_round=200)


def denoised_order(context, representation, models, threshold=.5, scored=False):
    order = context["orders"][representation]
    seeds, seed_set = order[:5], set(order[:5])
    candidates = {}
    for a, b in (tuple(edge) for edge in context["edges"]):
        if a in seed_set and b not in seed_set:
            candidate = b
        elif b in seed_set and a not in seed_set:
            candidate = a
        else:
            continue
        values = np.asarray([edge_features(context, a, b)])
        probability = statistics.fmean(float(model.predict(values)[0]) for model in models)
        candidates[candidate] = max(candidates.get(candidate, 0.0), probability)
    if scored:
        tail = order[5:]
        position = {candidate: rank for rank, candidate in enumerate(order)}
        tail.sort(key=lambda candidate: (-candidates.get(candidate, 0.0), position[candidate]))
        return (seeds + tail)[:10]
    marked = {candidate for candidate, probability in candidates.items() if probability >= threshold}
    return promote(order, marked)


def symbol(order, context):
    return sum(context["labels"][candidate] for candidate in order[:10]) / context["gold_total"]


def file_score(order, context):
    gold = set(context.get("gold_files") or [])
    files = {context["files"][candidate] for candidate in order[:10]}
    return len(files & gold) / len(gold) if gold else 0.0


def repo_interval(rows, arm, base, draws=10000, seed=20261107):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["repo"], []).append(row[arm + "_symbol"] - row[base + "_symbol"])
    names = sorted(grouped)
    rng = random.Random(seed)
    samples = []
    for _ in range(draws):
        chosen = rng.choices(names, k=len(names))
        samples.append(statistics.fmean(value for repo in chosen for value in grouped[repo]))
    samples.sort()
    return samples[int(.025 * (draws - 1))], samples[int(.975 * (draws - 1))]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=Path, default=ROOT / "data/graph_controls_context.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "data/contrastive_topology_scores.jsonl")
    args = parser.parse_args(argv)
    contexts = [json.loads(line) for line in args.context.open(encoding="utf-8") if line.strip()]
    repos = sorted({context["repo"] for context in contexts})
    half = set(repos[::2])
    output = []
    for train_repos, test_repos in ((half, set(repos) - half), (set(repos) - half, half)):
        examples = [example for context in contexts if context["repo"] in train_repos
                    for example in edge_examples(context)]
        models = [fit(examples, seed) for seed in MODEL_SEEDS]
        for context in contexts:
            if context["repo"] not in test_repos:
                continue
            for representation in REPRESENTATIONS:
                order = context["orders"][representation]
                real = promote(order, reachable(order, adjacency(tuple(edge) for edge in context["edges"])))
                rankings = {"base": order[:10], "real": real,
                            "denoised": denoised_order(context, representation, models),
                            "scored": denoised_order(context, representation, models, scored=True)}
                output.append({"instance_id": context["instance_id"], "repo": context["repo"],
                               "representation": representation,
                               **{f"{name}_top10": ranking for name, ranking in rankings.items()},
                               **{f"{name}_symbol": symbol(ranking, context)
                                  for name, ranking in rankings.items()},
                               **{f"{name}_file": file_score(ranking, context)
                                  for name, ranking in rankings.items()}})
    args.out.write_text("\n".join(json.dumps(row) for row in output) + "\n", encoding="utf-8")
    for representation in REPRESENTATIONS:
        rows = [row for row in output if row["representation"] == representation]
        print(f"\n{representation} n={len(rows)}")
        for arm in ("base", "real", "denoised", "scored"):
            print(f"  {arm:12s} symbol {statistics.fmean(row[arm + '_symbol'] for row in rows):.4f} "
                  f"file {statistics.fmean(row[arm + '_file'] for row in rows):.4f}")
        for arm, base in (("real", "base"), ("denoised", "base"), ("scored", "base"),
                          ("denoised", "real")):
            values = [row[arm + "_symbol"] - row[base + "_symbol"] for row in rows]
            wins = sum(value > 1e-9 for value in values)
            losses = sum(value < -1e-9 for value in values)
            interval = repo_interval(rows, arm, base)
            print(f"  {arm + ' - ' + base:18s} {statistics.fmean(values):+.4f} "
                  f"repo CI ({interval[0]:+.3f},{interval[1]:+.3f}) "
                  f"W/L {wins}/{losses} p={sign_test(wins, losses):.4f}")
    print(f"per-task -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
