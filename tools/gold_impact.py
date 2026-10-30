"""Does correcting the answer key move the reported numbers?

Re-labels every pool candidate with the repaired gold set (tools/gold_fix.py,
method C) and recomputes recall@10 for the arms whose ranking is already on
disk. No model is retrained, so the only thing that varies between the two
columns is the answer key.

    python tools/gold_impact.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.buildgraph import module_of  # noqa: E402

LITE = str(ROOT / "data" / "swebench_lite.jsonl")


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (ROOT / "data" / name).open(encoding="utf-8") if line.strip()]


def as_id(symbol: str) -> str:
    """'a/b/c.py::C.m' -> 'a.b.c.C.m' (the pool's node-id form)."""
    path, qualname = symbol.split("::", 1)
    return f"{module_of(path)}.{qualname}"


def recall(order: list[int], labels: list[int], total: int, k: int = 10) -> float:
    if not total:
        return 0.0
    return sum(1 for index in order[:k] if labels[index]) / total


def main() -> int:
    lite = {json.loads(line)["instance_id"] for line in open(LITE, encoding="utf-8") if line.strip()}
    fixed = {row["instance_id"]: row for row in load("gold_fixed.jsonl")}
    feat = {row["instance_id"]: row for row in load("features_full.jsonl") if row["instance_id"] in lite}
    orders = {row["instance_id"]: row for row in load("combo_ltr_orders.jsonl")}

    arms = ["bm25", "ltr", "ltr_ev5", "graph"]
    sums = {arm: {"a": 0.0, "c": 0.0} for arm in arms}
    count = 0
    changed = []
    for iid, row in feat.items():
        entry = fixed.get(iid)
        if entry is None:
            continue
        ids = row["ids"]
        labels_a = row["labels"]
        gold_c = {as_id(symbol) for symbol in entry["gold_c"]}
        gold_a = {as_id(symbol) for symbol in entry["gold_a"]}
        labels_c = [1 if node in gold_c else 0 for node in ids]
        total_a = row["gold_total"]
        total_c = len(entry["gold_c"])
        if not total_a or not total_c:
            print(f"  skip {iid}: gold A={total_a} C={total_c}")
            continue
        orders_here = dict(orders[iid]["orders"])
        orders_here["graph"] = row["rerank_top10"]
        count += 1
        for arm in arms:
            order = orders_here[arm]
            sums[arm]["a"] += recall(order, labels_a, total_a)
            sums[arm]["c"] += recall(order, labels_c, total_c)
        delta = (recall(orders_here["ltr"], labels_c, total_c)
                 - recall(orders_here["ltr"], labels_a, total_a))
        if abs(delta) > 1e-9 or gold_a != gold_c:
            changed.append((iid, delta, total_a, total_c))

    print(f"\ntasks {count}")
    summary = {"tasks": count, "arms": {}}
    for arm in arms:
        a, c = sums[arm]["a"] / count, sums[arm]["c"] / count
        summary["arms"][arm] = {"shipped": round(a, 4), "repaired": round(c, 4),
                                "delta": round(c - a, 4)}
        print(f"  {arm:10s} A {a:.4f}  C {c:.4f}  delta {c - a:+.4f}")
    summary["max_delta"] = max(abs(v["delta"]) for v in summary["arms"].values())
    (ROOT / "data" / "gold_impact.json").write_text(json.dumps(summary, indent=2) + "\n",
                                                    encoding="utf-8")
    print("\nper-task changes (ltr arm):")
    for iid, delta, ta, tc in sorted(changed, key=lambda x: -abs(x[1])):
        print(f"  {iid:34s} delta {delta:+.3f}   gold {ta} -> {tc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
