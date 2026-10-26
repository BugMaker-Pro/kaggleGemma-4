"""Recompute every number the paper prints, then check the paper still says it.

Two failure modes are worth guarding against: a number that no longer matches the
data, and a number that is still correct but has drifted out of the draft (or now
appears in two places with different values). This script reports both.

    python tools/audit_numbers.py            # full check, ~15 s
    python tools/audit_numbers.py --fast     # skip the graph rebuild
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.buildgraph import build_graph, read_snapshot  # noqa: E402
from experiments.snapindex import SnapshotIndex  # noqa: E402
from tools.analyse import paired  # noqa: E402

failures: list[str] = []


def check(label: str, claimed, actual, tol: float, fmt: str = "{:.3f}") -> None:
    if isinstance(claimed, str):
        ok = claimed == actual
    else:
        ok = actual is not None and abs(actual - claimed) <= tol
    mark = "ok  " if ok else "FAIL"
    print(f"  [{mark}] {label:52s} paper={claimed!s:>8s}  data="
          f"{(fmt.format(actual) if isinstance(actual, float) else actual)!s}")
    if not ok:
        failures.append(f"{label}: paper={claimed}, data={actual}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    args = ap.parse_args(argv)

    v3 = [json.loads(x) for x in (ROOT / "data" / "experiment_v3.jsonl").open(encoding="utf-8") if x.strip()]
    ablation = [json.loads(x) for x in (ROOT / "data" / "ablation.jsonl").open(encoding="utf-8") if x.strip()]
    gold = [json.loads(x) for x in (ROOT / "data" / "gold_symbols.jsonl").open(encoding="utf-8") if x.strip()]
    tasks = [json.loads(x) for x in (ROOT / "data" / "swebench_lite.jsonl").open(encoding="utf-8") if x.strip()]
    paper = (ROOT / "paper" / "main.md").read_text(encoding="utf-8")

    scored = [row for row in v3 if row.get("arms")]

    print("== corpus ==")
    check("tasks", 300, len(tasks), 0)
    check("repositories", 12, len({t["repo"] for t in tasks}), 0)
    check("distinct base commits", 297, len({t["base_commit"] for t in tasks}), 0)
    symbols = sum(len(f.get("symbols", [])) for row in gold for f in row["files"])
    check("gold symbols", 354, symbols, 0)
    check("tasks with a symbol", 290, sum(1 for row in gold if row["has_symbols"]), 0)
    outside = sum(f.get("unresolved_anchors", 0) for row in gold for f in row["files"])
    check("changed lines outside any definition", 87, outside, 0)
    size = sum(p.stat().st_size for p in (ROOT / "data" / "repos").glob("*.tar.gz"))
    check("snapshot bytes (GB)", 2.5, round(size / 1024 ** 3, 1), 0.1, fmt="{:.1f}")

    print("\n== headline ==")
    sym10 = statistics.fmean(row["arms"]["text"]["recall@10"] for row in scored)
    file10 = statistics.fmean(row["arms"]["text"]["file_recall@10"] for row in scored)
    file5 = statistics.fmean(row["arms"]["text"]["file_recall@5"] for row in scored)
    sym1 = statistics.fmean(row["arms"]["text"]["recall@1"] for row in scored)
    sym5 = statistics.fmean(row["arms"]["text"]["recall@5"] for row in scored)
    check("symbol recall@10", "27.5%", f"{sym10 * 100:.1f}%", 0, fmt="{}")
    check("file recall@10", "62.4%", f"{file10 * 100:.1f}%", 0, fmt="{}")
    check("file recall@5", 0.548, file5, 0.001)
    check("symbol recall@1", 0.091, sym1, 0.001)
    check("symbol recall@5", 0.214, sym5, 0.001)
    check("gap factor", 2.3, round(file10 / sym10, 1), 0.05, fmt="{:.1f}")

    print("\n== arms (Table 2) ==")
    expected = {
        "graph_rerank": (0.287, 0.614, 0.012, 0.50),
        "graph_open": (0.257, 0.576, -0.018, 0.46),
        "graph_open2": (0.249, 0.579, -0.026, 0.18),
        "graph_fuse": (0.272, 0.624, -0.003, 1.00),
        "graph_fuse_precise": (0.275, 0.624, 0.000, 1.00),
        "graph_ppr": (0.268, 0.579, -0.007, 0.72),
        "graph_ppr_text": (0.272, 0.624, -0.003, 1.00),
    }
    for arm, (r10, f10, delta, p) in expected.items():
        got_r10 = statistics.fmean(row["arms"][arm]["recall@10"] for row in scored)
        got_f10 = statistics.fmean(row["arms"][arm]["file_recall@10"] for row in scored)
        stats = paired(scored, "recall@10", arm)
        check(f"{arm} r@10", r10, got_r10, 0.001)
        check(f"{arm} file r@10", f10, got_f10, 0.001)
        check(f"{arm} delta", delta, stats["delta"], 0.0015)
        check(f"{arm} sign p", p, round(stats["sign_p"], 2), 0.005)

    print("\n== reach and the ball ==")
    reach1 = statistics.fmean(row["headroom"]["s5h1"] for row in ablation if row.get("headroom"))
    reach2 = statistics.fmean(row["headroom"]["s5h2"] for row in ablation if row.get("headroom"))
    check("one-hop reach", 0.119, reach1, 0.001)
    check("two-hop reach", 0.357, reach2, 0.001)
    with_ball = [row for row in scored if row.get("ball")]
    sizes = [row["ball"]["size1"] for row in with_ball]
    check("median ball size", 21, statistics.median(sizes), 0, fmt="{:.0f}")
    check("ball members", 9855, sum(sizes), 0)
    gold1 = sum(row["ball"]["gold1"] for row in with_ball)
    check("gold in ball", 41, gold1, 0)
    check("ball gold density", 0.0042, gold1 / sum(sizes), 0.0001)
    # Precision per slot, not recall per task: a task carries 1.22 gold symbols,
    # so recall@10 / 10 understates the hit rate of a single slot.
    hits = sum(len(set(row["arms"]["text"]["top"][:10]) & set(row["gold_nodes"]))
               for row in scored)
    check("gold density per text slot", 0.031, hits / (10 * len(scored)), 0.002)
    tasks1 = sum(1 for row in with_ball if row["ball"]["gold1"])
    check("tasks with reachable gold", 38, tasks1, 0)
    check("share of tasks", "13.1%", f"{tasks1 / len(with_ball) * 100:.1f}%", 0, fmt="{}")
    ranks = [rank for row in with_ball for rank in row["ball"]["gold1_ppr_rank"]]
    converted = sum(1 for rank in ranks if 0 < rank <= 10)
    check("reachable gold", 41, len(ranks), 1)
    check("converted by diffusion", 18, converted, 0)
    check("conversion share", "44%", f"{converted / len(ranks) * 100:.0f}%", 0, fmt="{}")
    check("median conversion rank", 12, statistics.median(ranks), 0, fmt="{:.0f}")

    print("\n== exchange accounting ==")
    for arm, gained, lost in (("graph_ppr", 15, 17), ("graph_open", 12, 17),
                              ("graph_rerank", 21, 15)):
        add = drop = 0
        for row in scored:
            text_top = set(row["arms"]["text"]["top"][:10])
            arm_top = set(row["arms"][arm]["top"][:10])
            gold_nodes = set(row["gold_nodes"])
            add += len((gold_nodes & arm_top) - text_top)
            drop += len((gold_nodes & text_top) - arm_top)
        check(f"{arm} gained", gained, add, 0)
        check(f"{arm} lost", lost, drop, 0)

    print("\n== pool ==")
    check("pool recall @200", 0.600, statistics.fmean(
        row["pool_recall"]["200"] for row in ablation if row.get("pool_recall")), 0.001)
    check("pool recall @60", 0.464, statistics.fmean(
        row["pool_recall"]["60"] for row in ablation if row.get("pool_recall")), 0.001)
    check("pool recall @500", 0.704, statistics.fmean(
        row["pool_recall"]["500"] for row in ablation if row.get("pool_recall")), 0.001)
    oracle = statistics.fmean(row["oracle@10"] for row in scored if row.get("oracle@10") is not None)
    check("oracle@10", 0.630, oracle, 0.001)

    if not args.fast:
        print("\n== django edge resolution ==")
        # The snapshot the paper's edge table is taken from; any django snapshot
        # would do, but the one audited has to be the one printed.
        index = SnapshotIndex(str(ROOT / "data" / "repos"))
        task = next(t for t in tasks if t["instance_id"] == "django__django-14787")
        path = index.path_for(task)
        graph, stats = build_graph(read_snapshot(path))
        counts = Counter(edge.get("resolution", "?") for edge in graph.edges)
        total = sum(counts.values())
        definite = counts["local"] + counts["import"] + counts["unique"] + counts["suffix"]
        check("definite call-site share", "46%", f"{definite / total * 100:.0f}%", 0, fmt="{}")
        check("unresolved share", 0.341, counts["unresolved"] / total, 0.002)
        check("ambiguous share", 0.150, counts["ambiguous"] / total, 0.002)

    print("\n== the draft still says the same thing ==")
    for token in ("62.4%", "27.5%", "2.3×", "0.42%", "3.1%", "11.9", "35.7",
                  "9,855", "44%", "46%", "seven times", "seven to one"):
        present = token in paper
        print(f"  [{'ok  ' if present else 'FAIL'}] draft contains {token!r}")
        if not present:
            failures.append(f"draft lost {token!r}")

    print("\n== citations ==")
    cited = sorted({int(n) for n in __import__("re").findall(r"\[(\d)\]", paper)})
    entries = __import__("re").findall(r"^\[(\d)\]", paper, flags=__import__("re").M)
    entries = sorted(int(n) for n in entries)
    ok = cited == entries and cited == list(range(1, len(cited) + 1))
    print(f"  [{'ok  ' if ok else 'FAIL'}] markers {cited} vs entries {entries}")
    if not ok:
        failures.append(f"citation markers {cited} do not match entries {entries}")
    notes = (ROOT / "docs" / "papers" / "notes.md").read_text(encoding="utf-8")
    for name in ("LocAgent", "ARISE", "PyCG", "CodexGraph", "RepoAtlas",
                 "SWE-agent", "SWE-bench"):
        verified = name in notes
        print(f"  [{'ok  ' if verified else 'FAIL'}] {name} has a verified note")
        if not verified:
            failures.append(f"{name} is cited but not in docs/papers/notes.md")

    print(f"\n{len(failures)} failure(s)")
    for item in failures:
        print(f"  - {item}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
