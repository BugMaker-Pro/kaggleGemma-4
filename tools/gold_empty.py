"""Classify the tasks the shipped key leaves empty, for the audit table."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
rows = [json.loads(line) for line in (ROOT / "data" / "gold_fixed.jsonl").open(encoding="utf-8") if line.strip()]
for row in rows:
    if row["gold_a"]:
        continue
    added = [name for probe in row["files"] for name in probe["added"]]
    parent = [name for name in added if "." in name]
    print(f"{row['instance_id']:32s} added={len(added):2d} nested={len(parent):2d} "
          f"repaired={len(row['gold_c'])} {row['files'][0]['old']}")
    if added:
        print(f"    {added[:4]}")
