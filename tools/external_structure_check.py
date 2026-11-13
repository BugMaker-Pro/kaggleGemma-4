"""Label-free structure replication on 62 held-out tasks that never entered
any prior experiment.

Protocol (frozen before inspecting any held-out structural value):
  docs/experiments/heldout-structure-replication.md

The 62 tasks come from swebench_full.jsonl minus features_full.jsonl. They were
excluded by tools/features.py because their reference patches resolve to no
symbol. This script therefore NEVER reads patch, test_patch, FAIL_TO_PASS,
PASS_TO_PASS, labels, or any gold-derived field. It uses only the source
snapshot and the issue text to build a BM25 candidate pool, an AST projection,
five constrained rewired graphs, and the resulting top-10 shortlists.

Run:
  .venv/Scripts/python.exe tools/external_structure_check.py
  .venv/Scripts/python.exe tools/external_structure_check.py --smoke 1
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from scipy.stats import fisher_exact, spearmanr

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.buildgraph import build_graph, read_snapshot  # noqa: E402
from experiments.graph_controls import (adjacency, projection, promote,  # noqa: E402
                                        reachable, rewire)
from experiments.retrieve import BM25, document_text  # noqa: E402
from experiments.snapindex import SnapshotIndex  # noqa: E402

EXPECTED_HASHES = {
    'data/swebench_full.jsonl':
        '6c7bf5df9130e1f0acfd1654b267b9d79e8d86c9c1c1bd7c5a83bdf828198d9b',
    'data/features_full.jsonl':
        '1bdb47063949bd67ca68e651a05bc989e282bf6fbac54b1f3a74ea20d782b2b4',
    'data/graph_controls.jsonl':
        'b89bb12bcab3c5f381ba271c8b2b876d491434bb85ae4f5c5681a9c2fa0560df',
}
TASK_FIELDS = ('instance_id', 'repo', 'base_commit', 'problem_statement')
SEEDS = (11, 23, 37, 51, 71)
BOOTSTRAP = 10_000
SEED = 20261109
OUT_JSON = ROOT / 'data' / 'external_structure_check.json'
OUT_ROWS = ROOT / 'data' / 'heldout_structure_rows.jsonl'

_REPOS: str | None = None


def sha256(relative: str) -> str:
    value = hashlib.sha256()
    with (ROOT / relative).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def load_jsonl(relative: str) -> list[dict]:
    out = []
    with (ROOT / relative).open(encoding='utf-8-sig') as handle:
        for line in handle:
            if line.strip():
                out.append(json.loads(line))
    return out


def jaccard_dispersion(sets: list[set[int]]) -> float:
    values = [1.0 - len(a & b) / len(a | b)
              for a, b in itertools.combinations(sets, 2)]
    return float(sum(values) / len(values))


def one_task(task: dict) -> dict:
    """Build everything from source snapshot + issue text only. No patch, no gold."""
    assert _REPOS is not None
    path = SnapshotIndex(_REPOS).path_for(task)
    if path is None:
        raise FileNotFoundError(task['instance_id'])
    files = read_snapshot(path)
    graph, _ = build_graph(files)
    nodes = graph.nodes
    docs = {node_id: document_text(node) for node_id, node in nodes.items()}
    ranked = BM25(docs).search(task.get('problem_statement') or '', 200)
    pool = [node_id for node_id, _ in ranked]
    cand_files = [nodes[i].get('file', '') for i in pool]
    edges = projection(graph.edges, pool)
    order = list(range(len(pool)))
    base = order[:10]
    real = promote(order, reachable(order, adjacency(edges)))
    rewired = []
    for seed in SEEDS:
        randomized, _ = rewire(edges, cand_files, task['instance_id'], seed, False)
        rewired.append(promote(order, reachable(order, adjacency(randomized))))
    d = jaccard_dispersion([set(r) for r in rewired])
    return {
        'instance_id': task['instance_id'],
        'repo': task['repo'],
        'D': d,
        'D_zero': bool(d == 0),
        'in_null': bool(tuple(real) in {tuple(r) for r in rewired}),
        'unchanged': bool(real == base),
        'churn': len(set(real) - set(base)),
        'pool_size': len(pool),
        'edges': len(edges),
    }


def init_worker(repos: str) -> None:
    global _REPOS
    _REPOS = repos


def holm(pvals: dict[str, float]) -> dict[str, float]:
    keys = list(pvals)
    order = np.argsort([pvals[k] for k in keys])
    adjusted, running = {}, 0.0
    for rank_pos, i in enumerate(order):
        running = max(running, (len(keys) - rank_pos) * pvals[keys[i]])
        adjusted[keys[i]] = min(1.0, running)
    return adjusted


def odds_ratio(table: list[list[int]]) -> float:
    a, b, c, d = (float(v) for row in table for v in row)
    if min(a, b, c, d) == 0:
        a, b, c, d = a + .5, b + .5, c + .5, d + .5
    return (a * d) / (b * c)


def main_baseline(controls_path: str) -> dict:
    """Recompute the already-public structural baseline on the 2,232 main tasks."""
    d_vals, in_null, unchanged = [], [], []
    with (ROOT / controls_path).open(encoding='utf-8') as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            arms = row['representations']['metadata']['arms']
            rew = [arms[f'rewired_{s}']['top10'] for s in SEEDS]
            d_vals.append(jaccard_dispersion([set(r) for r in rew]))
            in_null.append(tuple(arms['real']['top10']) in {tuple(r) for r in rew})
            unchanged.append(arms['real']['top10'] == arms['base']['top10'])
    d = np.asarray(d_vals)
    return {
        'n': len(d),
        'D_mean': float(d.mean()), 'D_median': float(np.median(d)),
        'D_nonzero': float((d > 0).mean()), 'D_zero': float((d == 0).mean()),
        'in_null': float(np.mean(in_null)), 'unchanged': float(np.mean(unchanged)),
        'D_zero_subset': {
            'n': int((d == 0).sum()),
            'in_null': float(np.mean(np.asarray(in_null)[d == 0])),
            'unchanged': float(np.mean(np.asarray(unchanged)[d == 0])),
        },
        'D_positive_subset': {
            'n': int((d > 0).sum()),
            'in_null': float(np.mean(np.asarray(in_null)[d > 0])),
            'unchanged': float(np.mean(np.asarray(unchanged)[d > 0])),
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke', type=int, default=0,
                        help='run only N tasks to verify the code path; '
                             'prints field types only, writes no output')
    parser.add_argument('--jobs', type=int, default=6)
    args = parser.parse_args(argv)

    for relative, expected in EXPECTED_HASHES.items():
        actual = sha256(relative)
        if actual != expected:
            print(f'ERROR: {relative} hash mismatch\n  expected {expected}\n  actual   {actual}')
            return 1
    print('input hashes: OK')

    used = {row['instance_id'] for row in load_jsonl('data/features_full.jsonl')}
    full = load_jsonl('data/swebench_full.jsonl')
    # Field whitelist: patch / test_patch / F2P / P2P are deliberately dropped.
    heldout = [{k: row.get(k) for k in TASK_FIELDS}
               for row in full if row['instance_id'] not in used]
    heldout.sort(key=lambda r: r['instance_id'])
    print(f'held-out tasks: {len(heldout)} (full {len(full)}, used {len(used)})')
    if len(heldout) != 62:
        print('ERROR: held-out population changed; protocol no longer applies')
        return 1

    repos = str(ROOT / 'data' / 'repos')
    if args.smoke:
        init_worker(repos)
        ok = 0
        for task in heldout[:args.smoke]:
            row = one_task(task)
            print('smoke', task['instance_id'], 'fields',
                  {k: type(v).__name__ for k, v in row.items()})
            ok += 1
        print(f'smoke complete: {ok} task(s), code path OK; no structural values printed')
        return 0

    results, errors = [], []
    with ProcessPoolExecutor(max_workers=args.jobs,
                             initializer=init_worker, initargs=(repos,)) as pool:
        jobs = {pool.submit(one_task, t): t['instance_id'] for t in heldout}
        for future in as_completed(jobs):
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append({'instance_id': jobs[future],
                               'error': f'{type(exc).__name__}: {exc}'})
    results.sort(key=lambda r: r['instance_id'])
    print(f'built {len(results)}/{len(heldout)} tasks; failures {len(errors)}')
    if errors:
        for e in errors[:10]:
            print('  FAILED', e['instance_id'], e['error'])
        OUT_JSON.write_text(json.dumps({
            'status': 'INCOMPLETE', 'protocol':
            'docs/experiments/heldout-structure-replication.md',
            'errors': errors,
            'verdict': '未完成：按冻结协议，任一任务建池/建图失败即整轮不下结论',
        }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return 1

    d = np.asarray([r['D'] for r in results], dtype=float)
    zero = np.asarray([r['D_zero'] for r in results], dtype=bool)
    in_null = np.asarray([r['in_null'] for r in results], dtype=bool)
    unchanged = np.asarray([r['unchanged'] for r in results], dtype=bool)
    churn = np.asarray([r['churn'] for r in results], dtype=float)
    base = main_baseline('data/graph_controls.jsonl')

    # ---- primary: two Fisher exact tests, direction fixed in advance ----
    raw_p, tests = {}, {}
    for name, column in (('R1', in_null), ('R2', unchanged)):
        table = [[int((zero & column).sum()), int((zero & ~column).sum())],
                 [int((~zero & column).sum()), int((~zero & ~column).sum())]]
        odds, p = fisher_exact(table, alternative='greater')
        raw_p[name] = float(p)
        fisher_or = float(odds) if np.isfinite(odds) else None
        tests[name] = {
            'table_rows': ['D==0', 'D>0'], 'table_cols': ['1', '0'],
            'table': table,
            'rate_D_zero': round(table[0][0] / max(1, sum(table[0])), 6),
            'rate_D_positive': round(table[1][0] / max(1, sum(table[1])), 6),
            'odds_ratio_fisher': None if fisher_or is None else round(fisher_or, 6),
            'odds_ratio_fisher_note': ('undefined (zero cell); Haldane-corrected OR used'
                                       if fisher_or is None else None),
            'odds_ratio_haldane': round(odds_ratio(table), 6),
            'p_raw': float(p),
            'p_raw_display': f'{p:.3e}',
        }
    adjusted = holm(raw_p)
    for name in tests:
        tests[name]['p_holm'] = float(adjusted[name])
        tests[name]['p_holm_display'] = f'{adjusted[name]:.3e}'
        tests[name]['passes'] = bool(adjusted[name] < 0.05
                                     and odds_ratio(tests[name]['table']) > 1)

    # ---- P1: cluster bootstrap of the difference against the main baseline ----
    repos_list = sorted({r['repo'] for r in results})
    repo_index = np.asarray([repos_list.index(r['repo']) for r in results])
    clusters = [np.flatnonzero(repo_index == i) for i in range(len(repos_list))]
    held_stats = {
        'D_mean': float(d.mean()), 'D_median': float(np.median(d)),
        'D_nonzero': float((d > 0).mean()), 'D_zero': float(zero.mean()),
    }
    rng = np.random.default_rng(SEED)
    history = {k: [] for k in held_stats}
    for _ in range(BOOTSTRAP):
        pick = rng.integers(0, len(repos_list), len(repos_list))
        idx = np.concatenate([clusters[i] for i in pick])
        sd = d[idx]
        for k, v in (('D_mean', float(sd.mean())), ('D_median', float(np.median(sd))),
                     ('D_nonzero', float((sd > 0).mean())),
                     ('D_zero', float((sd == 0).mean()))):
            history[k].append(v - base[k])
    p1 = {}
    for k in held_stats:
        arr = np.asarray(history[k])
        lo90, hi90 = np.percentile(arr, [5, 95])
        lo95, hi95 = np.percentile(arr, [2.5, 97.5])
        p1[k] = {
            'heldout': round(held_stats[k], 6),
            'main_baseline': round(base[k], 6),
            'difference': round(held_stats[k] - base[k], 6),
            'ci90': [round(float(lo90), 6), round(float(hi90), 6)],
            'ci95': [round(float(lo95), 6), round(float(hi95), 6)],
            'crosses_zero': bool(lo95 <= 0 <= hi95),
        }

    # ---- P4 / P5: descriptive only ----
    rho_raw = float(spearmanr(d, churn).statistic)
    rho = None if not np.isfinite(rho_raw) else round(rho_raw, 6)
    p4 = {
        'in_null_rate': round(float(in_null.mean()), 6),
        'unchanged_rate': round(float(unchanged.mean()), 6),
        'churn_mean': round(float(churn.mean()), 6),
        'churn_zero_fraction': round(float((churn == 0).mean()), 6),
        'spearman_D_churn': round(rho, 6),
        'pool_size_min': int(min(r['pool_size'] for r in results)),
        'pool_size_max': int(max(r['pool_size'] for r in results)),
        'edges_mean': round(statistics.fmean(r['edges'] for r in results), 3),
    }
    p5 = []
    for repo in repos_list:
        mask = np.asarray([r['repo'] == repo for r in results])
        p5.append({'repo': repo, 'n': int(mask.sum()),
                   'D_zero_rate': round(float(zero[mask].mean()), 6),
                   'in_null_rate': round(float(in_null[mask].mean()), 6),
                   'unchanged_rate': round(float(unchanged[mask].mean()), 6)})

    all_pass = all(tests[k]['passes'] for k in tests)
    if all_pass:
        code = 'REPLICATED_ON_UNSEEN_TASKS'
        verdict = ('在 62 个从未进入既有实验的留出任务上，两个 label-free 结构关联方向复现；'
                   '这是同仓库新任务集上的复现检验，不是外部验证，'
                   '且与任何金标/干预收益结论无关。')
    else:
        code = 'NOT_REPLICATED'
        verdict = ('结构关联在未见任务集上未复现；只报四个格子的计数与区间，'
                   '不给机制解释、不改列定义、不换随机种子或表示重跑。')

    out = {
        'protocol': 'docs/experiments/heldout-structure-replication.md',
        'status': 'COMPLETE',
        'inputs': {k: {'sha256': v, 'verified': True} for k, v in EXPECTED_HASHES.items()},
        'population': {
            'full_tasks': len(full), 'used_tasks': len(used),
            'heldout_tasks': len(results), 'heldout_repos': len(repos_list),
            'field_whitelist': list(TASK_FIELDS),
            'forbidden_fields_verified': ['patch', 'test_patch', 'FAIL_TO_PASS',
                                          'PASS_TO_PASS', 'labels', 'gold_*'],
            'selection_bias': 'held-out tasks are exactly those whose reference patch '
                              'resolves to no symbol; same 12 repositories, NOT new repos',
        },
        'main_baseline': {k: (round(v, 6) if isinstance(v, float) else v)
                          for k, v in base.items() if not isinstance(v, dict)},
        'main_baseline_subsets': {k: v for k, v in base.items() if isinstance(v, dict)},
        'primary_tests': {
            'method': 'one-sided Fisher exact (greater), Holm over two tests',
            'tests': tests, 'all_pass': bool(all_pass),
        },
        'P1_distribution': {'bootstrap': BOOTSTRAP, 'seed': SEED,
                            'unit': 'repo cluster', 'stats': p1},
        'P4_descriptive': p4,
        'P5_by_repo': p5,
        'verdict': {
            'code': code, 'text': verdict,
            'new_repositories': False, 'external_validation': False,
            'independent_replication': False,
            'any_gold_or_delta_claim': False,
            'eligible_for_submission': False,
            'paper_or_writeup_modified': False,
        },
    }
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    with OUT_ROWS.open('w', encoding='utf-8', newline='\n') as handle:
        for row in results:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')

    print('\nmain baseline:', {k: round(v, 4) for k, v in base.items()
                               if isinstance(v, float)})
    for name in ('R1', 'R2'):
        t = tests[name]
        print(f'{name}: table={t["table"]} OR_haldane={t["odds_ratio_haldane"]} '
              f'p_raw={t["p_raw_display"]} p_holm={t["p_holm_display"]} '
              f'pass={t["passes"]}')
    for k, v in p1.items():
        print(f'P1 {k:10s} held={v["heldout"]:.4f} base={v["main_baseline"]:.4f} '
              f'diff={v["difference"]:+.4f} CI95={v["ci95"]}')
    print('\nverdict:', code)
    print(verdict)
    print('\nwrote', OUT_JSON.relative_to(ROOT).as_posix(),
          'and', OUT_ROWS.relative_to(ROOT).as_posix())
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass
    raise SystemExit(main())
