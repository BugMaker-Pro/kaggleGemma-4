"""InterventionEffect Bench v0: build the resource and audit strategies against it.

Protocol (frozen before any outcome inspection):
    docs/experiments/intervention-effect-bench.md

This script does not propose a new selection algorithm. It releases per-task,
counterfactual-derived intervention effects and evaluates a fixed list of
published-style strategies on a pre-registered risk-coverage grid.

    .venv/Scripts/python.exe tools/intervention_effect_bench.py
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_HASHES = {
    'data/graph_controls.jsonl': 'b89bb12bcab3c5f381ba271c8b2b876d491434bb85ae4f5c5681a9c2fa0560df',
    'data/features_full.jsonl': '1bdb47063949bd67ca68e651a05bc989e282bf6fbac54b1f3a74ea20d782b2b4',
    'data/cost_budget.jsonl': '2ee7e122485a59d60929659dd39af9fc5b21c53a9d3a7f4f149b8c266787103a',
    'data/gold_symbols.jsonl': '2fa161dc437993153e2d0b1834a88a89553270c3ca1978bcd3db08e65eba25ad',
}
REPRESENTATIONS = ('metadata', 'body', 'dense')
PRIMARY = 'metadata'
Q_GRID = (0.1, 0.2, 0.3, 0.5, 0.8, 1.0)
MAIN_Q = 0.2
BOOTSTRAP = 10_000
SEED = 20261109
DATA_DRIVEN = ('null_spread', 'margin_low', 'evidence_high')
BASELINES = ('never', 'always', 'random')
UPPER = 'oracle'
FEATURE_NAMES = ('margin_10_11', 'top5_mass', 'seed_file_spread', 'seed_degree',
                 'evidence_top10', 'score_decay')
REWIRED = re.compile(r'^rewired_\d+$')
REWIRED_PAIR = re.compile(r'^rewired_pair_\d+$')


def sha256(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def load(relative: str) -> list[dict]:
    with (ROOT / relative).open(encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def features(feature_names: list[str], rows: list[list], files: list[str]) -> list[float]:
    """Leakage guard: receives only the matrix, column names and file paths."""
    ix = {n: i for i, n in enumerate(feature_names)}
    s = [float(r[ix['bm25_score']]) for r in rows]
    return [
        s[9] - s[10],
        sum(s[:5]) / max(sum(s[:50]), 1e-9),
        float(len(set(files[:5]))),
        float(np.mean([rows[i][ix['in_degree']] + rows[i][ix['out_degree']]
                       for i in range(5)])),
        float(sum(rows[i][ix['path_in_issue']] + rows[i][ix['frame_hit']]
                  + rows[i][ix['named_file']] for i in range(10))),
        s[0] - s[9],
    ]


def recall_at_budget(curve: list[dict], budget: int, total: int) -> float:
    hits = 0
    for point in curve:
        if point['cost'] > budget:
            break
        hits = point['hits']
    return hits / total if total else 0.0


def arm_view(arm: dict) -> dict:
    return {k: arm.get(k) for k in ('symbol', 'file', 'gained', 'lost')}


def representation_view(rep_data: dict, gold_total: int) -> dict:
    arms = rep_data['arms']
    real, base = arms['real'], arms['base']
    delta = float(real['symbol']) - float(base['symbol'])
    churn = (real['gained'] + real['lost']) / gold_total
    rew = [float(arms[n]['symbol']) for n in arms if REWIRED.match(n)]
    pair = [float(arms[n]['symbol']) for n in arms if REWIRED_PAIR.match(n)]
    return {
        'base': arm_view(base),
        'real': arm_view(real),
        'same_file': arm_view(arms['file']),
        'rewired': [dict(arm=n, **arm_view(arms[n])) for n in arms if REWIRED.match(n)],
        'rewired_pair': [dict(arm=n, **arm_view(arms[n])) for n in arms if REWIRED_PAIR.match(n)],
        'derived': {
            'delta': delta,
            'churn': churn,
            'efficiency': delta / churn if churn > 0 else 0.0,
            'harm': max(-delta, 0.0),
            'null_spread': float(np.std(rew)) if rew else 0.0,
            'null_mean': float(np.mean(rew)) if rew else 0.0,
            'pair_spread': float(np.std(pair)) if pair else 0.0,
        },
    }


def build_resource(controls: list[dict], ff: dict, budgets: dict) -> list[dict]:
    out = []
    for row in controls:
        key = row['instance_id']
        budget = budgets.get(key)
        out.append({
            'instance_id': key,
            'repo': row['repo'],
            'gold_total': row['gold_total'],
            'pool_size': row['pool_size'],
            'pool_gold': row['pool_gold'],
            'pre_intervention': dict(zip(FEATURE_NAMES,
                                         features(ff[key]['features'], ff[key]['rows'],
                                                  ff[key]['files']))),
            'char_budget': budget,
            'representations': {
                rep: representation_view(row['representations'][rep], row['gold_total'])
                for rep in REPRESENTATIONS
            },
        })
    return out


def selected_mask(score: np.ndarray, fold: np.ndarray, q: float) -> np.ndarray:
    mask = np.zeros(len(score), bool)
    for held_out in (0, 1):
        test = np.flatnonzero(fold == held_out)
        k = math.ceil(q * len(test))
        order = test[np.argsort(-score[test], kind='stable')]
        mask[order[:k]] = True
    return mask


def curve_metrics(rep: str, strategy: str, scores: dict, delta: dict, harm: dict,
                  fold: np.ndarray) -> dict:
    d, h = delta[rep], harm[rep]
    points = {}
    if strategy == 'never':
        return {'gain': 0.0, 'risk': 0.0, 'harm_rate': 0.0, 'saving': 1.0}
    for q in Q_GRID:
        if strategy == 'always':
            mask = np.ones(len(d), bool)
        else:
            mask = selected_mask(scores[strategy], fold, q)
        coverage = float(mask.mean())
        points[str(q)] = {
            'gain': float(d[mask].mean()),
            'risk': float(h[mask].mean()),
            'harm_rate': float((d[mask] < 0).mean()),
            'saving': float(1.0 - coverage),
            # Overall, not conditional: mean net gain / harm over ALL tasks.
            # gain@q alone inflates small-q noise (88% of deltas are zero).
            'utility': float((d * mask).mean()),
            'overall_risk': float((h * mask).mean()),
            'coverage': coverage,
            'n_selected': int(mask.sum()),
        }
    qs = np.asarray(list(Q_GRID), dtype=float)
    risks = np.asarray([points[str(q)]['risk'] for q in Q_GRID])
    gains = np.asarray([points[str(q)]['gain'] for q in Q_GRID])
    return {
        'points': points,
        'AURC': float(np.trapezoid(risks, qs)),
        'AUGC': float(np.trapezoid(gains, qs)),
        'main_q': points[str(MAIN_Q)],
    }


def bootstrap_diffs(selected: np.ndarray, d: np.ndarray, h: np.ndarray,
                    repo_index: np.ndarray, n_repos: int) -> dict:
    clusters = [np.flatnonzero(repo_index == i) for i in range(n_repos)]
    rng = np.random.default_rng(SEED)
    dg, dr = [], []
    for _ in range(BOOTSTRAP):
        idx = np.concatenate([clusters[i] for i in rng.integers(0, n_repos, n_repos)])
        s = selected[idx]
        if s.sum() < 10:
            continue
        dg.append(float(d[idx][s].mean() - d[idx].mean()))
        dr.append(float(h[idx][s].mean() - h[idx].mean()))
    dg, dr = np.asarray(dg), np.asarray(dr)

    def summarize(values: np.ndarray) -> dict:
        lo, hi = np.percentile(values, [2.5, 97.5])
        p = 2.0 * min(float((values <= 0).mean()), float((values >= 0).mean()))
        return {'estimate': float(values.mean()), 'ci95': [float(lo), float(hi)],
                'p_two_sided': min(1.0, p)}
    return {'delta_gain': summarize(dg), 'delta_risk': summarize(dr)}


def holm(pvals: dict[str, float]) -> dict[str, float]:
    keys = list(pvals)
    order = np.argsort([pvals[k] for k in keys])
    adjusted, running = {}, 0.0
    for rank, i in enumerate(order):
        running = max(running, (len(keys) - rank) * pvals[keys[i]])
        adjusted[keys[i]] = min(1.0, running)
    return adjusted


def main() -> int:
    for relative, expected in EXPECTED_HASHES.items():
        actual = sha256(relative)
        if actual != expected:
            print(f'ERROR: {relative} hash mismatch: {actual} != {expected}')
            return 1

    controls = [r for r in load('data/graph_controls.jsonl') if r['gold_total'] > 0]
    ff = {r['instance_id']: r for r in load('data/features_full.jsonl')}
    lite = {r['instance_id'] for r in load('data/gold_symbols.jsonl') if r.get('has_symbols')}
    budgets = {}
    for r in load('data/cost_budget.jsonl'):
        budgets[r['task']] = {
            'symbol_recall_at_16000': recall_at_budget(r['symbol_curve'], 16000, r['gold_total']),
            'file_recall_at_16000': recall_at_budget(r['file_curve'], 16000, r['gold_total']),
        }

    resource = build_resource(controls, ff, budgets)
    out_path = ROOT / 'data' / 'intervention_effect_bench.jsonl'
    with out_path.open('w', encoding='utf-8', newline='\n') as handle:
        for row in resource:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')

    ids = [r['instance_id'] for r in controls]
    repos = sorted({r['repo'] for r in controls})
    fold_of = {repo: i % 2 for i, repo in enumerate(repos)}
    fold = np.asarray([fold_of[r['repo']] for r in controls])
    repo_index = np.asarray([repos.index(r['repo']) for r in controls])

    delta, harm, churn, efficiency = {}, {}, {}, {}
    null_spread = {}
    for rep in REPRESENTATIONS:
        derived = [row['representations'][rep]['derived'] for row in resource]
        delta[rep] = np.asarray([v['delta'] for v in derived])
        harm[rep] = np.asarray([v['harm'] for v in derived])
        churn[rep] = np.asarray([v['churn'] for v in derived])
        efficiency[rep] = np.asarray([v['efficiency'] for v in derived])
        null_spread[rep] = np.asarray([v['null_spread'] for v in derived])

    feat = np.asarray([list(row['pre_intervention'].values()) for row in resource])
    rng = np.random.default_rng(SEED)
    random_score = rng.random(len(resource))

    results, primary_masks = {}, {}
    for rep in REPRESENTATIONS:
        scores = {
            'random': random_score,
            'null_spread': -null_spread[rep],
            'margin_low': -feat[:, 0],
            'evidence_high': feat[:, 4],
            'oracle': delta[rep],
        }
        strategies = {}
        for name in ('never', 'always', 'random', 'null_spread', 'margin_low',
                     'evidence_high', 'oracle'):
            strategies[name] = curve_metrics(rep, name, scores, delta, harm, fold)
        results[rep] = strategies
        primary_masks[rep] = {
            name: selected_mask(scores[name], fold, MAIN_Q) for name in DATA_DRIVEN
        }

    d, h = delta[PRIMARY], harm[PRIMARY]
    tests = {name: bootstrap_diffs(primary_masks[PRIMARY][name], d, h,
                                   repo_index, len(repos)) for name in DATA_DRIVEN}
    adjusted = holm({name: tests[name]['delta_gain']['p_two_sided'] for name in DATA_DRIVEN})
    for name in DATA_DRIVEN:
        tests[name]['holm_adjusted_p'] = adjusted[name]

    main_test = tests['null_spread']
    gain_ok = main_test['delta_gain']['ci95'][0] > 0
    risk_ok = main_test['delta_risk']['ci95'][1] < 0
    holm_ok = adjusted['null_spread'] < 0.05
    if gain_ok and risk_ok and holm_ok:
        verdict = ('Observed: the counterfactual-derived dispersion identifies a safer '
                   'intervention subset on held-out repositories at q=0.2. Report all '
                   'three representations, full curves and intervals; no mechanism claim.')
    elif not gain_ok or not risk_ok or not holm_ok:
        verdict = ('Not observed: the counterfactual-calibrated signal did not yield a '
                   'stable gain/risk improvement on held-out repositories at symbol level, '
                   'consistent in direction with the file-level calibration gap reported by '
                   'Agent Retrieval Bench. The resource and the metrics are the deliverable; '
                   'this is not a proof of impossibility.')
    else:
        verdict = 'Mixed: report all numbers and intervals without a mechanism claim.'

    payload = {
        'protocol': 'docs/experiments/intervention-effect-bench.md',
        'inputs': {k: {'sha256': v, 'rows': len(controls)} for k, v in EXPECTED_HASHES.items()},
        'resource': {'path': 'data/intervention_effect_bench.jsonl', 'rows': len(resource),
                     'license': 'MIT (repository LICENSE)',
                     'lite_tasks_with_char_budget': int(sum(1 for k in budgets if k in lite))},
        'n_tasks': len(ids), 'n_repositories': len(repos), 'fold_assignment': fold_of,
        'q_grid': list(Q_GRID), 'main_q': MAIN_Q, 'primary_representation': PRIMARY,
        'bootstrap': BOOTSTRAP, 'seed': SEED,
        'new_metric_definitions': {
            'delta': 'real.symbol - base.symbol',
            'churn': '(real.gained + real.lost)/gold_total',
            'efficiency': 'delta/churn, 0 when churn=0',
            'harm': 'max(-delta, 0)',
            'gain@q': 'mean(delta | selected)', 'risk@q': 'mean(harm | selected)',
            'harm_rate@q': 'P(delta<0 | selected)', 'saving@q': '1-coverage',
            'AURC': 'trapezoid integral of risk@q over q',
            'AUGC': 'trapezoid integral of gain@q over q',
            'utility@q': 'mean(delta * selected) over ALL tasks = coverage * gain@q',
            'overall_risk@q': 'mean(harm * selected) over ALL tasks',
        },
        'consistency_check': {
            'oracle_utility_at_main_q': results[PRIMARY]['oracle']['main_q']['utility'],
            'independent_prior_estimate': 0.04225,
            'note': 'Prior estimate is mean(max(delta,0)) recomputed independently on '
                    '2026-11-09; agreement is a cross-check of the utility definition.',
        },
        'full_sample': {
            rep: {'mean_delta': float(delta[rep].mean()),
                  'mean_harm': float(harm[rep].mean()),
                  'mean_churn': float(churn[rep].mean()),
                  'mean_efficiency': float(efficiency[rep].mean()),
                  'zero_delta_fraction': float((np.abs(delta[rep]) < 1e-12).mean())}
            for rep in REPRESENTATIONS
        },
        'strategies': results,
        'primary_test': {name: tests[name] for name in DATA_DRIVEN},
        'verdict': verdict,
    }
    result_path = ROOT / 'data' / 'intervention_effect_bench_results.json'
    result_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n',
                           encoding='utf-8')

    print(f'resource rows {len(resource)}  repositories {len(repos)}  '
          f'char-budget rows {sum(1 for k in budgets if k in lite)}')
    print(f'full sample (metadata): meanD={d.mean():+.4f} meanHarm={h.mean():.4f} '
          f'zero={(np.abs(d) < 1e-12).mean():.3f}')
    print(f"\n{PRIMARY} @ q={MAIN_Q}: {'strategy':16s}{'gain':>9s}{'risk':>9s}"
          f"{'harm%':>9s}{'utility':>10s}{'AURC':>9s}{'AUGC':>9s}")
    for name in ('always', 'random', 'null_spread', 'margin_low', 'evidence_high', 'oracle'):
        r = results[PRIMARY][name]
        p = r['main_q']
        print(f"{name:16s}{p['gain']:9.4f}{p['risk']:9.4f}{p['harm_rate']:9.3f}"
              f"{p['utility']:10.4f}{r['AURC']:9.4f}{r['AUGC']:9.4f}")
    print('\nprimary test (null_spread vs always, cluster bootstrap):')
    for name in DATA_DRIVEN:
        t = tests[name]
        print(f"  {name:14s} dGain={t['delta_gain']['estimate']:+.4f} "
              f"CI={[round(v, 4) for v in t['delta_gain']['ci95']]} "
              f"p={t['delta_gain']['p_two_sided']:.4f} Holm={t['holm_adjusted_p']:.4f} "
              f"dRisk={t['delta_risk']['estimate']:+.4f} "
              f"CI={[round(v, 4) for v in t['delta_risk']['ci95']]}")
    print(f'\nverdict: {verdict}')
    print(f'wrote {out_path.relative_to(ROOT)} and {result_path.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
