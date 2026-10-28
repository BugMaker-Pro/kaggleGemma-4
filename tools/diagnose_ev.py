"""Why does the combined arm lose on one repository?

Prints, for the tasks where the evidence arm does worse than plain BM25, what
each channel fired on: a traceback frame, a named path, a quoted body line — and
whether that evidence was right.

    python tools/diagnose_ev.py --repo pytest-dev/pytest
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "experiment_combo.jsonl"))
    ap.add_argument("--repo", default="")
    ap.add_argument("--arm", default="combo")
    ap.add_argument("--worst", type=int, default=10)
    args = ap.parse_args(argv)

    rows = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8")
            if line.strip()]
    rows = [row for row in rows if row.get("arms")]
    if args.repo:
        rows = [row for row in rows if row["repo"] == args.repo]

    rows.sort(key=lambda row: row["arms"][args.arm]["recall@10"]
              - row["arms"]["text"]["recall@10"])
    print(f"{'instance':34s}{'text':>6s}{'arm':>6s}{'frame':>7s}{'named':>7s}"
          f"{'quoted':>8s}  correct(frame/file)")
    for row in rows[: args.worst]:
        signals = row["signals"]
        print(f"{row['instance_id']:34s}{row['arms']['text']['recall@10']:6.2f}"
              f"{row['arms'][args.arm]['recall@10']:6.2f}"
              f"{signals['frame']:7d}{signals['named']:7d}{signals['quoted']:8d}"
              f"  {signals['frame_correct']}/{signals['named_correct']}")

    wins = sum(1 for row in rows if row["arms"][args.arm]["recall@10"]
               > row["arms"]["text"]["recall@10"])
    losses = sum(1 for row in rows if row["arms"][args.arm]["recall@10"]
                 < row["arms"]["text"]["recall@10"])
    print(f"\n{len(rows)} tasks: {wins} up, {losses} down")
    if losses:
        bad = [row for row in rows if row["arms"][args.arm]["recall@10"]
               < row["arms"]["text"]["recall@10"]]
        print("on the tasks that went down: named file correct "
              f"{sum(1 for row in bad if row['signals']['named_correct'])}/{len(bad)}, "
              f"frame hit {sum(1 for row in bad if row['signals']['frame_correct'])}/{len(bad)}, "
              f"quoted gold {sum(1 for row in bad if row['signals']['quoted_gold'])}/{len(bad)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
