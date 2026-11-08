"""Independent hash, pool, feature, training-fold and metric audit; no inference/API."""
from __future__ import annotations
import argparse
import json
import math
import statistics
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from experiments.query_pilot import digest,file_hash
from tools.analyse_candidate_retention import read_rows
from tools.evaluate_query_pilot import gold_targets
from tools.run_feedback_pilot import write_json
from tools.run_strong_query_v2 import load_run,cluster_interval,ARM_NAMES
from tools.run_deepseek_feedback import load_key


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--parent',type=Path,default=ROOT/'experiments/runs/flash-replication-20261102-v1')
    p.add_argument('--features',type=Path,default=ROOT/'data/features_full.jsonl')
    p.add_argument('--embed',type=Path,default=ROOT/'data/embed_retrieval.jsonl')
    p.add_argument('--historical-metrics',type=Path,default=ROOT/'data/dense_scores.jsonl')
    p.add_argument('--model-dir',type=Path,default=ROOT/'models/bge-small-en-v1.5')
    p.add_argument('--gold',type=Path,default=ROOT/'data/gold_symbols.jsonl')
    p.add_argument('--out',type=Path)
    args=p.parse_args()
    m,inputs,responses,anchors=load_run(args)
    summary=json.loads((args.run_dir/'summary.json').read_text(encoding='utf-8'))
    train=json.loads((args.run_dir/'training_audit.json').read_text(encoding='utf-8'))
    historical=read_rows(args.run_dir/'historical_predictions.jsonl')
    assert not train['mismatching_tasks'] and len(historical)==train['tasks']==2232
    assert all(abs(r['recall_at_10']-r['historical_recall'])<1e-12 for r in historical)
    assert abs(statistics.mean(r['recall_at_10'] for r in historical)-train['historical_mean'])<1e-12
    for name,h in train['model_hashes'].items():assert file_hash(args.run_dir/'models'/name)==h
    assert summary['training_audit_sha256']==file_hash(args.run_dir/'training_audit.json')
    assert summary['predictions_sha256']==file_hash(args.run_dir/'predictions.jsonl')
    assert summary['gold_sha256']==file_hash(args.gold)
    predictions=read_rows(args.run_dir/'predictions.jsonl');scores=read_rows(args.run_dir/'scores.jsonl')
    assert [r['instance_id'] for r in predictions]==[r['instance_id'] for r in scores]==m['task_ids']
    gold={r['instance_id']:r for r in read_rows(args.gold)}
    metric_checks=0
    new_dense=0
    generated_new_vs_body=[]
    for i,(item,prediction,scored) in enumerate(zip(inputs,predictions,scores)):
        tid=item['instance_id'];anchor=anchors[tid]['anchor']
        path=args.run_dir/'candidates'/f'{i:03d}.json';candidate=json.loads(path.read_text(encoding='utf-8'))
        assert file_hash(path)==prediction['candidate_sha256']
        assert candidate['manifest_sha256']==prediction['manifest_sha256']==m['manifest_sha256']
        assert candidate['instance_id']==prediction['instance_id']==tid
        parent_pair=json.loads((args.parent/'retrieval_tasks'/f'{i:03d}.json').read_text(encoding='utf-8'))['results']
        assert candidate['arms']['generated']==next(r['order'] for r in parent_pair if r['arm']=='preplanned')
        assert candidate['arms']['body_original']==[r['id'] for r in item['baseline']['actions']['original']['candidates']]
        assert candidate['arms']['historical']==anchor['ids']
        assert candidate['generated_source_response_sha256']==digest(responses[2*i])
        assert len(candidate['ids'])==len(set(candidate['ids']))==len(candidate['rows'])
        assert not {'labels','gold','patch','gold_count'}&set(candidate)
        assert all(len(row)==17 and all(math.isfinite(v) for v in row) for row in candidate['rows'])
        x=dict(zip(candidate['ids'],candidate['rows']))
        for node,row,cosine in zip(anchor['ids'],anchor['rows'],anchors[tid]['cosine']):
            assert x[node]==row+[cosine]
        new_dense+=candidate['new_dense_candidates']
        assert candidate['new_dense_candidates']==len(set(candidate['ids'])-set(anchor['ids']))
        assert candidate['feature_audit']['existing_rows_verified']==len(anchor['ids'])
        fold=m['folds'][prediction['fold']]
        assert prediction['repo'] in fold['test_repos'] and prediction['repo'] not in fold['train_repos']
        assert not set(fold['train_repos'])&set(fold['test_repos'])
        assert tid not in fold['training_task_ids']
        targets=gold_targets(gold.get(tid,{}))
        assert scored['gold_count']==len(targets)
        for arm in ARM_NAMES:
            pool=candidate['arms'][arm]
            assert len(pool)<=200 and len(pool)==len(set(pool))
            assert prediction['arms'][arm]==sorted(pool,key=lambda node:-prediction['scores'][node])
            order=prediction['arms'][arm]
            for metric,chosen in (('coverage',order),('recall_at_10',order[:10])):
                expected=len(set(chosen)&targets)/len(targets) if targets else None
                actual=scored['arms'][arm][metric]
                assert expected is None and actual is None or expected is not None and abs(expected-actual)<1e-12
                metric_checks+=1
        generated_new_vs_body.append(len(set(candidate['arms']['generated'])-set(candidate['arms']['body_original'])))
    valid=[r for r in scores if r['scorable']]
    for arm in ARM_NAMES:
        for metric in ('coverage','recall_at_10'):
            assert abs(statistics.mean(r['arms'][arm][metric] for r in valid)-summary['means'][arm][metric])<1e-12
    for base in ('body_original','historical'):
        assert cluster_interval(valid,base)==summary['comparisons'][base]['descriptive_repo_bootstrap_95']
    assert new_dense==summary['new_dense_candidates']
    key=load_key(ROOT/'.env')
    assert not any(key in f.read_text(encoding='utf-8') for f in args.run_dir.rglob('*') if f.is_file())
    result={'tasks':len(inputs),'metric_checks':metric_checks,'historical_tasks_reproduced':train['tasks'],
            'frozen_features_and_candidate_pools_verified':True,'repo_training_isolation_verified':True,
            'new_dense_candidates':new_dense,'mean_candidates_new_vs_body_pool':statistics.mean(generated_new_vs_body),
            'credential_scan':'passed','no_new_api_calls':True,'summary_sha256':file_hash(args.run_dir/'summary.json'),
            'audit_source_sha256':file_hash(Path(__file__))}
    if args.out:write_json(args.out,result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
