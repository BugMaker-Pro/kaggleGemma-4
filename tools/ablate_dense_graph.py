"""Frozen paired removal of topology features from the published dense-fusion ranker.

Reproduce the historical full ranker before fitting the ablation. Candidate
pools, text/evidence features, dense scores, repository folds and seeds are fixed.
This tests topology-derived columns conditional on an AST symbol index; it does
not compare graph-free repository parsing with graph construction.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault('OMP_NUM_THREADS', '4')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np
from tools.rank_with_dense import train, file_recall
from tools.run_combo_ltr import ORDER, SEEDS, ROUNDS, LEARNING_RATE, order_from, recall_all
from tools.analyse_graph_controls import paired_summary

GRAPH_COLUMNS = ('in_degree', 'out_degree', 'near_seed')

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]

def unique(rows: list[dict]) -> dict[str, dict]:
    result = {row['instance_id']: row for row in rows}
    if len(result) != len(rows):
        raise ValueError('Duplicate task IDs')
    return result

def prepare(features: list[dict], embedding_rows: list[dict], historical_rows: list[dict]):
    embeddings, historical = unique(embedding_rows), unique(historical_rows)
    ids = set(unique(features))
    if ids != set(embeddings) or ids != set(historical):
        raise ValueError('Feature, embedding and historical populations differ')
    for task in features:
        if tuple(task['features']) != ORDER:
            raise ValueError('Unexpected feature order')
        n = len(task['rows'])
        if not n or n != len(task['labels']) or n != len(task['ids']) or n != len(task['files']):
            raise ValueError('Candidate alignment mismatch')
        if any(len(row) != len(ORDER) for row in task['rows']):
            raise ValueError('Unexpected candidate feature width')
        if task.get('gold_total', 0) <= 0:
            raise ValueError('Unscorable task included')
        embedding = embeddings[task['instance_id']]
        candidates, scores = embedding['candidates'], embedding['scores']
        if len(candidates) != len(scores) or len(set(candidates)) != len(candidates):
            raise ValueError('Embedding candidate alignment mismatch')
        if any(not isinstance(i, int) or i < 0 or i >= n for i in candidates):
            raise ValueError('Embedding candidate out of bounds')
        cosine = [0.0] * n
        for index, score in zip(candidates, scores):
            cosine[index] = score
        task['rows'] = [list(values) + [cosine[i]] for i, values in enumerate(task['rows'])]
    return historical

def metrics(task, order):
    return {'symbol': recall_all(order, task['labels'], task['gold_total']),
            'file': file_recall(order, task['files'], task['gold_files'])}

def run_arm(tasks, folds, columns, name, out):
    results = {}
    for fold_index, (training, testing) in enumerate(folds):
        train_tasks = [task for task in tasks if task['repo'] in training]
        test_tasks = [task for task in tasks if task['repo'] in testing]
        matrix = np.asarray([[row[i] for i in columns] for task in test_tasks for row in task['rows']])
        predictions = []
        for seed in SEEDS:
            started = time.monotonic()
            model = train(train_tasks, seed, columns)
            model.save_model(str(out/'models'/f'{name}_fold{fold_index}_seed{seed}.txt'))
            predictions.append(model.predict(matrix))
            print(f'{name} fold={fold_index} seed={seed} finished in {time.monotonic()-started:.1f}s', flush=True)
        averaged = np.mean(predictions, axis=0)
        position = 0
        for task in test_tasks:
            size = len(task['rows'])
            order = order_from(list(averaged[position:position+size]), task['labels'])
            results[task['instance_id']] = {'top10': order[:10], **metrics(task, order)}
            position += size
        if position != len(averaged):
            raise ValueError('Prediction alignment mismatch')
    return results

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=ROOT/'experiments/runs/dense-graph-ablation-20261108-v1')
    args = parser.parse_args(argv)
    if args.out.exists():
        raise ValueError('Refusing to overwrite an existing run')
    inputs = {'features': ROOT/'data/features_full.jsonl', 'embedding': ROOT/'data/embed_retrieval.jsonl',
              'historical': ROOT/'data/dense_scores.jsonl'}
    tasks = load(inputs['features'])
    historical = prepare(tasks, load(inputs['embedding']), load(inputs['historical']))
    if len(tasks) != 2232 or len({t['repo'] for t in tasks}) != 12:
        raise ValueError('Expected 2232 scorable tasks from 12 repositories')
    repos = sorted({task['repo'] for task in tasks})
    half = set(repos[::2])
    folds = ((half, set(repos)-half), (set(repos)-half, half))
    full_columns = list(range(len(ORDER)+1))
    reduced_columns = [i for i, name in enumerate((*ORDER, 'dense_cosine')) if name not in GRAPH_COLUMNS]
    args.out.mkdir(parents=True)
    (args.out/'models').mkdir()
    manifest = {'input_sha256': {key:sha(path) for key,path in inputs.items()},
                'code_sha256': {str(path.relative_to(ROOT)):sha(path) for path in
                               (Path(__file__).resolve(), ROOT/'tools/rank_with_dense.py', ROOT/'tools/run_combo_ltr.py', ROOT/'tools/analyse_graph_controls.py')},
                'tasks':len(tasks),'task_ids':[t['instance_id'] for t in tasks],
                'folds':[{'train':sorted(a),'test':sorted(b)} for a,b in folds],
                'removed_features': GRAPH_COLUMNS,'full_features':[*ORDER,'dense_cosine'],
                'seeds':SEEDS,'rounds':ROUNDS,'learning_rate':LEARNING_RATE,
                'omp_threads':os.environ['OMP_NUM_THREADS'],
                'versions':{key:importlib.metadata.version(key) for key in ('lightgbm','numpy')},
                'primary':'with_graph minus without_graph macro symbol recall@10',
                'secondary':'file recall, task wins/losses, per-repository deltas',
                'inference':'10000 repository cluster resamples, exhaustive 12-repository sign flips; one primary comparison',
                'baseline_gate':'all historical dense_symbol and dense_file values must match within 1e-12 before fitting ablation',
                'scope':'post-hoc follow-up on reused benchmark; symbol extraction and candidate pool unchanged'}
    (args.out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Frozen protocol and input hashes; fitting reproduction baseline first.',flush=True)
    full = run_arm(tasks, folds, full_columns, 'with_graph', args.out)
    mismatches = []
    for task_id, result in full.items():
        for key in ('symbol','file'):
            if abs(result[key]-historical[task_id]['dense_'+key]) > 1e-12:
                mismatches.append({'instance_id':task_id,'metric':key,'historical':historical[task_id]['dense_'+key],'reproduced':result[key]})
    (args.out/'baseline_audit.json').write_text(json.dumps({'passed':not mismatches,'mismatches':mismatches,'tasks':len(full)},indent=2),encoding='utf-8')
    if mismatches:
        raise ValueError(f'Historical reproduction mismatch: {len(mismatches)} metrics; ablation not run')
    print('All 4464 historical metrics reproduced; fitting graph-feature removal.',flush=True)
    reduced = run_arm(tasks, folds, reduced_columns, 'without_graph', args.out)
    rows=[]
    for task in tasks:
        task_id=task['instance_id']
        rows.append({'instance_id':task_id,'repo':task['repo'],'with_graph':full[task_id],'without_graph':reduced[task_id]})
    (args.out/'scores.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
    summary={'tasks':len(rows),'arms':{name:{metric:statistics.fmean(row[name][metric] for row in rows) for metric in ('symbol','file')} for name in ('with_graph','without_graph')}}
    for metric in ('symbol','file'):
        summary[metric]=paired_summary([row['with_graph'][metric]-row['without_graph'][metric] for row in rows],[row['repo'] for row in rows])
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary['arms']),flush=True)
    print('Primary contrast:',json.dumps(summary['symbol']),flush=True)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
