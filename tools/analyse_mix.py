"""Does any depth/breadth mix beat plain text under the same ten slots?

The file-first arms either spend all slots inside one file (full depth, poor file
precision) or spread across five (good precision, no depth). A mix buys depth
where the file ranking is most confident and keeps breadth with the rest. All of
it is computed from rankings already stored by `run_filefirst.py`.

    python tools/analyse_mix.py
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

MIXES = (
    ("mix1", "ff_k1", 1),
    ("mix2", "ff_k1", 2),
    ("mix3", "ff_k1", 3),
    ("mix4", "ff_k1", 4),
    ("mix2x2", "ff_k2", 2),   # 1 slot each from the two best files, then text
)


def order_mix(text: list[str], deep: list[str], take: int, alt: bool = False) -> list[str]:
    """`take` symbols from the deep arm first, then the text ranking."""
    if alt:
        head = deep[:take * 2:2] if take else []
    else:
        head = deep[:take]
    out, seen = [], set()
    for node in head:
        if node not in seen:
            out.append(node)
            seen.add(node)
    for node in text:
        if len(out) >= 50:
            break
        if node not in seen:
            out.append(node)
            seen.add(node)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(ROOT / "data" / "experiment_ff.jsonl"))
    args = ap.parse_args(argv)
    rows = [json.loads(line) for line in Path(args.rows).open(encoding="utf-8")
            if line.strip()]
    rows = [row for row in rows if row.get("arms")]
    print(f"scored tasks: {len(rows)}\n")

    def recall(order: list[str], gold: set[str], k: int) -> float:
        return len(set(order[:k]) & gold) / len(gold)

    base = {row["instance_id"]: row for row in rows}
    print(f"{'arm':10s}{'r@1':>7s}{'r@5':>7s}{'r@10':>7s}{'delta@10':>10s}{'p':>7s}")
    text10 = statistics.fmean(recall(row["arms"]["text"]["top"], set(row["gold_nodes"]), 10)
                              for row in rows)
    for name, deep_arm, take in MIXES:
        alt = name.endswith("2x2")
        values10, deltas, wins, losses = [], [], 0, 0
        values5, values1 = [], []
        for row in rows:
            gold = set(row["gold_nodes"])
            order = order_mix(row["arms"]["text"]["top"], row["arms"][deep_arm]["top"],
                              take, alt=alt)
            values1.append(recall(order, gold, 1))
            values5.append(recall(order, gold, 5))
            values10.append(recall(order, gold, 10))
            delta = values10[-1] - recall(row["arms"]["text"]["top"], gold, 10)
            deltas.append(delta)
            if delta > 0:
                wins += 1
            elif delta < 0:
                losses += 1
        lo, hi = bootstrap_ci(deltas)
        print(f"{name:10s}{statistics.fmean(values1):7.3f}{statistics.fmean(values5):7.3f}"
              f"{statistics.fmean(values10):7.3f}{statistics.fmean(deltas):+10.3f}"
              f"{sign_test(wins, losses):7.3f}"
              f"   W/L {wins}/{losses}  CI ({lo:+.3f},{hi:+.3f})")

    # Conditional view: on tasks where stage 1 already has the right file,
    # does depth pay? This is the assumption behind every file-first method.
    print("\n== conditional on the gold file being in the top-3 file ranking ==")
    subset = [row for row in rows if row["stage1"]["gold_in_top3"]]
    print(f"tasks: {len(subset)}")
    for arm in ("text", "ff_k1", "ff_k2", "ff_k3"):
        values = [recall(row["arms"][arm]["top"], set(row["gold_nodes"]), 10)
                  for row in subset]
        print(f"  {arm:12s} r@10 {statistics.fmean(values):.3f}")
    values = [recall(row["arms"]["file_oracle"]["top"], set(row["gold_nodes"]), 10)
              for row in subset]
    print(f"  {'file_oracle':12s} r@10 {statistics.fmean(values):.3f}  (ceiling)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
