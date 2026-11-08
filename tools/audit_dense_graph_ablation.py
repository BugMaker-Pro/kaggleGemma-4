"""Independently rescore saved dense/graph ablation shortlists and frozen inputs."""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def load(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line]

def check_run(run: Path, root: Path = ROOT) -> dict:
    manifest = json.loads((run/'manifest.json').read_text())
    summary = json.loads((run/'summary.json').read_text())
    paths = {'features':root/'data/features_full.jsonl','embedding':root/'data/embed_retrieval.jsonl',
             'historical':root/'data/dense_scores.jsonl'}
    checks = 0
    portable_path = run/'portable-inputs.json'
    portable = json.loads(portable_path.read_text())['files'] if portable_path.exists() else {}
    def matches(path, key, expected):
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()==expected:
            return True
        alternate=portable.get(key,{})
        return alternate.get('raw_sha256')==expected and hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()==alternate.get('utf8_lf_sha256')
    for key,path in paths.items():
        if not matches(path,key,manifest['input_sha256'][key]):
            raise ValueError('Input hash changed: '+key)
        checks += 1
    for relative,expected in manifest['code_sha256'].items():
        path=root/relative.replace('\\','/')
        if not matches(path,relative,expected):
            raise ValueError('Frozen source changed: '+relative)
        checks += 1
    tasks={row['instance_id']:row for row in load(paths['features'])}
    historical={row['instance_id']:row for row in load(paths['historical'])}
    rows=load(run/'scores.jsonl')
    if len(rows)!=len(tasks) or {r['instance_id'] for r in rows}!=set(tasks) or set(manifest['task_ids'])!=set(tasks):
        raise ValueError('Missing or duplicated tasks')
    if manifest['removed_features']!=['in_degree','out_degree','near_seed']:
        raise ValueError('Unexpected feature removal')
    repos=sorted({t['repo'] for t in tasks.values()})
    expected_folds=[{'train':repos[::2],'test':repos[1::2]},{'train':repos[1::2],'test':repos[::2]}]
    if manifest['folds']!=expected_folds:
        raise ValueError('Repository fold changed')
    recomputed=[]
    for row in rows:
        task=tasks[row['instance_id']]
        if row['repo']!=task['repo']:raise ValueError('Task repository differs')
        record={'repo':row['repo']}
        for arm in ('with_graph','without_graph'):
            order=row[arm]['top10']
            if len(order)!=10 or len(set(order))!=10 or any(i<0 or i>=len(task['labels']) for i in order):
                raise ValueError('Invalid shortlist')
            symbol=sum(task['labels'][i] for i in order)/task['gold_total']
            target_files=set(task['gold_files'])
            file=len({task['files'][i] for i in order}&target_files)/len(target_files) if target_files else 0.0
            record[arm]={'symbol':symbol,'file':file}
            for metric,value in record[arm].items():
                if abs(value-row[arm][metric])>1e-12:raise ValueError('Saved metric differs')
                if arm=='with_graph' and abs(value-historical[row['instance_id']]['dense_'+metric])>1e-12:
                    raise ValueError('Historical baseline differs')
                checks += 1
        recomputed.append(record)
    for arm in ('with_graph','without_graph'):
        for metric in ('symbol','file'):
            mean=statistics.fmean(r[arm][metric] for r in recomputed)
            if abs(mean-summary['arms'][arm][metric])>1e-12:raise ValueError('Aggregate metric differs')
            checks += 1
    import numpy as np
    for metric in ('symbol','file'):
        values=defaultdict(list)
        for row in recomputed:values[row['repo']].append(row['with_graph'][metric]-row['without_graph'][metric])
        sums=[sum(values[repo]) for repo in repos]
        counts=np.asarray([len(values[repo]) for repo in repos])
        deltas=[d for repo in repos for d in values[repo]]
        observed=abs(sum(sums))
        p=sum(abs(sum(sign*value for sign,value in zip(signs,sums)))>=observed-1e-12 for signs in itertools.product((-1,1),repeat=len(repos)))/(2**len(repos))
        draws=np.random.default_rng(20261101).integers(0,len(repos),size=(10000,len(repos)))
        interval=np.quantile(np.asarray(sums)[draws].sum(axis=1)/counts[draws].sum(axis=1),[0.025,0.975])
        saved=summary[metric]
        if abs(p-saved['repository_signflip_p'])>1e-12 or any(abs(a-b)>1e-12 for a,b in zip(interval,saved['cluster_ci95'])):
            raise ValueError('Repository inference differs')
        for key,value in {'wins':sum(d>1e-12 for d in deltas),'losses':sum(d < -1e-12 for d in deltas),'delta':statistics.fmean(deltas)}.items():
            if abs(value-saved[key])>1e-12:raise ValueError('Paired effect differs')
        checks += 5
    return {'passed':True,'tasks':len(rows),'metric_and_hash_checks':checks,
            'scores_sha256':hashlib.sha256((run/'scores.jsonl').read_bytes()).hexdigest(),
            'summary_sha256':hashlib.sha256((run/'summary.json').read_bytes()).hexdigest(),
            'scope':'Input/source hashes, complete population, candidate metrics, baseline reproduction and repository inference; no retraining'}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-dir',type=Path,default=ROOT/'experiments/runs/dense-graph-ablation-20261108-v1')
    args=parser.parse_args()
    report=check_run(args.run_dir)
    (args.run_dir/'audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__':main()
