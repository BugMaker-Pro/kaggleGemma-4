"""Paired comparison of two BM25 candidate-pool sizes on the same tasks.

Both inputs come from tools/rank_with_dense.py with identical folds, seeds and
feature columns; only the candidate pool differs.  Reports per-metric means,
paired deltas, bootstrap CIs and sign tests so a pool-size change is judged on
the same tasks rather than against a differently sized evaluation set.
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

METRICS = ("base_symbol", "cosine_symbol", "dense_symbol", "both_symbol",
           "base_file", "cosine_file", "dense_file", "both_file")


def load(path: str) -> dict[str, dict]:
    return {row["instance_id"]: row for row in
            (json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
             if line.strip())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", required=True)
    ap.add_argument("--treatment", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    control, treatment = load(args.control), load(args.treatment)
    ids = sorted(set(control) & set(treatment))
    if not ids:
        raise SystemExit("no paired tasks between the two score files")
    available = [m for m in METRICS if m in next(iter(control.values()))]
    result = {"control": args.control, "treatment": args.treatment,
              "paired_tasks": len(ids),
              "control_only": len(set(control) - set(treatment)),
              "treatment_only": len(set(treatment) - set(control)),
              "metrics": {}}
    print(f"paired tasks {len(ids)} "
          f"(control only {result['control_only']}, treatment only {result['treatment_only']})")
    for metric in available:
        deltas = [treatment[i][metric] - control[i][metric] for i in ids]
        wins = sum(1 for d in deltas if d > 1e-9)
        losses = sum(1 for d in deltas if d < -1e-9)
        lo, hi = bootstrap_ci(deltas)
        entry = {"control_mean": statistics.fmean(control[i][metric] for i in ids),
                 "treatment_mean": statistics.fmean(treatment[i][metric] for i in ids),
                 "delta": statistics.fmean(deltas), "ci": [lo, hi],
                 "wins": wins, "losses": losses, "p_sign": sign_test(wins, losses)}
        result["metrics"][metric] = entry
        print(f"  {metric:15s} {entry['control_mean']:.4f} -> {entry['treatment_mean']:.4f} "
              f"delta {entry['delta']:+.4f}  CI ({lo:+.3f},{hi:+.3f})  "
              f"W/L {wins}/{losses}  p={entry['p_sign']:.4f}")
    Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("->", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
