"""Pre-registered test: can a graph intervention's net gain be predicted before the intervention?

Protocol (frozen before any outcome inspection):
    docs/experiments/intervention-predictability.md

Predictors come only from data/features_full.jsonl (the 200-candidate feature
matrix); outcomes come only from data/graph_controls.jsonl (topology-control
results). Coefficients are fitted on six repositories and applied once to the
other six; every task gets exactly one out-of-fold prediction.

    .venv/Scripts/python.exe tools/predict_intervention_value.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import rankdata, spearmanr

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_HASHES = {
    'data/features_full.jsonl': '1bdb47063949bd67ca68e651a05bc989e282bf6fbac54b1f3a74ea20d782b2b4',
    'data/graph_controls.jsonl': 'b89bb12bcab3c5f381ba271c8b2b876d491434bb85ae4f5c5681a9c2fa0560df',
}
REPRESENTATIONS = ('metadata', 'body', 'dense')
PRIMARY = 'metadata'
ALPHA = 1.0
BOOTSTRAP = 10_000
SEED = 20261109
FEATURE_NAMES = (
    'margin_10_11', 'top5_mass', 'seed_file_spread', 'seed_degree',
    'evidence_top10', 'score_decay',
)


def sha256(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def load_jsonl(relative: str) -> list[dict]:
    with (ROOT / relative).open(encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build_features(feature_names: list[str], rows: list[list], files: list[str]) -> list[float]:
    """Leakage guard: this function receives ONLY the matrix, its column names and
    file paths. It cannot see labels, gold targets, or any intervention outcome."""
    ix = {name: i for i, name in enumerate(feature_names)}
    score = [float(row[ix['bm25_score']]) for row in rows]

    margin = score[9] - score[10]
    mass = sum(score[:5]) / max(sum(score[:50]), 1e-9)
    spread = float(len(set(files[:5])))
    degree = float(np.mean([rows[i][ix['in_degree']] + rows[i][ix['out_degree']]
                            for i in range(5)]))
    evidence = float(sum(rows[i][ix['path_in_issue']] + rows[i][ix['frame_hit']]
                         + rows[i][ix['named_file']] for i in range(10)))
    decay = score[0] - score[9]
    return [margin, mass, spread, degree, evidence, decay]


def outcome(row: dict, representation: str) -> tuple[float, float]:
    arms = row['representations'][representation]['arms']
    delta = float(arms['real']['symbol']) - float(arms['base']['symbol'])
    check = (arms['real']['gained'] - arms['real']['lost']) / row['gold_total']
    return delta, float(check)


def fit_predict(x: np.ndarray, y: np.ndarray, train: np.ndarray,
                test: np.ndarray) -> np.ndarray:
    mu, sigma = x[train].mean(axis=0), x[train].std(axis=0)
    sigma = np.where(sigma < 1e-12, 1.0, sigma)
    xt = (x[train] - mu) / sigma
    xs = (x[test] - mu) / sigma
    design = np.column_stack([np.ones(len(train)), xt])
    gram = design.T @ design + ALPHA * np.eye(design.shape[1])
    gram[0, 0] -= ALPHA  # do not penalise the intercept
    beta = np.linalg.solve(gram, design.T @ y[train])
    return np.column_stack([np.ones(len(test)), xs]) @ beta


def corr(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a - a.mean(), b - b.mean()
    denom = np.sqrt(float((a * a).sum()) * float((b * b).sum()))
    return float((a * b).sum() / denom) if denom > 1e-12 else 0.0


def cluster_bootstrap(pred: np.ndarray, y: np.ndarray,
                      repo_index: np.ndarray, n_repos: int) -> tuple[list[float], float]:
    rp, ry = rankdata(pred), rankdata(y)
    clusters = [np.flatnonzero(repo_index == i) for i in range(n_repos)]
    rng = np.random.default_rng(SEED)
    values = []
    for _ in range(BOOTSTRAP):
        pick = rng.integers(0, n_repos, n_repos)
        idx = np.concatenate([clusters[i] for i in pick])
        values.append(corr(rp[idx], ry[idx]))
    lo, hi = np.percentile(values, [2.5, 97.5])
    arr = np.asarray(values)
    p = 2.0 * min(float((arr <= 0).mean()), float((arr >= 0).mean()))
    return [float(lo), float(hi)], min(1.0, p)


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
            print(f'ERROR: {relative} hash mismatch\n  expected {expected}\n  actual   {actual}')
            return 1

    features = {row['instance_id']: row for row in load_jsonl('data/features_full.jsonl')}
    controls = load_jsonl('data/graph_controls.jsonl')
    controls = [row for row in controls
                if row['instance_id'] in features and row['gold_total'] > 0]
    ids = [row['instance_id'] for row in controls]
    if len(set(ids)) != len(ids):
        print('ERROR: duplicate instance_id in controls')
        return 1

    x = np.asarray([build_features(features[i]['features'], features[i]['rows'],
                                   features[i]['files']) for i in ids], dtype=float)
    repos = sorted({row['repo'] for row in controls})
    fold_of = {repo: i % 2 for i, repo in enumerate(repos)}
    fold = np.asarray([fold_of[row['repo']] for row in controls])
    repo_index = np.asarray([repos.index(row['repo']) for row in controls])

    # Lite subset: a secondary, descriptive-only analysis (nested in the full split).
    lite = {row['instance_id'] for row in load_jsonl('data/gold_symbols.jsonl')
            if row.get('has_symbols')}
    lite_mask = np.asarray([i in lite for i in ids])

    results, consistency = {}, {}
    for rep in REPRESENTATIONS:
        pairs = [outcome(row, rep) for row in controls]
        y = np.asarray([p[0] for p in pairs], dtype=float)
        checks = np.asarray([p[1] for p in pairs], dtype=float)
        consistency[rep] = int((np.abs(y - checks) > 1e-6).sum())

        pred = np.empty(len(y))
        for held_out in (0, 1):
            train = np.flatnonzero(fold != held_out)
            test = np.flatnonzero(fold == held_out)
            pred[test] = fit_predict(x, y, train, test)

        rho = float(spearmanr(pred, y).statistic)
        ci, p_value = cluster_bootstrap(pred, y, repo_index, len(repos))
        mse_zero = float(np.mean(y ** 2))
        mse_model = float(np.mean((pred - y) ** 2))
        results[rep] = {
            'spearman': rho,
            'spearman_ci95_cluster': ci,
            'bootstrap_p_two_sided': p_value,
            'pearson': corr(pred, y),
            'mse_zero_baseline': mse_zero,
            'mse_model': mse_model,
            'mse_improvement': 1.0 - mse_model / mse_zero if mse_zero > 0 else None,
            'n_nonzero_delta': int((np.abs(y) > 1e-12).sum()),
            'mean_delta': float(y.mean()),
            'lite_spearman': (float(spearmanr(pred[lite_mask], y[lite_mask]).statistic)
                              if lite_mask.sum() > 2 and np.std(y[lite_mask]) > 0 else None),
            'lite_tasks': int(lite_mask.sum()),
        }

    adjusted = holm({rep: results[rep]['bootstrap_p_two_sided'] for rep in REPRESENTATIONS})
    for rep in REPRESENTATIONS:
        results[rep]['holm_adjusted_p'] = adjusted[rep]

    primary = results[PRIMARY]
    ci = primary['spearman_ci95_cluster']
    ci_crosses_zero = ci[0] <= 0 <= ci[1]
    gain = primary['mse_improvement']
    if (rho_pos := 0 < ci[0]) and gain is not None and gain > 0 \
            and adjusted[PRIMARY] < 0.05:
        verdict = ('Observed: cross-repository, pre-intervention predictability of net '
                   'intervention gain in this setup. Report all three representations '
                   'and all intervals; no mechanism or universality claim.')
    elif ci_crosses_zero or gain is None or gain <= 0:
        verdict = ('Not observed: net intervention gain was not stably predictable from '
                   'pre-intervention statistics on held-out repositories. This does not '
                   'prove unpredictability; combine with the existing failed counterfactual '
                   'router as a negative-result chain.')
    else:
        verdict = 'Mixed: report numbers and intervals without a mechanism claim.'
    _ = rho_pos

    payload = {
        'protocol': 'docs/experiments/intervention-predictability.md',
        'inputs': {k: {'sha256': v, 'rows': len(controls)} for k, v in EXPECTED_HASHES.items()},
        'n_tasks': len(ids), 'n_repositories': len(repos),
        'fold_assignment': fold_of,
        'feature_names': list(FEATURE_NAMES),
        'alpha': ALPHA, 'bootstrap': BOOTSTRAP, 'seed': SEED,
        'primary_representation': PRIMARY,
        'delta_consistency_mismatch_tasks': consistency,
        'representations': results,
        'verdict': verdict,
    }
    out = ROOT / 'data' / 'intervention_predictability.json'
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    print(f'tasks {len(ids)}  repositories {len(repos)}  folds 2  alpha {ALPHA}')
    print(f'delta consistency mismatches: {consistency}')
    print(f"{'rep':10s}{'rho':>9s}{'CI95':>22s}{'p':>9s}{'Holm':>9s}"
          f"{'MSEgain':>10s}{'nonzero':>9s}")
    for rep in REPRESENTATIONS:
        r = results[rep]
        print(f"{rep:10s}{r['spearman']:9.4f}"
              f"{'[' + format(r['spearman_ci95_cluster'][0], '.4f') + ', ' + format(r['spearman_ci95_cluster'][1], '.4f') + ']':>22s}"
              f"{r['bootstrap_p_two_sided']:9.4f}{r['holm_adjusted_p']:9.4f}"
              f"{r['mse_improvement']:10.4f}{r['n_nonzero_delta']:9d}")
    print(f'\nverdict: {verdict}\nwrote {out.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
