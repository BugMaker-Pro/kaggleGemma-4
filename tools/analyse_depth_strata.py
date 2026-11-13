"""Where does the topology signal live? Stratify by distance from the seeds.

The primary experiment reports a +2.14-point real-minus-rewired effect under the
metadata ranking, but not where it comes from. This splits tasks by whether the
gold symbol sits within one hop of a BM25 top-five seed (the `near_seed` feature
already stored in `features_full.jsonl`) and re-scores the stored per-task arm
outputs from `data/graph_controls.jsonl`. No graph is rebuilt and no arm is
rerun: this is a re-slicing of frozen outputs.

Tasks with exactly one gold symbol, in the pool and in total, give a clean 0/1
per-task recall so the stratum label is unambiguous.

    python tools/analyse_depth_strata.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.analyse import bootstrap_ci, sign_test  # noqa: E402
from tools.run_combo_ltr import ORDER  # noqa: E402

REWIRE_SEEDS = (11, 23, 37, 51, 71)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--controls", default=str(ROOT / "data" / "graph_controls.jsonl"))
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
    args = ap.parse_args(argv)

    near_idx = ORDER.index("near_seed")
    gold_near: dict[str, bool] = {}
    for line in Path(args.rows).open(encoding="utf-8"):
        if not line.strip():
            continue
        task = json.loads(line)
        golds = [i for i, label in enumerate(task["labels"]) if label]
        if len(golds) == 1:
            gold_near[task["instance_id"]] = bool(task["rows"][golds[0]][near_idx])

    strata: dict[str, dict[str, list[float]]] = {
        "near": {"base": [], "real": [], "rewired": []},
        "far": {"base": [], "real": [], "rewired": []},
    }
    skipped = {"no_gold": 0, "multi_gold": 0, "not_scorable": 0}
    for line in Path(args.controls).open(encoding="utf-8"):
        if not line.strip():
            continue
        task = json.loads(line)
        if task["instance_id"] not in gold_near:
            skipped["multi_gold" if task["pool_gold"] else "no_gold"] += 1
            continue
        if task["gold_total"] != 1:
            skipped["not_scorable"] += 1
            continue
        arms = task["representations"]["metadata"]["arms"]
        bucket = "near" if gold_near[task["instance_id"]] else "far"
        strata[bucket]["base"].append(arms["base"]["symbol"])
        strata[bucket]["real"].append(arms["real"]["symbol"])
        strata[bucket]["rewired"].append(statistics.fmean(
            arms[f"rewired_{seed}"]["symbol"] for seed in REWIRE_SEEDS))

    print(f"task filter: {skipped}")
    for bucket in ("near", "far"):
        data = strata[bucket]
        n = len(data["real"])
        if not n:
            print(f"{bucket}: no tasks")
            continue
        base, real, rewired = (statistics.fmean(data[name]) for name in ("base", "real", "rewired"))
        deltas = [r - w for r, w in zip(data["real"], data["rewired"])]
        wins = sum(1 for d in deltas if d > 1e-9)
        losses = sum(1 for d in deltas if d < -1e-9)
        lo, hi = bootstrap_ci(deltas)
        print(f"{bucket:4s} n={n:5d}  base {base:.4f}  real {real:.4f}  rewired {rewired:.4f}  "
              f"real-rewired {statistics.fmean(deltas):+.4f}  CI ({lo:+.4f},{hi:+.4f})  "
              f"W/L {wins}/{losses}  p={sign_test(wins, losses):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
