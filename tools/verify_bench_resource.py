"""Integrity / reproducibility verifier for the InterventionEffect Bench v1 resource.

It is READ-ONLY with respect to the resource data: it validates files, schema,
derived quantities, cross-file ID disjointness, licence, and reproduction
entrypoints, then writes a deterministic manifest (no timestamps, so reruns are
byte-for-byte identical).

Run:
  .venv/Scripts/python.exe tools/verify_bench_resource.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent

BENCH = 'data/intervention_effect_bench.jsonl'
HELDOUT = 'data/heldout_structure_rows.jsonl'
RESULT_FILES = (
    'data/intervention_effect_bench_results.json',
    'data/intervention_predictability.json',
    'data/intervention_sensitivity_confirmation.json',
    'data/external_structure_check.json',
)
REPRO_SCRIPTS = (
    'tools/intervention_effect_bench.py',
    'tools/predict_intervention_value.py',
    'tools/confirm_intervention_sensitivity.py',
    'tools/external_structure_check.py',
)
PROTOCOLS = (
    'docs/experiments/intervention-predictability.md',
    'docs/experiments/intervention-effect-bench.md',
    'docs/experiments/intervention-sensitivity-confirmation.md',
    'docs/experiments/heldout-structure-replication.md',
)
MANIFEST = ROOT / 'data' / 'bench_resource_manifest.json'

REPRESENTATIONS = ('metadata', 'body', 'dense')
REP_KEYS = {'base', 'real', 'same_file', 'rewired', 'rewired_pair', 'derived'}
ARM_KEYS = {'symbol', 'file', 'gained', 'lost'}
DERIVED_KEYS = {'delta', 'churn', 'efficiency', 'harm',
                'null_spread', 'null_mean', 'pair_spread'}
PRE_KEYS = {'margin_10_11', 'top5_mass', 'seed_file_spread',
            'seed_degree', 'evidence_top10', 'score_decay'}
TOP_KEYS = {'instance_id', 'repo', 'gold_total', 'pool_size', 'pool_gold',
            'pre_intervention', 'char_budget', 'representations'}
HELDOUT_KEYS = {'instance_id', 'repo', 'D', 'D_zero', 'in_null',
                'unchanged', 'churn', 'pool_size', 'edges'}
EXPECTED_BENCH_ROWS = 2232
EXPECTED_HELDOUT_ROWS = 62
EXPECTED_BUDGET_ROWS = 290


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def rows_of(relative: str) -> list[dict]:
    out = []
    with (ROOT / relative).open(encoding='utf-8') as handle:
        for line in handle:
            if line.strip():
                out.append(json.loads(line))
    return out


def main() -> int:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({'name': name, 'pass': bool(ok), 'detail': detail})

    needed = [BENCH, HELDOUT, *RESULT_FILES, *REPRO_SCRIPTS, *PROTOCOLS, 'LICENSE']
    missing = [p for p in needed if not (ROOT / p).exists()]
    check('all_declared_files_exist', not missing,
          f'missing={missing}' if missing else f'{len(needed)} files present')
    if missing:
        print('ERROR: missing files', missing)
        return 1

    licence = (ROOT / 'LICENSE').read_text(encoding='utf-8')
    check('licence_is_MIT', 'MIT License' in licence or 'MIT' in licence[:200],
          'LICENSE declares MIT')

    hashes = {p: sha256(ROOT / p) for p in needed}

    bench = rows_of(BENCH)
    heldout = rows_of(HELDOUT)
    check('bench_row_count', len(bench) == EXPECTED_BENCH_ROWS,
          f'{len(bench)} rows (expected {EXPECTED_BENCH_ROWS})')
    check('heldout_row_count', len(heldout) == EXPECTED_HELDOUT_ROWS,
          f'{len(heldout)} rows (expected {EXPECTED_HELDOUT_ROWS})')

    bench_ids = [r['instance_id'] for r in bench]
    held_ids = [r['instance_id'] for r in heldout]
    check('bench_ids_unique', len(set(bench_ids)) == len(bench_ids),
          f'{len(set(bench_ids))} unique / {len(bench_ids)} rows')
    check('heldout_ids_unique', len(set(held_ids)) == len(held_ids),
          f'{len(set(held_ids))} unique / {len(held_ids)} rows')
    check('heldout_disjoint_from_bench', not (set(held_ids) & set(bench_ids)),
          f'overlap = {len(set(held_ids) & set(bench_ids))}')

    # ---- schema ----
    schema_fail = []
    for i, r in enumerate(bench):
        if set(r) != TOP_KEYS:
            schema_fail.append((i, 'top-level keys'))
            continue
        if set(r['pre_intervention']) != PRE_KEYS:
            schema_fail.append((i, 'pre_intervention keys'))
        if set(r['representations']) != set(REPRESENTATIONS):
            schema_fail.append((i, 'representation names'))
            continue
        for rep in REPRESENTATIONS:
            v = r['representations'][rep]
            if set(v) != REP_KEYS:
                schema_fail.append((i, f'{rep} keys'))
                continue
            for arm in ('base', 'real', 'same_file'):
                if set(v[arm]) != ARM_KEYS:
                    schema_fail.append((i, f'{rep}.{arm} keys'))
            for group in ('rewired', 'rewired_pair'):
                if len(v[group]) != 5 or any(
                        set(x) != (ARM_KEYS | {'arm'}) for x in v[group]):
                    schema_fail.append((i, f'{rep}.{group} shape'))
            if set(v['derived']) != DERIVED_KEYS:
                schema_fail.append((i, f'{rep}.derived keys'))
    check('bench_schema', not schema_fail,
          f'{len(schema_fail)} violations' + (f'; first={schema_fail[:3]}' if schema_fail else ''))

    heldout_schema = all(set(r) == HELDOUT_KEYS for r in heldout)
    check('heldout_schema_label_free', heldout_schema,
          'only 9 label-free fields' if heldout_schema else 'unexpected fields present')
    check('heldout_D_zero_consistent',
          all(r['D_zero'] == (r['D'] == 0) for r in heldout),
          'D_zero matches D == 0 on every row')

    # ---- derived quantities ----
    derived_fail = []
    for i, r in enumerate(bench):
        gt = r['gold_total']
        if gt <= 0:
            derived_fail.append((i, 'gold_total <= 0'))
            continue
        for rep in REPRESENTATIONS:
            v = r['representations'][rep]
            real, base = v['real'], v['base']
            delta = float(real['symbol']) - float(base['symbol'])
            churn = (real['gained'] + real['lost']) / gt
            d = v['derived']
            rew = [float(x['symbol']) for x in v['rewired']]
            pair = [float(x['symbol']) for x in v['rewired_pair']]
            expected = {
                'delta': delta, 'churn': churn,
                'efficiency': delta / churn if churn > 0 else 0.0,
                'harm': max(-delta, 0.0),
                'null_spread': float(np.std(rew)),
                'null_mean': float(np.mean(rew)),
                'pair_spread': float(np.std(pair)),
            }
            for key, want in expected.items():
                if abs(float(d[key]) - want) > 1e-9:
                    derived_fail.append((i, f'{rep}.derived.{key}'))
            if abs(delta - (real['gained'] - real['lost']) / gt) > 1e-9:
                derived_fail.append((i, f'{rep}.delta_vs_gained_lost'))
    check('derived_quantities_consistent', not derived_fail,
          f'{len(derived_fail)} violations' +
          (f'; first={derived_fail[:3]}' if derived_fail else ''))

    budget_rows = sum(1 for r in bench if r.get('char_budget'))
    check('char_budget_rows', budget_rows == EXPECTED_BUDGET_ROWS,
          f'{budget_rows} Lite tasks with budget curves (expected {EXPECTED_BUDGET_ROWS})')

    # ---- result files: report verdicts, verify submission claims ----
    verdicts, claim_fail = {}, []
    for p in RESULT_FILES:
        data = json.loads((ROOT / p).read_text(encoding='utf-8'))
        verdict = data.get('verdict', 'MISSING')
        verdicts[p] = verdict
        if isinstance(verdict, dict):
            for key, expected in (('eligible_for_submission', False),
                                  ('paper_or_writeup_modified', False)):
                if key in verdict and verdict[key] is not expected:
                    claim_fail.append((p, key, verdict[key]))
    check('no_submission_claim_in_results', not claim_fail,
          f'{len(claim_fail)} violations' if claim_fail else
          'all declared verdicts are non-submission / paper untouched')

    all_pass = all(c['pass'] for c in checks)
    manifest = {
        'schema_version': 1,
        'resource': 'InterventionEffect Bench v1',
        'card': 'docs/resource/intervention-effect-bench-card.md',
        'licence': 'MIT (root LICENSE)',
        'files': {p: {'sha256': h} for p, h in hashes.items()},
        'row_counts': {
            BENCH: len(bench),
            HELDOUT: len(heldout),
            'char_budget_tasks': budget_rows,
        },
        'result_verdicts': verdicts,
        'checks': checks,
        'all_pass': bool(all_pass),
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                        encoding='utf-8')

    for c in checks:
        print(('PASS' if c['pass'] else 'FAIL'), c['name'], '-', c['detail'])
    print('\nALL PASS:', all_pass)
    print('manifest:', MANIFEST.relative_to(ROOT).as_posix())
    return 0 if all_pass else 1


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass
    raise SystemExit(main())
