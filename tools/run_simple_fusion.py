"""Fixed metadata/body RRF control using already frozen strong-model scores.

prepare -> replay (no gold) -> evaluate. No inference, API or parameter search.
"""
from __future__ import annotations
import argparse
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from experiments.query_pilot import canonical,digest,file_hash,merge_actions
from tools.analyse_candidate_retention import read_rows
from tools.run_feedback_pilot import write_json
from tools.run_strong_query_v2 import load_run as load_strong

CONFIG={'rrf_k':60,'candidate_cap':200,'final_k':10,'seed':20261103,'bootstrap_replicates':5000,
        'minimum_worthwhile_delta':.02,'weight_metadata':1,'weight_body':1}
ARMS=('historical','body_original','simple_fusion','generated')


def simple_pool(metadata,body,cap=200,k=60):
    if cap<0 or k<=0:raise ValueError('Invalid fusion settings')
    results={'original':{'candidates':[{'id':x} for x in metadata]},
             'body':{'candidates':[{'id':x} for x in body]}}
    return merge_actions(results,('body',),cap,k)


def replay_task(candidate,prediction):
    """Only candidate rankings and frozen model scores are accepted; no gold."""
    if set(candidate)!={'instance_id','repo','arms'} or set(prediction)!={'instance_id','scores'}:
        raise ValueError('Inference input must be explicitly projected without labels')
    if candidate['instance_id']!=prediction['instance_id']:raise ValueError('Task mismatch')
    if set(candidate['arms'])!={'historical','body_original','generated'}:raise ValueError('Unexpected source pools')
    pools={**candidate['arms'],'simple_fusion':simple_pool(candidate['arms']['historical'],candidate['arms']['body_original'])}
    scores=prediction['scores']
    for pool in pools.values():
        if len(pool)>200 or len(pool)!=len(set(pool)):raise ValueError('Invalid source candidate count')
        if any(n not in scores or not math.isfinite(scores[n]) for n in pool):raise ValueError('Missing/nonfinite frozen score')
    # Match parent stable pool-order tie policy: only membership changes, no model changes.
    orders={arm:sorted(pools[arm],key=lambda n:-scores[n]) for arm in ARMS}
    return {'instance_id':candidate['instance_id'],'repo':candidate['repo'],'pools':pools,'orders':orders,
            'metadata_body_union':sorted(set(pools['historical'])|set(pools['body_original'])),
            'union_size':len(set(pools['historical'])|set(pools['body_original'])),
            'unique_candidates_scored':{arm:len(pool) for arm,pool in pools.items()},
            'logical_retrieval_calls':{'historical':1,'body_original':1,'simple_fusion':2,'generated':3},
            'logical_generation_calls':{'historical':0,'body_original':0,'simple_fusion':0,'generated':1}}


def parent_args(args):
    return argparse.Namespace(run_dir=args.strong,parent=ROOT/'experiments/runs/flash-replication-20261102-v1',
        features=ROOT/'data/features_full.jsonl',embed=ROOT/'data/embed_retrieval.jsonl',
        historical_metrics=ROOT/'data/dense_scores.jsonl',model_dir=ROOT/'models/bge-small-en-v1.5')


def parent_inputs(args):
    m,inputs,responses,anchors=load_strong(parent_args(args))
    predictions=read_rows(args.strong/'predictions.jsonl')
    summary=json.loads((args.strong/'summary.json').read_text(encoding='utf-8'))
    if summary['predictions_sha256']!=file_hash(args.strong/'predictions.jsonl'):raise ValueError('Parent prediction hash mismatch')
    if [r['instance_id'] for r in predictions]!=m['task_ids']:raise ValueError('Parent prediction task IDs changed')
    train=json.loads((args.strong/'training_audit.json').read_text(encoding='utf-8'))
    if train['mismatching_tasks'] or train['tasks']!=2232:raise ValueError('Historical reproduction not verified')
    for name,h in train['model_hashes'].items():
        if file_hash(args.strong/'models'/name)!=h:raise ValueError('Frozen model changed')
    pairs=[]
    for i,(item,prediction) in enumerate(zip(inputs,predictions)):
        path=args.strong/'candidates'/f'{i:03d}.json'
        if file_hash(path)!=prediction['candidate_sha256']:raise ValueError('Parent candidate hash mismatch')
        candidate=json.loads(path.read_text(encoding='utf-8'))
        if candidate['instance_id']!=item['instance_id'] or candidate['manifest_sha256']!=m['manifest_sha256']:raise ValueError('Parent task identity mismatch')
        projected={k:candidate[k] for k in ('instance_id','repo','arms')}
        score_input={k:prediction[k] for k in ('instance_id','scores')}
        pairs.append((projected,score_input))
        # Validate original arms without looking at their evaluation labels or scores.
        for arm,pool in projected['arms'].items():
            if sorted(pool,key=lambda n:-score_input['scores'][n])!=prediction['arms'][arm]:raise ValueError('Parent ranking mismatch')
    return m,pairs


