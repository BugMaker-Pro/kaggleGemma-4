"""Does the evidence override still help the tasks that quote source?

`sensitivity.py` answers this for the Lite study from the evidence passes. The
full benchmark has no such pass: the same two signals are already columns of
`features.jsonl`, so the buckets are recoverable from the candidate rows.

    python tools/sensitivity_full.py --rows data/features_full.jsonl \
        --results data/combo_ltr_full.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

IDX = {"body_line": 3, "path_in_issue": 4, "frame_hit": 6, "named_file": 8}


def bucket(task: dict) -> str:
    rows = task["rows"]
    if any(row[IDX["body_line"]] for row in rows):
        return "quotes code"
    if any(row[IDX["path_in_issue"]] or row[IDX["frame_hit"]] or row[IDX["named_file"]]
           for row in rows):
        return "names only"
    return "no signal"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "features_full.jsonl"))
    ap.add_argument("--results", default=str(ROOT / "data" / "combo_ltr_full.jsonl"))
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    results = {row["instance_id"]: row for row in
               (json.loads(line) for line in Path(args.results).open(encoding="utf-8") if line.strip())}

    groups: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        if task["instance_id"] in results:
            groups[bucket(task)].append(task["instance_id"])

    print(f"{'subset':14s}{'n':>6s}{'share':>8s}{'bm25':>8s}{'ranker':>8s}{'ranker+ev':>11s}{'Δ ev':>8s}")
    total = sum(len(v) for v in groups.values())
    for name in ("quotes code", "names only", "no signal"):
        ids = groups.get(name, [])
        if not ids:
            continue
        bm25 = statistics.fmean(results[i]["bm25"] for i in ids)
        ltr = statistics.fmean(results[i]["ltr"] for i in ids)
        ev = statistics.fmean(results[i]["ltr_ev5"] for i in ids)
        print(f"{name:14s}{len(ids):6d}{len(ids) / total:8.1%}{bm25:8.3f}{ltr:8.3f}{ev:11.3f}{ev - ltr:+8.3f}")

    print(f"\nall tasks{'':9s}{total:6d}{1.0:8.1%}"
          f"{statistics.fmean(r['bm25'] for r in results.values()):8.3f}"
          f"{statistics.fmean(r['ltr'] for r in results.values()):8.3f}"
          f"{statistics.fmean(r['ltr_ev5'] for r in results.values()):11.3f}"
          f"{statistics.fmean(r['ltr_ev5'] - r['ltr'] for r in results.values()):+8.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
