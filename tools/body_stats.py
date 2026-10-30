"""Paired statistics for the body ablation, from the per-task rows it wrote."""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.analyse import bootstrap_ci, sign_test  # noqa: E402

rows = [json.loads(line) for line in (ROOT / "data" / "body_ablation.jsonl").open(encoding="utf-8")
        if line.strip()]
print(f"tasks {len(rows)}")

for field in ("symbol", "file", "pool_hit", "chars"):
    for variant in ("body_in", "body_noise"):
        if variant not in rows[0]["variant"]:
            continue
        deltas = [row["variant"][variant][field] - row["variant"]["body_out"][field] for row in rows]
        wins = sum(1 for delta in deltas if delta > 1e-9)
        losses = sum(1 for delta in deltas if delta < -1e-9)
        lo, hi = bootstrap_ci(deltas)
        print(f"{field:9s} {variant:10s} - body_out = {statistics.fmean(deltas):+.4f}  "
              f"CI ({lo:+.3f},{hi:+.3f})  W/L {wins}/{losses}  p={sign_test(wins, losses):.4f}")

if "body_noise" in rows[0]["variant"]:
    for field in ("symbol", "file"):
        deltas = [row["variant"]["body_in"][field] - row["variant"]["body_noise"][field]
                  for row in rows]
        wins = sum(1 for delta in deltas if delta > 1e-9)
        losses = sum(1 for delta in deltas if delta < -1e-9)
        lo, hi = bootstrap_ci(deltas)
        print(f"{field:9s} body_in - body_noise = {statistics.fmean(deltas):+.4f}  "
              f"CI ({lo:+.3f},{hi:+.3f})  W/L {wins}/{losses}  p={sign_test(wins, losses):.4f}")

symbol = statistics.fmean(row["variant"]["body_out"]["symbol"] for row in rows)
file = statistics.fmean(row["variant"]["body_out"]["file"] for row in rows)
print(f"\ngap body_out {file / symbol:.2f}x")
symbol = statistics.fmean(row["variant"]["body_in"]["symbol"] for row in rows)
file = statistics.fmean(row["variant"]["body_in"]["file"] for row in rows)
print(f"gap body_in  {file / symbol:.2f}x")
