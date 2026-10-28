"""Is 290 tasks enough? Two intervals for the same effect.

Tasks inside a repository share files, conventions and ranking noise, so treating
290 tasks as 290 independent draws overstates precision. This reports the naive
per-task bootstrap next to a cluster bootstrap that resamples repositories.

    python tools/cluster_boot.py
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

RESAMPLES = 4000
SEED = 20261029


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(ROOT / "data" / "combo_ltr.jsonl"))
    ap.add_argument("--features", default=str(ROOT / "data" / "features.jsonl"))
    args = ap.parse_args(argv)

    repo_of = {}
    for line in Path(args.features).open(encoding="utf-8"):
        if line.strip():
            row = json.loads(line)
            repo_of[row["instance_id"]] = row["repo"]
    rows = [json.loads(line) for line in Path(args.results).open(encoding="utf-8") if line.strip()]

    deltas = {row["instance_id"]: row["ltr_ev5"] - row["bm25"] for row in rows}
    by_repo: dict[str, list[float]] = defaultdict(list)
    for instance_id, delta in deltas.items():
        by_repo[repo_of[instance_id]].append(delta)

    print(f"tasks {len(deltas)}  repositories {len(by_repo)}")
    print(f"{'repository':26s}{'n':>4s}{'mean delta':>12s}")
    for repo, values in sorted(by_repo.items(), key=lambda kv: -len(kv[1])):
        print(f"{repo:26s}{len(values):4d}{statistics.fmean(values):+12.3f}")

    values = list(deltas.values())
    wins = sum(1 for value in values if value > 0)
    losses = sum(1 for value in values if value < 0)
    lo, hi = bootstrap_ci(values)
    print(f"\nper-task:  {statistics.fmean(values):+.3f}  CI ({lo:+.3f},{hi:+.3f})  "
          f"W/L {wins}/{losses}  p={sign_test(wins, losses):.4f}")

    rng = random.Random(SEED)
    repos = list(by_repo)
    means = []
    for _ in range(RESAMPLES):
        picked = [rng.choice(repos) for _ in repos]
        pooled = [value for repo in picked for value in by_repo[repo]]
        means.append(statistics.fmean(pooled))
    means.sort()
    lower = means[int(0.025 * RESAMPLES)]
    upper = means[int(0.975 * RESAMPLES) - 1]
    print(f"cluster:   {statistics.fmean(means):+.3f}  CI ({lower:+.3f},{upper:+.3f})  "
          f"over {len(repos)} repositories")

    positives = sum(1 for repo, group in by_repo.items() if statistics.fmean(group) > 0)
    print(f"\n{positives} of {len(repos)} repositories improve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
