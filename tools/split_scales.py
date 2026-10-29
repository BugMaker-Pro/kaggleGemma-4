"""The same split at both scales, with one definition.

Table 6 splits the Lite tasks by what the issue offers. That split was built from
the evidence passes, which only exist for the 300 Lite instances, so it cannot be
reused on the full benchmark. This recomputes the strict definition straight from
the features file, where it is already a column:

  quotes   the gold symbol's own body contains a line the issue pastes
  names    the issue names a file or prints a traceback frame
  neither  the issue carries no source at all

Because both files carry `body_line` per candidate and labels per candidate, the
same rule gives a comparable bucket on 290 tasks and on 2,232.

    python tools/split_scales.py --lite-rows data/features.jsonl \
        --lite-results data/combo_ltr.jsonl \
        --full-rows data/features_full.jsonl --full-results data/combo_ltr_full.jsonl
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

BODY_LINE, PATH_IN_ISSUE, FRAME_HIT, NAMED_FILE = 3, 4, 6, 8


def bucket(task: dict) -> str:
    rows, labels = task["rows"], task["labels"]
    for index, label in enumerate(labels):
        if label and rows[index][BODY_LINE]:
            return "quotes"
    for index, label in enumerate(labels):
        if label and (rows[index][PATH_IN_ISSUE] or rows[index][FRAME_HIT]
                      or rows[index][NAMED_FILE]):
            return "names"
    return "neither"


def load_rows(path: Path) -> dict[str, dict]:
    return {row["instance_id"]: row for row in
            (json.loads(line) for line in path.open(encoding="utf-8") if line.strip())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lite-rows", default=str(ROOT / "data" / "features.jsonl"))
    ap.add_argument("--lite-results", default=str(ROOT / "data" / "combo_ltr.jsonl"))
    ap.add_argument("--full-rows", default=str(ROOT / "data" / "features_full.jsonl"))
    ap.add_argument("--full-results", default=str(ROOT / "data" / "combo_ltr_full.jsonl"))
    args = ap.parse_args(argv)

    for label, rows_path, results_path in (
        ("lite", Path(args.lite_rows), Path(args.lite_results)),
        ("full", Path(args.full_rows), Path(args.full_results)),
    ):
        if not rows_path.exists() or not results_path.exists():
            print(f"{label}: missing input, skipped")
            continue
        tasks = load_rows(rows_path)
        results = load_rows(results_path)
        groups: dict[str, list[str]] = defaultdict(list)
        for instance_id, task in tasks.items():
            if instance_id in results and task.get("labels"):
                groups[bucket(task)].append(instance_id)
        total = sum(len(v) for v in groups.values())
        print(f"\n== {label} ({total} tasks) ==")
        print(f"{'subset':10s}{'n':>6s}{'share':>8s}{'bm25':>8s}{'ranker':>8s}{'rank+ev':>9s}"
              f"{'Δ ranker':>10s}{'Δ ev':>8s}")
        for name in ("quotes", "names", "neither"):
            ids = groups.get(name, [])
            if not ids:
                continue
            bm25 = statistics.fmean(results[i]["bm25"] for i in ids)
            ltr = statistics.fmean(results[i]["ltr"] for i in ids)
            ev = statistics.fmean(results[i]["ltr_ev5"] for i in ids)
            print(f"{name:10s}{len(ids):6d}{len(ids) / total:8.1%}{bm25:8.3f}{ltr:8.3f}"
                  f"{ev:9.3f}{ltr - bm25:+10.3f}{ev - ltr:+8.3f}")
        all_ids = [i for ids in groups.values() for i in ids]
        bm25 = statistics.fmean(results[i]["bm25"] for i in all_ids)
        ltr = statistics.fmean(results[i]["ltr"] for i in all_ids)
        ev = statistics.fmean(results[i]["ltr_ev5"] for i in all_ids)
        print(f"{'all':10s}{len(all_ids):6d}{1.0:8.1%}{bm25:8.3f}{ltr:8.3f}{ev:9.3f}"
              f"{ltr - bm25:+10.3f}{ev - ltr:+8.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
