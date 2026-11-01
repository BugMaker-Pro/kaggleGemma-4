"""Build exact candidate graph projections, then run the frozen graph controls.

Examples:
  python tools/run_graph_controls.py --limit 3 --jobs 2 --out data/graph_controls_smoke.jsonl
  python tools/run_graph_controls.py --jobs 6 --out data/graph_controls.jsonl
  python tools/run_graph_controls.py --replay --out data/graph_controls.jsonl

Outputs are separate from historical experiments. --resume checks the manifest
and task IDs, requires complete JSONL rows, and does not silently omit errors.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.buildgraph import build_graph, read_snapshot
from experiments.graph_controls import (ATTEMPTS_PER_EDGE, SEEDS, adjacency, bm25_subset,
                                        body_documents, evaluate, projection, promote, reachable)
from experiments.snapindex import SnapshotIndex
from experiments.cached_graph import CachedBuilder, cached_body_scores

_BUILDER = CachedBuilder()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def read_rows(path: Path):
    with path.open(encoding='utf-8-sig') as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def prepare(payload: tuple[dict, dict, dict, str]) -> dict:
    feature, task, dense, repos = payload
    start = time.perf_counter()
    path = SnapshotIndex(repos).path_for(task)
    if path is None:
        raise FileNotFoundError(task['instance_id'])
    files = read_snapshot(path)
    loaded = time.perf_counter()
    graph, body_counts, cache_stats = _BUILDER.build(files, task['repo'])
    built = time.perf_counter()
    ids = feature['ids']
    if len(set(ids)) != len(ids) or any(i not in graph.nodes for i in ids):
        raise ValueError('Missing or duplicate candidates')
    candidate_files = [graph.nodes[i].get('file', '') for i in ids]
    if candidate_files != feature['files']:
        raise ValueError('Candidate file mapping differs from the saved features')
    edges = projection(graph.edges, ids)
    meta_order = list(range(len(ids)))
    reproduced = promote(meta_order, reachable(meta_order, adjacency(edges)))
    if reproduced != feature['rerank_top10']:
        raise ValueError(f"Graph reproduction differs: {reproduced} != {feature['rerank_top10']}")
    dense_order = dense['candidates']
    if sorted(dense_order) != meta_order or len(dense['scores']) != len(ids):
        raise ValueError('Incomplete or invalid dense candidate permutation')
    scores = cached_body_scores(body_counts, task.get('problem_statement') or '', ids)
    body_order = sorted(meta_order, key=lambda i: (-scores[i], i))
    finished = time.perf_counter()
    return {'instance_id': task['instance_id'], 'repo': feature['repo'],
            'base_commit': task['base_commit'], 'ids': ids, 'files': candidate_files,
            'labels': feature['labels'], 'gold_total': feature['gold_total'],
            'gold_files': feature['gold_files'], 'edges': edges,
            'orders': {'metadata': meta_order, 'body': body_order, 'dense': dense_order},
            'body_scores': [round(value, 12) for value in scores],
            'graph_reproduced': True, 'seconds': round(finished - start, 3),
            'timing': {'snapshot': round(loaded-start, 3), 'graph': round(built-loaded, 3),
                       'body': round(finished-built, 3)},
            'cache': cache_stats, 'graph_nodes': len(graph.nodes), 'graph_edges_all': len(graph.edges)}


def manifest(args, ids):
    paths = [Path(args.features), Path(args.tasks), Path(args.dense),
             ROOT / 'docs/graph-control-protocol.md', ROOT / 'experiments/graph_controls.py',
             ROOT / 'experiments/buildgraph.py', ROOT / 'experiments/retrieve.py',
             ROOT / 'experiments/cached_graph.py', ROOT / 'experiments/symbols.py', Path(__file__)]
    return {'schema': 1, 'task_ids': ids, 'random_seeds': SEEDS, 'attempts_per_edge': ATTEMPTS_PER_EDGE,
            'input_sha256': {str(path.resolve().relative_to(ROOT)): digest(path) for path in paths},
            'representations': ['metadata', 'body', 'dense'], 'k': 10, 'seeds_kept': 5}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--features', default=str(ROOT/'data/features_full.jsonl'))
    parser.add_argument('--tasks', default=str(ROOT/'data/swebench_full.jsonl'))
    parser.add_argument('--dense', default=str(ROOT/'data/embed_retrieval.jsonl'))
    parser.add_argument('--repos', default=str(ROOT/'data/repos'))
    parser.add_argument('--out', default=str(ROOT/'data/graph_controls.jsonl'))
    parser.add_argument('--jobs', type=int, default=6)
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--replay', action='store_true')
    args = parser.parse_args(argv)
    out = Path(args.out)
    context_path = out.with_name(out.stem + '_context.jsonl')
    manifest_path = out.with_suffix('.manifest.json')
    wanted = ('instance_id','repo','ids','files','labels','gold_total','gold_files','rerank_top10')
    features = [{key: row[key] for key in wanted} for row in read_rows(Path(args.features))]
    features.sort(key=lambda row: row['instance_id'])
    if args.limit:
        features = features[:args.limit]
    ids = [row['instance_id'] for row in features]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate feature tasks')
    tasks = {row['instance_id']: {key: row[key] for key in
             ('instance_id','repo','base_commit','problem_statement')}
             for row in read_rows(Path(args.tasks))}
    dense = {row['instance_id']: row for row in read_rows(Path(args.dense))}
    missing = set(ids) - tasks.keys() | (set(ids) - dense.keys())
    if missing:
        raise ValueError(f'Missing metadata/dense tasks: {sorted(missing)[:5]}')
    current_manifest = json.loads(json.dumps(manifest(args, ids)))
    if manifest_path.exists():
        if not (args.resume or args.replay):
            raise FileExistsError('Existing experiment: use --resume or choose another --out')
        if json.loads(manifest_path.read_text(encoding='utf-8')) != current_manifest:
            raise ValueError('Manifest changed; use a separate output for a different protocol/input')
    else:
        if out.exists() or context_path.exists():
            raise FileExistsError('Outputs exist without a manifest')
        manifest_path.write_text(json.dumps(current_manifest, indent=2)+'\n', encoding='utf-8')
    done = {}
    if context_path.exists():
        for row in read_rows(context_path):
            if row['instance_id'] in done:
                raise ValueError('Duplicate context record')
            done[row['instance_id']] = row
    if set(done) - set(ids):
        raise ValueError('Unexpected context tasks')
    # Recreate inexpensive evaluated rows from complete contexts on resume, so a
    # crash between writing context and writing results cannot omit a task.
    with out.open('w',encoding='utf-8',newline='\n') as result_handle:
        for task_id in sorted(done):
            result_handle.write(json.dumps(evaluate(done[task_id]))+'\n')
        result_handle.flush()
        pending = [row for row in features if row['instance_id'] not in done]
        print(f'tasks={len(ids)} cached={len(done)} pending={len(pending)} workers={args.jobs}',flush=True)
        if args.replay and pending:
            raise ValueError('Replay requires a complete context file')
        errors = []
        if args.resume and out.with_suffix('.errors.json').exists():
            out.with_suffix('.errors.json').unlink()
        start = time.perf_counter()
        with context_path.open('a',encoding='utf-8',newline='\n') as context_handle:
            if pending:
                with ProcessPoolExecutor(max_workers=args.jobs) as pool:
                    jobs = {pool.submit(prepare, (row,tasks[row['instance_id']],dense[row['instance_id']],args.repos)):
                            row['instance_id'] for row in pending}
                    count = 0
                    for future in as_completed(jobs):
                        task_id = jobs[future]
                        try:
                            context = future.result()
                            result = evaluate(context)
                            context_handle.write(json.dumps(context)+'\n')
                            context_handle.flush()
                            result_handle.write(json.dumps(result)+'\n')
                            result_handle.flush()
                            count += 1
                            if count <= 3 or count % 20 == 0 or count == len(pending):
                                elapsed = time.perf_counter()-start
                                eta = elapsed/max(count,1)*(len(pending)-count)/60
                                print(f'complete={len(done)+count}/{len(ids)} elapsed={elapsed:.1f}s eta={eta:.1f}m '
                                      f'last_timing={context["timing"]}',flush=True)
                        except Exception as error:
                            errors.append({'instance_id':task_id,'error':f'{type(error).__name__}: {error}'})
                            print(f'ERROR {task_id}: {error}',flush=True)
        if errors:
            out.with_suffix('.errors.json').write_text(json.dumps(errors,indent=2)+'\n',encoding='utf-8')
            raise RuntimeError(f'{len(errors)} tasks failed; no complete-result claim is valid')
    final_ids = [row['instance_id'] for row in read_rows(out)]
    if sorted(final_ids) != ids:
        raise ValueError('Output population differs from intended population')
    print(f'COMPLETE {len(ids)} tasks; every graph reproduced; {out}',flush=True)
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    except AttributeError:
        pass
    raise SystemExit(main())
