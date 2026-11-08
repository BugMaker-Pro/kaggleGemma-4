"""Read-only independent fusion/metric audit; no API calls or model inference."""
import argparse
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.run_query_validation import load_run, validate_generated, read_rows, file_hash, digest, load_key, charged_or_reserved
from tools.evaluate_query_pilot import gold_targets


def rrf(sources):
    votes = defaultdict(float)
    for source in sources:
        assert len(source) == len(set(source))
        for rank, node in enumerate(source, 1):
            votes[node] += 1 / (60 + rank)
    return sorted(votes, key=lambda node: (-votes[node], node))[:200]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    args.strong = ROOT / 'experiments/runs/strong-query-20261103-v2'
    args.model_dir = ROOT / 'models/bge-small-en-v1.5'
    manifest, tasks, anchors, requests, _ = load_run(args)
    responses = validate_generated(args.run_dir, manifest, requests)
    scores = read_rows(args.run_dir / 'scores.jsonl')
    summary = json.loads((args.run_dir / 'summary.json').read_text(encoding='utf-8'))
    gold = {r['instance_id']: r for r in read_rows(ROOT / 'data/gold_symbols.jsonl')}
    assert [s['instance_id'] for s in scores] == manifest['task_ids']
    assert len(responses) == len(tasks) == len(scores)
    assert summary['responses_sha256'] == file_hash(args.run_dir / 'responses.jsonl')
    assert summary['gold_sha256'] == file_hash(ROOT / 'data/gold_symbols.jsonl')
    checks = 0
    for i, (task, anchor, response, scored) in enumerate(zip(tasks, anchors, responses, scores)):
        path = args.run_dir / 'scored_candidates' / f'{i:03d}.json'
        assert summary['candidate_hashes'][path.name] == file_hash(path)
        row = json.loads(path.read_text(encoding='utf-8'))
        assert row['instance_id'] == task.instance_id
        assert row['manifest_sha256'] == manifest['manifest_sha256']
        assert row['response_sha256'] == digest(response)
        assert row['request_sha256'] == requests[i]['request_sha256']
        pools = row['pools']
        assert pools['historical'] == anchor['anchor']['ids']
        assert pools['body_original'] == [x['id'] for x in row['original']]
        assert pools['simple_fusion'] == rrf([pools['historical'], pools['body_original']])
        assert [a['query'] for a in row['generated_actions']] == response['queries']
        sources = [pools['body_original']] + [[x['id'] for x in a['candidates']] for a in row['generated_actions']]
        assert pools['generated'] == (rrf(sources) if response['status'] == 'ok' else pools['simple_fusion'])
        assert row['fallback'] == (response['status'] != 'ok') == scored['fallback']
        fold = manifest['folds'][row['fold']]
        assert task.repo in fold['test_repos'] and task.repo not in fold['train_repos']
        assert task.instance_id not in fold['training_task_ids']
        assert len(row['ids']) == len(set(row['ids'])) == len(row['rows'])
        assert set(row['ids']) == set().union(*map(set, pools.values()))
        assert all(len(x) == 17 and all(math.isfinite(v) for v in x) for x in row['rows'])
        features = dict(zip(row['ids'], row['rows']))
        for node, values in zip(anchor['anchor']['ids'], anchor['anchor']['rows']):
            assert features[node][:16] == values
        for node, cosine in zip(anchor['anchor']['ids'], anchor['cosine']):
            assert features[node][16] == cosine
        if anchor['origin'] == 'rebuilt_without_gold':
            assert row['snapshot_content_sha256'] == anchor['snapshot_sha256']
        record = gold.get(task.instance_id)
        targets = gold_targets(record) if record else set()
        assert scored['gold_count'] == len(targets) and scored['scorable'] == bool(targets)
        assert scored['gold_status'] == ('missing_record' if record is None else 'symbols' if targets else 'no_symbols')
        for arm, pool in pools.items():
            assert len(pool) <= 200 and len(pool) == len(set(pool))
            assert all(math.isfinite(row['strong_scores'][n]) for n in pool)
            assert row['orders'][arm] == sorted(pool, key=lambda n: -row['strong_scores'][n])
            for metric, ids in [('coverage', pool), ('recall_at_10', row['orders'][arm][:10])]:
                expected = len(set(ids) & targets) / len(targets) if targets else None
                assert scored['arms'][arm][metric] == expected
                checks += 1
        union = set(pools['historical']) | set(pools['body_original'])
        generated_top = set(row['orders']['generated'][:10]) & targets
        simple_top = set(row['orders']['simple_fusion'][:10]) & targets
        assert scored['generated_top_targets_outside_original_union'] == sorted(generated_top - union)
        assert scored['generated_gained_top_targets'] == sorted(generated_top - simple_top)
        assert scored['generated_lost_top_targets'] == sorted(simple_top - generated_top)
    valid = [s for s in scores if s['scorable']]
    assert summary['selected_tasks'] == len(tasks) and summary['scorable_tasks'] == len(valid)
    primary = summary['primary']
    for arm, means in primary['means'].items():
        for metric, value in means.items():
            assert value == statistics.mean(s['arms'][arm][metric] for s in valid)
    groups = defaultdict(list)
    for s in valid:
        groups[s['repo']].append(s['arms']['generated']['recall_at_10'] - s['arms']['simple_fusion']['recall_at_10'])
    rng = random.Random(20261103)
    repos = sorted(groups)
    draws = sorted(statistics.mean(v for repo in rng.choices(repos, k=len(repos)) for v in groups[repo]) for _ in range(5000))
    assert primary['descriptive_repo_bootstrap_95'] == [draws[int(.025 * 4999)], draws[int(.975 * 4999)]]
    assert math.isclose(summary['known_idle_cny'], sum(r['estimated_cny_idle'] or 0 for r in responses))
    assert math.isclose(summary['cumulative_reserved_cny'], manifest['prior_reserved_cny'] + sum(charged_or_reserved(r) for r in responses))
    key = load_key(ROOT / '.env')
    assert not any(key in p.read_text(encoding='utf-8') for p in args.run_dir.rglob('*') if p.is_file())
    result = {'tasks': len(tasks), 'scorable_tasks': len(valid), 'independent_metric_checks': checks,
              'frozen_inputs_and_receipts': 'passed', 'independent_rrf': 'passed', 'features_and_folds': 'passed',
              'independent_metrics_and_interval': 'passed', 'credential_scan': 'passed', 'new_api_calls': 0,
              'audit_source_sha256': file_hash(Path(__file__)), 'summary_sha256': file_hash(args.run_dir / 'summary.json')}
    if args.out:
        with args.out.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
            stream.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
