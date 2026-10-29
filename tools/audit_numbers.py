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
from tools.analyse import paired, sign_test  # noqa: E402

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


def recall_files(order, files, gold_files) -> float:
    """File-level recall@10: distinct gold files reached by the first ten slots."""
    if not gold_files:
        return float("nan")
    seen: list[str] = []
    for index in order[:10]:
        path = files[index] if index < len(files) else ""
        if path and path not in seen:
            seen.append(path)
    return len(set(seen) & set(gold_files)) / len(set(gold_files))


def strict_bucket(task: dict) -> str:
    """What the issue offers, from the features file alone — same rule at any scale.

    quotes   the gold symbol's own body contains a line the issue pastes
    names    the issue names a file or prints a traceback frame
    neither  no source at all
    """
    rows, labels = task["rows"], task["labels"]
    for index, label in enumerate(labels):
        if label and rows[index][3]:
            return "quotes"
    for index, label in enumerate(labels):
        if label and (rows[index][4] or rows[index][6] or rows[index][8]):
            return "names"
    return "neither"


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
    # only the Lite snapshots: data/repos now also holds the 2,174-snapshot full set
    lite_files = {f"{t['repo'].replace('/', '__')}@{t['base_commit'][:12]}.tar.gz" for t in tasks}
    size = sum(p.stat().st_size for p in (ROOT / "data" / "repos").glob("*.tar.gz")
               if p.name in lite_files)
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

    print("\n== evidence channels ==")
    ev = [json.loads(x) for x in (ROOT / "data" / "experiment_ev.jsonl").open(encoding="utf-8") if x.strip()]
    ev = [row for row in ev if row.get("arms")]
    body = [json.loads(x) for x in (ROOT / "data" / "experiment_body.jsonl").open(encoding="utf-8") if x.strip()]
    body = [row for row in body if row.get("arms")]
    combo = [json.loads(x) for x in (ROOT / "data" / "experiment_combo2.jsonl").open(encoding="utf-8") if x.strip()]
    combo = [row for row in combo if row.get("arms")]

    for name, rows_, arm, r10, delta, p in (
        ("ev_soft", ev, "ev_soft", 0.323, 0.048, 0.005),
        ("body_cap5", body, "body_cap5", 0.335, 0.060, 0.0),
        ("combo", combo, "combo", 0.352, 0.077, 0.0),
        ("combo_cap", combo, "combo_cap", 0.348, 0.073, 0.0),
    ):
        value = statistics.fmean(row["arms"][arm]["recall@10"] for row_ in [rows_] for row in row_)
        check(f"{name} r@10", r10, value, 0.001)
        stats = paired(rows_, "recall@10", arm)
        check(f"{name} delta", delta, stats["delta"], 0.0015)
        check(f"{name} p", p, round(stats["sign_p"], 3), 0.0015)
    check("combo characters", 1535,
          statistics.fmean(row["arms"]["combo"]["chars@10"] for row in combo), 2, fmt="{:.0f}")
    check("combo wins", 30, sum(1 for row in combo
                                if row["arms"]["combo"]["recall@10"] > row["arms"]["text"]["recall@10"]), 0)

    issue = [json.loads(x) for x in (ROOT / "data" / "issue_evidence.jsonl").open(encoding="utf-8") if x.strip()]
    census = [json.loads(x) for x in (ROOT / "data" / "body_evidence.jsonl").open(encoding="utf-8") if x.strip()]
    check("issues naming a path", 0.417,
          sum(1 for row in issue if row["paths"]) / len(issue), 0.003)
    check("issues with a frame", 0.172,
          sum(1 for row in issue if row["frames"]) / len(issue), 0.003)
    check("issues quoting a body line", 0.228,
          sum(1 for row in census if row["line_quote"]) / len(census), 0.003)

    def fires(instance_id: str) -> bool:
        row = next((item for item in issue if item["instance_id"] == instance_id), None)
        quoted = next((item for item in census if item["instance_id"] == instance_id), None)
        return bool((row and (row["paths"] or row["frames"]))
                    or (quoted and quoted["line_quote"]))

    hot = [row for row in combo if fires(row["instance_id"])]
    cold = [row for row in combo if not fires(row["instance_id"])]
    check("tasks with a signal", 137, len(hot), 0)
    check("signal: text r@10", 0.305,
          statistics.fmean(row["arms"]["text"]["recall@10"] for row in hot), 0.002)
    check("signal: combo r@10", 0.446,
          statistics.fmean(row["arms"]["combo"]["recall@10"] for row in hot), 0.002)
    check("no signal: text r@10", 0.248,
          statistics.fmean(row["arms"]["text"]["recall@10"] for row in cold), 0.002)
    check("no signal: combo r@10", 0.268,
          statistics.fmean(row["arms"]["combo"]["recall@10"] for row in cold), 0.002)

    from tools.sensitivity import main as _sensitivity  # noqa: F401,PLC0415

    def quoted(instance_id: str) -> bool:
        row = next((item for item in census if item["instance_id"] == instance_id), None)
        return bool(row and row["line_quote"])

    def named_only(instance_id: str) -> bool:
        row = next((item for item in issue if item["instance_id"] == instance_id), None)
        return bool(row and (row["paths"] or row["frames"])) and not quoted(instance_id)

    buckets = {
        "quotes code": [row for row in combo if quoted(row["instance_id"])],
        "names only": [row for row in combo if named_only(row["instance_id"])],
    }
    for label, claimed_n, claimed_delta in (("quotes code", 66, 0.289), ("names only", 71, 0.004)):
        group = buckets[label]
        check(f"{label}: n", claimed_n, len(group), 0)
        delta = (statistics.fmean(row["arms"]["combo"]["recall@10"] for row in group)
                 - statistics.fmean(row["arms"]["text"]["recall@10"] for row in group))
        check(f"{label}: delta", claimed_delta, delta, 0.002)

    print("\n== learned ranker ==")
    ltr = [json.loads(x) for x in (ROOT / "data" / "combo_ltr.jsonl").open(encoding="utf-8") if x.strip()]
    for arm, claimed in (("bm25", 0.275), ("ltr", 0.332), ("ltr_ev5", 0.361)):
        check(f"{arm} r@10", claimed,
              statistics.fmean(row[arm] for row in ltr), 0.002)
    keys = sorted(row["instance_id"] for row in ltr)
    index = {row["instance_id"]: row for row in ltr}
    deltas = [index[key]["ltr_ev5"] - index[key]["bm25"] for key in keys]
    check("ltr_ev5 delta", 0.086, statistics.fmean(deltas), 0.002)
    wins = sum(1 for delta in deltas if delta > 0)
    losses = sum(1 for delta in deltas if delta < 0)
    check("ltr_ev5 wins", 39, wins, 0)
    check("ltr_ev5 losses", 13, losses, 0)
    check("ltr_ev5 p", 0.0004, round(sign_test(wins, losses), 4), 0.002)

    print("\n== the split at both scales (tools/split_scales.py) ==")
    for scale, rows_name, results_name, claims in (
        ("290", "features.jsonl", "combo_ltr.jsonl",
         (("quotes", 54, 0.481, 0.776), ("names", 16, 0.406, 0.469),
          ("neither", 220, 0.215, 0.214))),
        ("2,232", "features_full.jsonl", "combo_ltr_full.jsonl",
         (("quotes", 355, 0.459, 0.755), ("names", 224, 0.380, 0.659),
          ("neither", 1653, 0.185, 0.236))),
    ):
        rows = {row["instance_id"]: row for row in
                (json.loads(x) for x in (ROOT / "data" / rows_name).open(encoding="utf-8") if x.strip())}
        res = {row["instance_id"]: row for row in
               (json.loads(x) for x in (ROOT / "data" / results_name).open(encoding="utf-8") if x.strip())}
        groups: dict[str, list[str]] = {}
        for instance_id, task in rows.items():
            if instance_id in res and task.get("labels"):
                groups.setdefault(strict_bucket(task), []).append(instance_id)
        for name, claimed_n, claimed_bm25, claimed_ranker in claims:
            ids = groups.get(name, [])
            check(f"{scale} {name}: n", claimed_n, len(ids), 0)
            check(f"{scale} {name}: bm25", claimed_bm25,
                  statistics.fmean(res[i]["bm25"] for i in ids), 0.002)
            check(f"{scale} {name}: ranker", claimed_ranker,
                  statistics.fmean(res[i]["ltr"] for i in ids), 0.002)

    print("\n== scale check on 2,232 tasks (Table 7) ==")
    full = {row["instance_id"]: row for row in
            (json.loads(x) for x in (ROOT / "data" / "combo_ltr_full.jsonl").open(encoding="utf-8") if x.strip())}
    check("scorable tasks", 2232, len(full), 0)
    for arm, claimed in (("bm25", 0.248), ("ltr", 0.361), ("ltr_ev5", 0.359)):
        check(f"{arm} r@10", claimed, statistics.fmean(row[arm] for row in full.values()), 0.002)
    full_deltas = [full[key]["ltr"] - full[key]["bm25"] for key in full]
    check("ranker delta", 0.113, statistics.fmean(full_deltas), 0.002)
    check("ranker wins", 488, sum(1 for value in full_deltas if value > 0), 0)
    check("ranker losses", 123, sum(1 for value in full_deltas if value < 0), 0)
    check("override delta", -0.002,
          statistics.fmean(full[key]["ltr_ev5"] - full[key]["ltr"] for key in full), 0.002)

    full_rows = [json.loads(x) for x in
                 (ROOT / "data" / "features_full.jsonl").open(encoding="utf-8") if x.strip()]
    bm25_symbol, rerank_symbol = [], []
    bm25_file, rerank_file = [], []
    for task in full_rows:
        labels, files = task["labels"], task["files"]
        total, gold_files = task.get("gold_total") or sum(labels), task.get("gold_files") or []
        if not total:
            continue
        order = list(range(len(labels)))
        bm25_symbol.append(sum(1 for i in order[:10] if labels[i]) / total)
        rerank_symbol.append(sum(1 for i in task["rerank_top10"][:10] if labels[i]) / total)
        if gold_files:
            bm25_file.append(recall_files(order, files, gold_files))
            rerank_file.append(recall_files(task["rerank_top10"], files, gold_files))
    check("bm25 symbol", 0.248, statistics.fmean(bm25_symbol), 0.002)
    check("bm25 file", 0.564, statistics.fmean(bm25_file), 0.002)
    check("graph symbol", 0.270, statistics.fmean(rerank_symbol), 0.002)
    check("graph file", 0.564, statistics.fmean(rerank_file), 0.002)
    check("gap", 2.28, statistics.fmean(bm25_file) / statistics.fmean(bm25_symbol), 0.005,
          fmt="{:.2f}")
    graph_delta = [a - b for a, b in zip(rerank_symbol, bm25_symbol)]
    check("graph symbol delta", 0.022, statistics.fmean(graph_delta), 0.002)
    check("graph wins", 169, sum(1 for value in graph_delta if value > 0), 0)
    check("graph losses", 90, sum(1 for value in graph_delta if value < 0), 0)
    graph_file_delta = [a - b for a, b in zip(rerank_file, bm25_file)]
    check("graph file delta", 0.000, statistics.fmean(graph_file_delta), 0.002)

    orders = {row["instance_id"]: row for row in
              (json.loads(x) for x in (ROOT / "data" / "combo_ltr_orders_full.jsonl").open(encoding="utf-8") if x.strip())}
    files_of = {task["instance_id"]: task["files"] for task in full_rows}
    gold_of = {task["instance_id"]: task.get("gold_files") or [] for task in full_rows}
    for arm, claimed in (("ltr", 0.643),):
        values = [recall_files(row["orders"][arm], files_of[key], gold_of[key])
                  for key, row in orders.items() if key in files_of and gold_of.get(key)]
        check(f"{arm} file r@10", claimed, statistics.fmean(values), 0.002)

    print("\n== budget decomposition and the file vote ==")
    ff = [json.loads(x) for x in (ROOT / "data" / "experiment_ff.jsonl").open(encoding="utf-8") if x.strip()]
    ff = [row for row in ff if row.get("arms")]
    fr = [json.loads(x) for x in (ROOT / "data" / "experiment_fr2.jsonl").open(encoding="utf-8") if x.strip()]
    fr = [row for row in fr if row.get("arms")]
    for arm, claimed in (("ff_k1", 0.236), ("ff_k2", 0.268), ("ff_k3", 0.257),
                         ("ff_k5", 0.241), ("file_oracle", 0.665)):
        value = statistics.fmean(row["arms"][arm]["recall@10"] for row in ff)
        check(f"{arm} r@10", claimed, value, 0.001)
    probability = {
        "ff_k1": sum(1 for r in ff if r["stage1"]["gold_file_rank_3"] == 1) / len(ff),
        "ff_k2": sum(1 for r in ff if 1 <= r["stage1"]["gold_file_rank_3"] <= 2) / len(ff),
        "ff_k3": sum(1 for r in ff if 1 <= r["stage1"]["gold_file_rank_3"] <= 3) / len(ff),
        "ff_k5": sum(1 for r in ff if 1 <= r["stage1"]["gold_file_rank_5"] <= 5) / len(ff),
    }
    for arm, claimed in (("ff_k1", 0.290), ("ff_k2", 0.459), ("ff_k3", 0.503),
                         ("ff_k5", 0.586)):
        check(f"{arm} P(gold file found)", claimed, probability[arm], 0.002)
    for arm, claimed in (("ff_k1", 0.222), ("ff_k2", 0.268), ("ff_k3", 0.257),
                         ("ff_k5", 0.241)):
        subset = [row for row in ff if row["stage1"]["gold_file_rank_3" if arm != "ff_k5" else "gold_file_rank_5"]
                  == 0 or False]
        # product = P x recovery, recomputed the same way `tools/decompose.py` does
        key = "gold_file_rank_5" if arm == "ff_k5" else "gold_file_rank_3"
        limit = {"ff_k1": 1, "ff_k2": 2, "ff_k3": 3, "ff_k5": 5}[arm]
        subset = [row for row in ff if 1 <= row["stage1"][key] <= limit]
        recovery = statistics.fmean(row["arms"][arm]["recall@10"] for row in subset)
        check(f"{arm} P x recovery", claimed, probability[arm] * recovery, 0.002)

    top1 = {signal: sum(row["stage1"][signal]["top1"] for row in fr) / len(fr)
            for signal in ("max", "sum3", "path", "ppr", "borda", "borda_nop")}
    check("file top-1, best symbol", 0.290, top1["max"], 0.002)
    check("file top-1, lexical vote", 0.345, top1["borda_nop"], 0.002)
    check("file top-1, vote with PageRank", 0.348, top1["borda"], 0.002)
    for arm, claimed, p_claim in (("fr_mix_nop", 0.305, 0.031), ("fr_borda_mix", 0.300, 0.049)):
        value = statistics.fmean(row["arms"][arm]["recall@10"] for row in fr)
        check(f"{arm} r@10", claimed, value, 0.001)
        stats = paired(fr, "recall@10", arm)
        check(f"{arm} p", p_claim, round(stats["sign_p"], 3), 0.001)
    chars = statistics.fmean(row["arms"]["fr_mix_nop"]["chars@10"] for row in fr)
    check("fr_mix_nop characters", 1579, chars, 1, fmt="{:.0f}")

    print("\n== line-level coverage ==")
    from tools.line_coverage import anchor_symbols  # noqa: PLC0415
    records = {row["instance_id"]: row for row in gold}
    total_lines = covered = outside = 0
    for row in scored:
        record = records.get(row["instance_id"])
        if record is None:
            continue
        mapped, _ = anchor_symbols(record)
        if not mapped:
            continue
        top = set(row["arms"]["text"]["top"][:10])
        total_lines += len(mapped)
        outside += sum(1 for node in mapped if node is None)
        covered += sum(1 for node in mapped if node is not None and node in top)
    check("changed lines", 1010, total_lines, 0)
    check("lines inside a definition", 936, total_lines - outside, 0)
    check("line coverage, all", 0.239, covered / total_lines, 0.001)
    check("line coverage, inside a definition", 0.258,
          covered / (total_lines - outside), 0.001)

    print("\n== the draft still says the same thing ==")
    for token in ("62.4%", "27.5%", "2.3×", "0.42%", "3.1%", "11.9", "35.7",
                  "9,855", "44%", "46%", "seven to one",
                  "66.5%", "0.361", "0.332", "p = 0.035",
                  "22.8%", "17.2%", "41.7%", "23.9%",
                  "2,232", "2.28×", "0.564", "0.248", "0.113", "0.643",
                  "0.776", "0.755", "0.659", "27.8", "29.4", "29.6"):
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
