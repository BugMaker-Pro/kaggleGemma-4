"""Confirmatory test of the "counterfactual dispersion = intervention sensitivity"
hypothesis with a strictly label-free main signal.

Protocol (frozen before inspecting any signal-outcome association):
  docs/experiments/intervention-sensitivity-confirmation.md

The main signal D is built ONLY from the top-10 candidate-index sets of five
rewired random graphs. It never reads real/base arms, symbol, gained, lost,
gold_total, gold_files, or labels. Gold-derived quantities are used exclusively
as OUTCOMES (delta, upside, downside, harm) and in one descriptive equivalence
diagnostic (null_spread).

Run:
  .venv/Scripts/python.exe tools/confirm_intervention_sensitivity.py
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent

EXPECTED_HASHES = {
    'data/graph_controls.jsonl':
        'b89bb12bcab3c5f381ba271c8b2b876d491434bb85ae4f5c5681a9c2fa0560df',
    'data/null_calibrated_graph.jsonl':
        '9c523214103a2270758c3d30e7e822217d86780d424c1910531fa07f3bcdec27',
}

CONTROLS = 'data/graph_controls.jsonl'
CALIBRATED = 'data/null_calibrated_graph.jsonl'
OUT = ROOT / 'data' / 'intervention_sensitivity_confirmation.json'

SEEDS = (11, 23, 37, 51, 71)
REPRESENTATIONS = ('metadata', 'body', 'dense')
PRIMARY_REP = 'metadata'
Q_MAIN = 0.2
Q_SECONDARY = 0.3
BOOTSTRAP = 10_000
SEED = 20261109
RHO_GATE = 0.30
MAIN_TESTS = ('upside', 'downside', 'harm')

REWIRED = re.compile(r'^rewired_\d+$')
REWIRED_PAIR = re.compile(r'^rewired_pair_\d+$')


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
    """Mean pairwise 1-Jaccard over C(5,2)=10 unordered pairs. No parameters."""
    values = [1.0 - len(a & b) / len(a | b)
              for a, b in itertools.combinations(sets, 2)]
    return float(sum(values) / len(values))


def tie_key(instance_id: str) -> np.uint64:
    return np.uint64(int.from_bytes(
        hashlib.sha256(instance_id.encode('utf-8')).digest()[:8], 'big'))


def rank_from_score(score: np.ndarray, tie: np.ndarray,
                    descending: bool = True) -> np.ndarray:
    """Deterministic rank: primary score, SHA256(instance_id) tie-break."""
    primary = -score if descending else score
    order = np.lexsort((tie.astype(np.uint64), primary))
    rank = np.empty(len(order), dtype=np.int64)
    rank[order] = np.arange(len(order), dtype=np.int64)
    return rank


def select_mask(rank: np.ndarray, fold: np.ndarray, idx: np.ndarray,
                q: float) -> np.ndarray:
    """Top ceil(q*n_fold) per fold, over the (possibly resampled) idx array."""
    mask = np.zeros(len(idx), dtype=bool)
    sub_rank, sub_fold = rank[idx], fold[idx]
    for f in (0, 1):
        pos = np.flatnonzero(sub_fold == f)
        if not len(pos):
            continue
        k = math.ceil(q * len(pos))
        k = max(1, min(k, len(pos)))
        chosen = pos[np.argpartition(sub_rank[pos], k - 1)[:k]]
        mask[chosen] = True
    return mask


def three_diffs(upside: np.ndarray, downside: np.ndarray, harm: np.ndarray,
                rank: np.ndarray, fold: np.ndarray, idx: np.ndarray,
                q: float) -> dict[str, float]:
    mask = select_mask(rank, fold, idx, q)
    return {
        'upside': float(upside[idx][mask].mean() - upside[idx].mean()),
        'downside': float(downside[idx][mask].mean() - downside[idx].mean()),
        'harm': float(harm[idx][mask].mean() - harm[idx].mean()),
        'selected_gain': float(upside[idx][mask].mean() - downside[idx][mask].mean()),
        'selected_harm_rate': float(harm[idx][mask].mean()),
        'baseline_upside': float(upside[idx].mean()),
        'baseline_downside': float(downside[idx].mean()),
        'baseline_harm_rate': float(harm[idx].mean()),
    }


def holm(pvals: dict[str, float]) -> dict[str, float]:
    keys = list(pvals)
    order = np.argsort([pvals[k] for k in keys])
    adjusted, running = {}, 0.0
    for rank_pos, i in enumerate(order):
        running = max(running, (len(keys) - rank_pos) * pvals[keys[i]])
        adjusted[keys[i]] = min(1.0, running)
    return adjusted


def point_estimates(upside, downside, harm, rank, fold, idx, q) -> dict:
    d = three_diffs(upside, downside, harm, rank, fold, idx, q)
    return {k: round(v, 6) for k, v in d.items()}


def main() -> int:
    for relative, expected in EXPECTED_HASHES.items():
        actual = sha256(relative)
        if actual != expected:
            print(f'ERROR: {relative} hash mismatch\n  expected {expected}\n  actual   {actual}')
            return 1
    print('input hashes: OK')

    controls = load_jsonl(CONTROLS)
    controls = [r for r in controls if r['gold_total'] > 0]
    ids = [r['instance_id'] for r in controls]
    n = len(ids)
    if len(set(ids)) != n:
        print('ERROR: duplicate instance_id')
        return 1
    repos = sorted({r['repo'] for r in controls})
    n_repos = len(repos)
    fold_of = {repo: i % 2 for i, repo in enumerate(repos)}
    fold = np.asarray([fold_of[r['repo']] for r in controls], dtype=np.int64)
    repo_index = np.asarray([repos.index(r['repo']) for r in controls], dtype=np.int64)
    tie = np.asarray([tie_key(i) for i in ids], dtype=np.uint64)
    print(f'population: {n} tasks, {n_repos} repos, folds '
          f'{int((fold == 0).sum())}/{int((fold == 1).sum())}')

    # ---- signal: strictly label-free, built from top10 candidate-index sets ----
    dispersion: dict[str, np.ndarray] = {}
    for rep in REPRESENTATIONS:
        for family, prefix, tag in (('rewired', 'rewired_', f'{rep}_rewired'),
                                    ('pair', 'rewired_pair_', f'{rep}_pair')):
            vals = []
            for row in controls:
                arms = row['representations'][rep]['arms']
                sets = [set(arms[prefix + str(s)]['top10']) for s in SEEDS]
                vals.append(jaccard_dispersion(sets))
            dispersion[tag] = np.asarray(vals, dtype=float)

    # ---- outcomes: gold-derived, never used to build the signal ----
    delta: dict[str, np.ndarray] = {}
    null_spread = np.zeros(n, dtype=float)
    for rep in REPRESENTATIONS:
        vals = []
        for k, row in enumerate(controls):
            arms = row['representations'][rep]['arms']
            real, base = arms['real'], arms['base']
            d = float(real['symbol']) - float(base['symbol'])
            check = (float(real['gained']) - float(real['lost'])) / row['gold_total']
            if abs(d - check) > 1e-9:
                print(f'ERROR: delta inconsistency at {ids[k]} / {rep}: {d} vs {check}')
                return 1
            vals.append(d)
            if rep == PRIMARY_REP:
                rew = [float(arms[x]['symbol']) for x in arms if REWIRED.match(x)]
                null_spread[k] = float(np.std(rew)) if rew else 0.0
        delta[rep] = np.asarray(vals, dtype=float)

    def split(d: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return np.maximum(d, 0.0), np.maximum(-d, 0.0), (d < 0).astype(float)

    up, down, hm = split(delta[PRIMARY_REP])
    rank_main = rank_from_score(dispersion['metadata_rewired'], tie)
    rank_pair = rank_from_score(dispersion['metadata_pair'], tie)
    rank_body = rank_from_score(dispersion['body_rewired'], tie)
    rank_dense = rank_from_score(dispersion['dense_rewired'], tie)
    rank_low = rank_from_score(dispersion['metadata_rewired'], tie, descending=False)
    idx_all = np.arange(n, dtype=np.int64)

    # ---- applicability gate: is the label-free signal the same quantity? ----
    rho = float(spearmanr(dispersion['metadata_rewired'], null_spread).statistic)
    gate_pass = bool(rho >= RHO_GATE)
    print(f'applicability gate: rho(D_main, null_spread) = {rho:.4f} '
          f'(gate {RHO_GATE}) -> {"pass" if gate_pass else "FAIL"}')

    # ---- primary test: full re-selection inside every bootstrap replicate ----
    clusters = [np.flatnonzero(repo_index == i) for i in range(n_repos)]
    rng = np.random.default_rng(SEED)
    history: dict[str, list[float]] = {k: [] for k in MAIN_TESTS}
    for _ in range(BOOTSTRAP):
        pick = rng.integers(0, n_repos, n_repos)
        idx = np.concatenate([clusters[i] for i in pick])
        d = three_diffs(up, down, hm, rank_main, fold, idx, Q_MAIN)
        for key in MAIN_TESTS:
            history[key].append(d[key])

    point = three_diffs(up, down, hm, rank_main, fold, idx_all, Q_MAIN)
    raw_p, ci, primary = {}, {}, {}
    for key in MAIN_TESTS:
        arr = np.asarray(history[key])
        lo, hi = np.percentile(arr, [2.5, 97.5])
        p = min(1.0, 2.0 * min(float((arr <= 0).mean()), float((arr >= 0).mean())))
        raw_p[key], ci[key] = p, [float(lo), float(hi)]
    adjusted = holm(raw_p)
    for key in MAIN_TESTS:
        primary[key] = {
            'point': round(point[key], 6),
            'ci95': [round(v, 6) for v in ci[key]],
            'p_raw': round(raw_p[key], 6),
            'p_holm': round(adjusted[key], 6),
            'passes': bool(ci[key][0] > 0 and adjusted[key] < 0.05),
        }

    # ---- secondary: direction + point estimates only, no inference ----
    up_b, down_b, hm_b = split(delta['body'])
    up_d, down_d, hm_d = split(delta['dense'])

    cal_rows = [r for r in load_jsonl(CALIBRATED) if r['representation'] == PRIMARY_REP]
    cal = {r['instance_id']: r['arms'] for r in cal_rows}
    if set(cal) != set(ids):
        print('ERROR: null_calibrated_graph population differs')
        return 1
    d_cal, base_mismatch = [], 0
    for k, row in enumerate(controls):
        c = cal[ids[k]]
        if abs(float(c['base']['symbol']) -
               float(row['representations'][PRIMARY_REP]['arms']['base']['symbol'])) > 1e-9:
            base_mismatch += 1
        d_cal.append(float(c['calibrated']['symbol']) - float(c['base']['symbol']))
    d_cal = np.asarray(d_cal, dtype=float)
    up_c, down_c, hm_c = split(d_cal)

    order = np.argsort(rank_main)
    buckets = []
    for part in np.array_split(order, 5):
        buckets.append({
            'n': int(len(part)),
            'mean_D': round(float(dispersion['metadata_rewired'][part].mean()), 6),
            'mean_upside': round(float(up[part].mean()), 6),
            'mean_downside': round(float(down[part].mean()), 6),
            'mean_delta': round(float(delta[PRIMARY_REP][part].mean()), 6),
            'harm_rate': round(float(hm[part].mean()), 6),
        })

    secondary = {
        'C1_pair_signal': point_estimates(up, down, hm, rank_pair, fold, idx_all, Q_MAIN),
        'C2_body': point_estimates(up_b, down_b, hm_b, rank_body, fold, idx_all, Q_MAIN),
        'C2_dense': point_estimates(up_d, down_d, hm_d, rank_dense, fold, idx_all, Q_MAIN),
        'C3_q0.3': point_estimates(up, down, hm, rank_main, fold, idx_all, Q_SECONDARY),
        'C4_calibrated_arm': {
            **point_estimates(up_c, down_c, hm_c, rank_main, fold, idx_all, Q_MAIN),
            'delta_zero_fraction': round(float((d_cal == 0).mean()), 6),
            'base_symbol_mismatch': base_mismatch,
        },
        'C5_quintiles': buckets,
        'C6_low_dispersion': point_estimates(up, down, hm, rank_low, fold, idx_all, Q_MAIN),
    }

    all_pass = all(primary[k]['passes'] for k in MAIN_TESTS)
    if gate_pass and all_pass:
        verdict_code = 'INTERNAL_CONFIRMATION'
        verdict = ('在同一批 2,232 任务上，用完全不含金标的结构分歧度信号，'
                   '去除共享 recall 混杂后，内部确认了高离散度子集的 upside 与 downside '
                   '同时上升；与"离散度=安全性"不相容。'
                   '这不是独立复制、不是外部验证、不是样本外预测，不得进入投稿结论。')
    elif not gate_pass:
        verdict_code = 'NOT_CONFIRMED_SIGNAL_NOT_EQUIVALENT'
        verdict = ('label-free 结构分歧度与上一轮 post-hoc 使用的离散度不等价；'
                   '本轮检验了另一个量，不构成对该假设的确认。按冻结协议强制判为未确认。')
    else:
        verdict_code = 'NOT_CONFIRMED'
        verdict = ('敏感度假设在本轮未获内部确认；只报数字与区间，不给机制解释，'
                   '不换方向重跑、不挑表示或覆盖率当结论。')

    out = {
        'protocol': 'docs/experiments/intervention-sensitivity-confirmation.md',
        'inputs': {k: {'sha256': v, 'verified': True} for k, v in EXPECTED_HASHES.items()},
        'population': {'n_tasks': n, 'n_repos': n_repos, 'repos': repos,
                       'fold_sizes': [int((fold == 0).sum()), int((fold == 1).sum())],
                       'representations': list(REPRESENTATIONS)},
        'signal': {
            'definition': 'mean pairwise 1-Jaccard over five rewired top10 index sets',
            'label_free': True,
            'reads': ['representations.*.arms.rewired*_*.top10'],
            'forbidden_reads_verified': ['real', 'base', 'symbol', 'gained', 'lost',
                                         'gold_total', 'gold_files', 'labels'],
            'nonzero_fraction': {k: round(float((v > 0).mean()), 6)
                                 for k, v in dispersion.items()},
        },
        'outcomes': {rep: {'mean_delta': round(float(delta[rep].mean()), 6),
                           'zero_fraction': round(float((delta[rep] == 0).mean()), 6)}
                     for rep in REPRESENTATIONS},
        'applicability_check': {
            'spearman_rho_D_main_vs_null_spread': round(rho, 6),
            'gate': RHO_GATE,
            'passed': gate_pass,
            'note': 'null_spread is a DESCRIPTIVE equivalence diagnostic only; '
                    'it is never used to build the main signal or to select tasks.',
        },
        'primary_test': {
            'representation': PRIMARY_REP, 'signal': 'D_main (metadata, rewired)',
            'intervention': 'real vs base', 'q': Q_MAIN,
            'bootstrap': BOOTSTRAP, 'seed': SEED,
            'resampling': 'per-replicate fold-wise re-selection and baseline recomputation',
            'multiple_comparison': 'Holm over three tests',
            'baseline': {
                'upside': round(float(up.mean()), 6),
                'downside': round(float(down.mean()), 6),
                'harm_rate': round(float(hm.mean()), 6),
                'mean_delta': round(float(delta[PRIMARY_REP].mean()), 6),
            },
            'selected': {
                'mean_delta': round(point['selected_gain'], 6),
                'harm_rate': round(point['selected_harm_rate'], 6),
                'utility_at_q': round(Q_MAIN * point['selected_gain'], 6),
            },
            'tests': primary,
            'all_pass': bool(all_pass),
        },
        'secondary': secondary,
        'verdict': {'code': verdict_code, 'text': verdict,
                    'independent_replication': False,
                    'external_validation': False,
                    'eligible_for_submission': False,
                    'paper_or_writeup_modified': False},
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    print('\napplicability rho = %.4f (gate %.2f, %s)' %
          (rho, RHO_GATE, 'pass' if gate_pass else 'FAIL'))
    print('primary test, q=0.2, metadata, real-vs-base, 10,000 cluster bootstraps')
    print('%-10s %10s %24s %10s %10s %6s' %
          ('test', 'point', 'CI95', 'p_raw', 'p_holm', 'pass'))
    for key in MAIN_TESTS:
        t = primary[key]
        print('%-10s %10.6f [%9.6f, %9.6f] %10.4f %10.4f %6s' %
              (key, t['point'], t['ci95'][0], t['ci95'][1],
               t['p_raw'], t['p_holm'], t['passes']))
    print('\nverdict:', verdict_code)
    print(verdict)
    print('\nwrote', OUT.relative_to(ROOT).as_posix())
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass
    raise SystemExit(main())
