"""Can a better *file* ranking make file-first win? Four signals and one Borda vote.

`run_filefirst.py` showed the gap is not inside the file: given the right file,
ten BM25 slots recover 66.5% of gold symbols. What it also showed is that the
file ranking we used (best symbol score) names the gold file first only 29% of
the time. This pass tries to raise that number with signals a practitioner would
have on hand, and then runs file-first again on top of the best ranking.

File signals, each computed per task:
  max    highest symbol score in the file                      (the baseline)
  sum3   sum of the three highest symbol scores                (consistency beats one hit)
  path   IDF-weighted match between issue tokens and path tokens
  ppr    file-level PageRank over call/import/inherit edges, seeded by the
         text scores of the top twenty symbols

The combination is a Borda count over reciprocal ranks — no weights to tune, so
nothing here can be accused of being fitted to the test set.

Arms: the four rankings at depth 10 (all slots in the top file), the Borda
ranking at depth 10 and depth 5, and a half-and-half mix with plain text.

    python tools/run_filerank.py --jobs 6 --out data/experiment_fr.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.buildgraph import build_graph, read_snapshot  # noqa: E402
from experiments.gold import DictSnapshot, build_record  # noqa: E402
from experiments.retrieve import BM25, document_text, tokenize  # noqa: E402
from experiments.snapindex import SnapshotIndex  # noqa: E402
from tools.run_experiment import target_ids  # noqa: E402
from tools.run_filefirst import _arm, _file_graph, _file_scores, _fill  # noqa: E402

_INDEX: SnapshotIndex | None = None
_POOL = 200
_KEEP = 50
_TOP_FILES = 50      # files considered per signal before the Borda vote
_RESTART = 0.15


def _init(repos: str, pool: int = 200) -> None:
    global _INDEX, _POOL
    _INDEX = SnapshotIndex(repos)
    _POOL = pool


def _file_ppr(file_adj: dict[str, set[str]], seed_mass: dict[str, float],
              restart: float = _RESTART, iterations: int = 30) -> dict[str, float]:
    """PageRank over files, seeded with the text mass of their best symbols."""
    total = sum(seed_mass.values()) or 1.0
    seed = {path: mass / total for path, mass in seed_mass.items()}
    scores = dict(seed)
    for _ in range(iterations):
        nxt: dict[str, float] = defaultdict(float)
        dangling = 0.0
        for path, mass in scores.items():
            adjacent = file_adj.get(path)
            if not adjacent:
                dangling += mass
                continue
            spread = restart * mass / len(adjacent)
            for neighbour in adjacent:
                nxt[neighbour] += spread
        for path, mass in nxt.items():
            nxt[path] = mass + (1 - restart) * seed.get(path, 0.0)
        for path, mass in seed.items():           # dead-end mass returns to seeds
            nxt[path] += dangling * (1 - restart) * mass
        delta = sum(abs(nxt.get(k, 0.0) - v) for k, v in scores.items())
        scores = dict(nxt)
        if delta < 1e-9:
            break
    return scores


def _path_scores(issue_tokens: set[str], files: list[str]) -> dict[str, float]:
    """Rare path tokens matched by the issue, weighted by how rare they are."""
    path_tokens: dict[str, set[str]] = {}
    df: dict[str, int] = defaultdict(int)
    for path in files:
        tokens = {tok.lower() for tok in tokenize(path.replace("/", " ").replace(".", " "))}
        tokens |= {part.lower() for part in path.replace(".py", "").split("/") if part}
        path_tokens[path] = tokens
        for token in tokens:
            df[token] += 1
    limit = max(len(files) // 20, 2)              # ignore tokens in >5% of files
    scores: dict[str, float] = {}
    for path, tokens in path_tokens.items():
        weight = 0.0
        for token in tokens & issue_tokens:
            if df[token] <= limit and len(token) > 2:
                weight += 1.0 / (1.0 + math.log(df[token]))
        scores[path] = weight / (len(tokens) or 1)
    return scores


def _borda(*rankings: list[str]) -> list[str]:
    """Mean reciprocal rank across signals; a file no signal likes scores zero."""
    score: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for position, path in enumerate(ranking, 1):
            score[path] += 1.0 / position
    return sorted(score, key=lambda path: (-score[path], path))


def _stage1_quality(order: list[str], gold_files: set[str]) -> dict:
    rank = next((i + 1 for i, path in enumerate(order) if path in gold_files), 0)
    return {"rank": rank, "top1": 1.0 if rank == 1 else 0.0,
            "top3": 1.0 if 0 < rank <= 3 else 0.0, "rr": 1.0 / rank if rank else 0.0}


def _work(task: dict) -> dict:
    assert _INDEX is not None
    started = time.time()
    path = _INDEX.path_for(task)
    if path is None:
        return {"instance_id": task["instance_id"], "error": "no_snapshot"}

    files = read_snapshot(path)
    graph, _stats = build_graph(files)
    nodes = graph.nodes
    record = build_record(task, None, snap=DictSnapshot(files))
    gold, unresolved = target_ids(record, set(nodes))
    row: dict = {"instance_id": task["instance_id"], "repo": task.get("repo", ""),
                 "gold_nodes": gold, "gold_unresolved": unresolved[:20], "seconds": 0.0}
    if not gold:
        row["seconds"] = round(time.time() - started, 2)
        return row

    docs = {node_id: document_text(node) for node_id, node in nodes.items()}
    bm25 = BM25(docs)
    query = task.get("problem_statement") or ""
    ranked = bm25.search(query, len(docs))
    ranked_ids = [node_id for node_id, _ in ranked]
    files_of = {node_id: node.get("file", "") for node_id, node in nodes.items()}
    gold_files = {entry["path"] for entry in record.get("files", [])
                  if entry.get("language") == "python"}
    targets = set(gold)

    by_file: dict[str, list[str]] = defaultdict(list)
    for node_id in ranked_ids:
        by_file[files_of.get(node_id, "")].append(node_id)

    max_order = [p for p, _ in _file_scores(ranked, files_of)]
    per_file: dict[str, list[float]] = defaultdict(list)
    for node_id, score in ranked[:2000]:
        per_file[files_of.get(node_id, "")].append(score)
    sum3 = {path_: sum(sorted(scores, reverse=True)[:3])
            for path_, scores in per_file.items() if path_}
    sum3_order = sorted(sum3, key=lambda p: (-sum3[p], p))

    issue_tokens = {t for t in tokenize(query) if len(t) > 2}
    path_scores = _path_scores(issue_tokens, max_order)
    path_order = sorted((p for p in path_scores if p), key=lambda p: (-path_scores[p], p))

    file_adj = _file_graph(graph, files_of)
    seed_mass: dict[str, float] = defaultdict(float)
    for node_id, score in ranked[:20]:
        seed_mass[files_of.get(node_id, "")] += score
    ppr_scores = _file_ppr(file_adj, {k: v for k, v in seed_mass.items() if k})
    ppr_order = sorted((p for p in ppr_scores if p), key=lambda p: (-ppr_scores[p], p))

    borda = _borda(max_order[:_TOP_FILES], sum3_order[:_TOP_FILES],
                   path_order[:_TOP_FILES], ppr_order[:_TOP_FILES])

    arms: dict[str, dict] = {"text": _arm(ranked_ids, targets, gold_files, nodes, files_of)}
    for name, order in (("fr_max", max_order), ("fr_sum3", sum3_order),
                        ("fr_path", path_order), ("fr_ppr", ppr_order),
                        ("fr_borda", borda)):
        selected = order[:1]
        filled = _fill(selected, by_file, ranked_ids)
        filled += [n for n in ranked_ids if n not in set(filled)]
        arms[name] = _arm(filled, targets, gold_files, nodes, files_of)

    filled = _fill(borda[:2], by_file, ranked_ids)
    filled += [n for n in ranked_ids if n not in set(filled)]
    arms["fr_borda_k2"] = _arm(filled, targets, gold_files, nodes, files_of)

    mixed = list(arms["fr_borda"]["top"][:5])
    seen = set(mixed)
    for node_id in ranked_ids:
        if len(mixed) >= 10:
            break
        if node_id not in seen:
            mixed.append(node_id)
            seen.add(node_id)
    mixed += [n for n in ranked_ids if n not in set(mixed)]
    arms["fr_borda_mix"] = _arm(mixed, targets, gold_files, nodes, files_of)

    # Ablations, so "the graph contributes" is evidence rather than inference:
    # a vote without the file-level PageRank signal, and a vote without the
    # (individually useless) path signal. Same arms as above, same budget.
    borda_nop = _borda(max_order[:_TOP_FILES], sum3_order[:_TOP_FILES],
                       path_order[:_TOP_FILES])
    borda_nopath = _borda(max_order[:_TOP_FILES], sum3_order[:_TOP_FILES],
                          ppr_order[:_TOP_FILES])
    for name, vote in (("nop", borda_nop), ("nopath", borda_nopath)):
        filled = _fill(vote[:1], by_file, ranked_ids)
        filled += [n for n in ranked_ids if n not in set(filled)]
        arms[f"fr_borda_{name}"] = _arm(filled, targets, gold_files, nodes, files_of)
        blend = list(arms[f"fr_borda_{name}"]["top"][:5])
        seen = set(blend)
        for node_id in ranked_ids:
            if len(blend) >= 10:
                break
            if node_id not in seen:
                blend.append(node_id)
                seen.add(node_id)
        blend += [n for n in ranked_ids if n not in set(blend)]
        arms[f"fr_mix_{name}"] = _arm(blend, targets, gold_files, nodes, files_of)

    row["arms"] = arms
    row["stage1"] = {
        "max": _stage1_quality(max_order, gold_files),
        "sum3": _stage1_quality(sum3_order, gold_files),
        "path": _stage1_quality(path_order, gold_files),
        "ppr": _stage1_quality(ppr_order, gold_files),
        "borda": _stage1_quality(borda, gold_files),
        "borda_nop": _stage1_quality(borda_nop, gold_files),
        "borda_nopath": _stage1_quality(borda_nopath, gold_files),
    }
    row["seconds"] = round(time.time() - started, 2)
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_lite.jsonl"))
    ap.add_argument("--repos", default=str(ROOT / "data" / "repos"))
    ap.add_argument("--out", default=str(ROOT / "data" / "experiment_fr.jsonl"))
    ap.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1))
    ap.add_argument("--pool", type=int, default=200)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip()]
    if args.limit:
        tasks = tasks[: args.limit]

    started = time.time()
    rows: list[dict] = []
    failures = 0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w", encoding="utf-8") as fh, ProcessPoolExecutor(
        max_workers=args.jobs, initializer=_init, initargs=(args.repos, args.pool)
    ) as pool:
        futures = {pool.submit(_work, task): task for task in tasks}
        for done, future in enumerate(as_completed(futures), 1):
            try:
                row = future.result()
            except Exception as exc:  # noqa: BLE001
                task = futures[future]
                row = {"instance_id": task["instance_id"],
                       "error": f"{type(exc).__name__}: {exc}"}
            if "error" in row:
                failures += 1
                print(f"  FAIL {row['instance_id']}: {row['error']}", flush=True)
            else:
                rows.append(row)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
            if done % 10 == 0 or done == len(tasks):
                elapsed = time.time() - started
                rate = done / elapsed
                print(f"  {done}/{len(tasks)}  {rate:.2f} task/s  "
                      f"eta {(len(tasks) - done) / max(rate, 1e-9) / 60:.1f} min", flush=True)

    with out.open("w", encoding="utf-8") as fh:
        for row in sorted(rows, key=lambda r: r["instance_id"]):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    scored = [row for row in rows if row.get("arms")]
    print(f"\ntasks {len(rows)} scored {len(scored)} failures {failures} "
          f"{round(time.time() - started, 1)}s")
    print(f"{'arm':16s}{'r@1':>7s}{'r@5':>7s}{'r@10':>7s}{'file@10':>9s}")
    for arm in ("text", "fr_max", "fr_sum3", "fr_path", "fr_ppr", "fr_borda",
                "fr_borda_k2", "fr_borda_mix", "fr_borda_nop", "fr_mix_nop",
                "fr_borda_nopath", "fr_mix_nopath"):
        def mean(metric):
            return sum(row["arms"][arm][metric] for row in scored) / len(scored)
        print(f"{arm:16s}{mean('recall@1'):7.3f}{mean('recall@5'):7.3f}"
              f"{mean('recall@10'):7.3f}{mean('file_recall@10'):9.3f}")
    print("\nstage 1 quality (gold file):")
    for signal in ("max", "sum3", "path", "ppr", "borda", "borda_nop", "borda_nopath"):
        top1 = sum(row["stage1"][signal]["top1"] for row in scored) / len(scored)
        top3 = sum(row["stage1"][signal]["top3"] for row in scored) / len(scored)
        mrr = sum(row["stage1"][signal]["rr"] for row in scored) / len(scored)
        print(f"  {signal:8s} top1 {top1:.3f}  top3 {top3:.3f}  mrr {mrr:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