def prepare(args):
    parent,pairs=parent_inputs(args)
    m={'schema':1,'date':'2026-11-03','stage':'fixed_metadata_body_fusion_control',
       'task_ids':parent['task_ids'],'parent_manifest_sha256':parent['manifest_sha256'],
       'parent_artifacts':{n:file_hash(args.strong/n) for n in ('manifest.json','summary.json','predictions.jsonl','training_audit.json','audit.json')},
       'source_hashes':{p:file_hash(ROOT/p) for p in ('tools/run_simple_fusion.py','experiments/query_pilot.py','tools/run_strong_query_v2.py')},
       'config':CONFIG,'input_boundary':'frozen source rankings + per-candidate strong scores; labels opened only in evaluate',
       'primary':'generated minus simple_fusion macro symbol recall@10',
       'secondary':['candidate coverage','per-task target gains/losses','generated targets absent from both original pools','original arm replay equality'],
       'tie_policy':'RRF desc then ID for membership; stable pre-ranker pool order on strong-score ties, identical to parent convention',
       'statistical_plan':'5000 repository-cluster bootstrap; descriptive 95%; one primary contrast; threshold +.02; no automatic expansion',
       'cost_scope':'equal retained pool cap, not equal retrieval/generation cost. Reuse all frozen scores, no new dense/model/API inference.',
       'limits':['35 previously inspected historical tasks; post-hoc motivated exploratory control, not independent confirmation',
                 'exactly one equal-weight RRF rule k60; no quota or weight search',
                 'strong scores inherited with historical seed/file-stat anchors and new-candidate distribution limitation',
                 'generated arm uses prior Flash query calls; simple fusion has no generation calls',
                 'no method superiority or equivalence claim from absence of significance alone']}
    m['manifest_sha256']=digest(m)
    args.run_dir.mkdir(parents=True,exist_ok=False)
    write_json(args.run_dir/'manifest.json',m)
    print(canonical({'frozen_tasks':len(pairs),'rrf_k':60,'candidate_cap':200,'new_api_calls':0}))


def load_run(args):
    parent,pairs=parent_inputs(args)
    m=json.loads((args.run_dir/'manifest.json').read_text(encoding='utf-8'))
    expected=m.pop('manifest_sha256')
    if digest(m)!=expected:raise ValueError('Fusion manifest changed')
    m['manifest_sha256']=expected
    if m['config']!=CONFIG or m['parent_manifest_sha256']!=parent['manifest_sha256'] or m['task_ids']!=parent['task_ids']:raise ValueError('Frozen settings changed')
    for name,h in m['parent_artifacts'].items():
        if file_hash(args.strong/name)!=h:raise ValueError('Parent artifact changed')
    for name,h in m['source_hashes'].items():
        if file_hash(ROOT/name)!=h:raise ValueError('Source changed since freeze')
    return m,pairs


def replay(args):
    m,pairs=load_run(args)
    with (args.run_dir/'replay.jsonl').open('x',encoding='utf-8') as stream:
        for candidate,prediction in pairs:
            row=replay_task(candidate,prediction)
            row['manifest_sha256']=m['manifest_sha256']
            stream.write(canonical(row)+'\n')
    print(canonical({'replayed':len(pairs),'new_model_inference':0,'new_dense_encoding':0,'new_api_calls':0,'gold_read':False}))


def interval(rows):
    groups=defaultdict(list)
    for row in rows:groups[row['repo']].append(row['arms']['generated']['recall_at_10']-row['arms']['simple_fusion']['recall_at_10'])
    if len(groups)<2:return None
    repos=sorted(groups);rng=random.Random(CONFIG['seed']);n=CONFIG['bootstrap_replicates']
    draws=sorted(statistics.mean(v for repo in rng.choices(repos,k=len(repos)) for v in groups[repo]) for _ in range(n))
    return [draws[int(.025*(n-1))],draws[int(.975*(n-1))]]


def score_task(row,targets):
    simple_top=set(row['orders']['simple_fusion'][:10])&targets
    generated_top=set(row['orders']['generated'][:10])&targets
    original_union=set(row['metadata_body_union'])
    result={'instance_id':row['instance_id'],'repo':row['repo'],'gold_count':len(targets),'scorable':bool(targets),
            'arms':{a:{'coverage':len(set(row['pools'][a])&targets)/len(targets) if targets else None,
                       'recall_at_10':len(set(row['orders'][a][:10])&targets)/len(targets) if targets else None} for a in ARMS},
            'generated_gained_top_targets':sorted(generated_top-simple_top),
            'generated_lost_top_targets':sorted(simple_top-generated_top),
            'generated_top_targets_outside_original_union':sorted(generated_top-original_union),
            'original_union_coverage':len(original_union&targets)/len(targets) if targets else None,
            'fusion_removed_original_union_targets':sorted((original_union&targets)-set(row['pools']['simple_fusion']))}
    return result


