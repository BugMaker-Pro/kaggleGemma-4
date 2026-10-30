"""How many tasks does a code-retrieval claim need?

The paper reports a 2.9-point rule that is significant on 290 tasks and worth
-0.002 on 2,232. That is not bad luck, it is what a 290-task comparison does:
this measures it. Every arm pairing has 2,232 paired per-task differences, so we
can resample subsets of size n, run the same test the paper runs, and count how
often it would have declared an effect.

Reported per (pair, n): the probability that a sign test reaches p < 0.05, and
the probability that a bootstrap interval excludes zero -- i.e. the actual power
of the comparison the literature usually reports.

    python tools/power_analysis.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from tools.analyse import bootstrap_ci, sign_test  # noqa: E402

SIZES = (100, 200, 290, 500, 800, 1200, 2232)
ROUNDS = 400
SEED = 12345


def recall(order: list[int], labels: list[int], total: int, k: int = 10) -> float:
    if not total:
        return 0.0
    return sum(1 for index in order[:k] if labels[index]) / total


def load() -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    features = {row["instance_id"]: row for row in
                (json.loads(line) for line in (ROOT / "data" / "features_full.jsonl").open(encoding="utf-8") if line.strip())}
    for row in (json.loads(line) for line in (ROOT / "data" / "combo_ltr_orders_full.jsonl").open(encoding="utf-8") if line.strip()):
        instance_id = row["instance_id"]
        total = row["gold_total"] or 0
        labels = row["labels"]
        arms = dict(row["orders"])
        extra = features.get(instance_id, {}).get("rerank_top10")
        if extra is not None:
            arms["graph"] = extra
        out[instance_id] = {name: recall(order, labels, total)
                            for name, order in arms.items()}
    return out


def main(argv=None) -> int:
    per_task = load()
    ids = sorted(per_task)
    pairs = (("ltr", "bm25"), ("ltr_ev5", "ltr"), ("graph", "bm25"))
    rng = np.random.default_rng(SEED)

    print(f"tasks {len(ids)}; {ROUNDS} resamples per cell\n")
    header = f"{'pair':16s}" + "".join(f"{size:>8d}" for size in SIZES)
    print(header)
    print("-" * len(header))
    rows: dict[str, dict[int, float]] = {}
    for candidate, base in pairs:
        if candidate not in per_task[ids[0]]:
            continue
        deltas = np.array([per_task[i][candidate] - per_task[i][base] for i in ids])
        full = statistics.fmean(deltas)
        line = f"{candidate + ' vs ' + base:16s}"
        rows[f"{candidate}-{base}"] = {}
        for size in SIZES:
            hits = 0
            for _ in range(ROUNDS):
                picked = rng.choice(len(deltas), size=min(size, len(deltas)), replace=False)
                sample = deltas[picked]
                wins = int((sample > 1e-9).sum())
                losses = int((sample < -1e-9).sum())
                if wins + losses == 0:
                    continue
                if sign_test(wins, losses) < 0.05:
                    hits += 1
            power = hits / ROUNDS
            rows[f"{candidate}-{base}"][size] = power
            line += f"{power:8.2f}"
        print(line + f"   (full-scale delta {full:+.4f})")

    print("\nreading: the share of 2,000-task resamples whose sign test would have")
    print("called the effect significant at that sample size.")
    out = ROOT / "data" / "power_analysis.json"
    out.write_text(json.dumps({"rounds": ROUNDS, "sizes": SIZES,
                               "power": {key: {str(k): v for k, v in value.items()}
                                         for key, value in rows.items()}}, indent=2) + "\n",
                   encoding="utf-8")
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
