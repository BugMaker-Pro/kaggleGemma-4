"""Sensitivity: how much of the evidence gain survives without quoted code?

The strongest signal is a pasted line of source. If the gain leaned on that
alone, the method would only work where users paste code. This splits the tasks
by which channel fired and reports the effect in each bucket.

    python tools/sensitivity.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "experiment_combo2.jsonl"))
    args = ap.parse_args(argv)

    quoted = {row["instance_id"]: row for row in
              (json.loads(line) for line in (ROOT / "data" / "body_evidence.jsonl").open(encoding="utf-8") if line.strip())}
    named = {row["instance_id"]: row for row in
             (json.loads(line) for line in (ROOT / "data" / "issue_evidence.jsonl").open(encoding="utf-8") if line.strip())}
    rows = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8") if line.strip()]
    rows = [row for row in rows if row.get("arms")]

    def bucket(instance_id: str) -> str:
        if quoted.get(instance_id, {}).get("line_quote"):
            return "quotes code"
        info = named.get(instance_id, {})
        if info.get("paths") or info.get("frames") or info.get("path_hit"):
            return "names only"
        return "no signal"

    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(bucket(row["instance_id"]), []).append(row)

    print(f"{'subset':14s}{'n':>4s}{'text':>8s}{'combo':>8s}{'delta':>8s}")
    for name in ("quotes code", "names only", "no signal"):
        group = groups.get(name, [])
        if not group:
            continue
        text = statistics.fmean(row["arms"]["text"]["recall@10"] for row in group)
        combo = statistics.fmean(row["arms"]["combo"]["recall@10"] for row in group)
        print(f"{name:14s}{len(group):4d}{text:8.3f}{combo:8.3f}{combo - text:+8.3f}")

    without = [row for row in rows if bucket(row["instance_id"]) != "quotes code"]
    text = statistics.fmean(row["arms"]["text"]["recall@10"] for row in without)
    combo = statistics.fmean(row["arms"]["combo"]["recall@10"] for row in without)
    print(f"\nexcluding every task that quotes code (n={len(without)}): "
          f"{text:.3f} -> {combo:.3f} ({combo - text:+.3f})")
    all_text = statistics.fmean(row["arms"]["text"]["recall@10"] for row in rows)
    all_combo = statistics.fmean(row["arms"]["combo"]["recall@10"] for row in rows)
    print(f"all tasks: {all_text:.3f} -> {all_combo:.3f} ({all_combo - all_text:+.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