def evaluate(args):
    m,pairs=load_run(args)
    replays=read_rows(args.run_dir/'replay.jsonl')
    if [r['instance_id'] for r in replays]!=m['task_ids']:raise ValueError('Missing/duplicate/reordered replay tasks')
    # Verify all membership and rank decisions without labels first.
    for row,(candidate,prediction) in zip(replays,pairs):
        expected={**replay_task(candidate,prediction),'manifest_sha256':m['manifest_sha256']}
        if row!=expected:raise ValueError('Fusion replay differs from frozen inputs')
    from tools.evaluate_query_pilot import gold_targets
    records=read_rows(args.gold);gold={r['instance_id']:r for r in records}
    if len(gold)!=len(records):raise ValueError('Duplicate gold task')
    scores=[]
    parent_meta={r['instance_id']:r for r in read_rows(ROOT/'experiments/runs/flash-replication-20261102-v1/tasks.jsonl')}
    for row in replays:
        record=gold.get(row['instance_id'])
        if record and any(record.get(k)!=parent_meta[row['instance_id']][k] for k in ('repo','base_commit')):raise ValueError('Gold identity mismatch')
        scored=score_task(row,gold_targets(record) if record else set())
        scored['gold_status']='missing_record' if record is None else ('symbols' if scored['scorable'] else 'no_symbols')
        scores.append(scored)
    valid=[r for r in scores if r['scorable']]
    if not valid:raise ValueError('No scorable tasks')
    means={arm:{metric:statistics.mean(r['arms'][arm][metric] for r in valid) for metric in ('coverage','recall_at_10')} for arm in ARMS}
    parent_scores={r['instance_id']:r for r in read_rows(args.strong/'scores.jsonl')}
    for row in scores:
        for arm in ('historical','body_original','generated'):
            if any(row['arms'][arm][k]!=parent_scores[row['instance_id']]['arms'][arm][k] for k in ('coverage','recall_at_10')):raise ValueError('Parent metrics failed to reproduce')
    ci=interval(valid);decision='uncertain'
    if ci and ci[0]>=.02:decision='generation_warrants_further_exploration'
    elif ci and ci[1]<.02:decision='no_worthwhile_generation_gain_under_this_control'
    summary={'manifest_sha256':m['manifest_sha256'],'replay_sha256':file_hash(args.run_dir/'replay.jsonl'),'gold_sha256':file_hash(args.gold),
             'tasks':len(scores),'scorable_tasks':len(valid),'missing_gold_tasks':[r['instance_id'] for r in scores if r['gold_status']=='missing_record'],
             'means':means,'primary_delta':means['generated']['recall_at_10']-means['simple_fusion']['recall_at_10'],
             'descriptive_repo_bootstrap_95':ci,'decision':decision,
             'improved_tasks':[r['instance_id'] for r in valid if r['arms']['generated']['recall_at_10']>r['arms']['simple_fusion']['recall_at_10']],
             'harmed_tasks':[r['instance_id'] for r in valid if r['arms']['generated']['recall_at_10']<r['arms']['simple_fusion']['recall_at_10']],
             'novel_top_target_tasks':[r['instance_id'] for r in valid if r['generated_top_targets_outside_original_union']],
             'fusion_truncation_loss_tasks':[r['instance_id'] for r in valid if r['fusion_removed_original_union_targets']],
             'parent_metric_reproduction':'all three parent arms identical',
             'cost':{'new_api_calls':0,'new_dense_encoding':0,'new_ranker_inference':0,
                     'logical_retrieval_calls_per_task':{'simple_fusion':2,'generated':3},
                     'logical_generation_calls_per_task':{'simple_fusion':0,'generated':1},
                     'retained_scored_candidates_total':{a:sum(len(r['pools'][a]) for r in replays) for a in ARMS},
                     'mean_simple_union_size':statistics.mean(r['union_size'] for r in replays)},
             'automatic_expansion':False,'limits':m['limits']}
    with (args.run_dir/'scores.jsonl').open('x',encoding='utf-8') as stream:
        for row in scores:stream.write(canonical(row)+'\n')
    write_json(args.run_dir/'summary.json',summary)
    print(json.dumps(summary,indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    for command in ('prepare','replay','evaluate'):
        ap=sub.add_parser(command);ap.add_argument('--run-dir',type=Path,required=True)
        ap.add_argument('--strong',type=Path,default=ROOT/'experiments/runs/strong-query-20261103-v2')
        if command=='evaluate':ap.add_argument('--gold',type=Path,default=ROOT/'data/gold_symbols.jsonl')
    args=p.parse_args();{'prepare':prepare,'replay':replay,'evaluate':evaluate}[args.command](args)


if __name__=='__main__':main()
