"""Prospectively configured exploratory Flash replication, disjoint from 12-task pilot.

prepare -> inputs -> generate -> retrieve -> evaluate. Old frozen sources untouched.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from experiments.feedback_pilot import ARMS, CONFIG, code_excerpts, paired_requests, rank_queries, validate_pair_order
from experiments.query_pilot import TaskInput, canonical, digest, file_hash, sanitize_task, stable_search
from experiments.buildgraph import read_snapshot
from experiments.snapindex import SnapshotIndex
from tools.analyse_candidate_retention import read_rows
from tools.run_query_pilot import retrieve_task
from tools.run_feedback_pilot import build_index, validate_retrieval, write_json
from tools.run_deepseek_feedback import (API_CONFIG, ENDPOINT, PRICES, NoRedirect, decode_response,
                                        load_key, reserve_cost, utc_now)

SEED=2026110202
SOURCE_PATHS=sorted([p.relative_to(ROOT).as_posix() for p in (ROOT/'experiments').glob('*.py')]+[
    'tools/run_flash_replication.py','tools/run_query_pilot.py','tools/run_feedback_pilot.py',
    'tools/run_deepseek_feedback.py','tools/analyse_candidate_retention.py','tools/evaluate_query_pilot.py'])


def select_tasks(rows,excluded,per_repo=3,seed=SEED):
    if per_repo < 1:
        raise ValueError('per_repo must be positive')
    groups=defaultdict(list)
    seen=set()
    for row in rows:
        clean=sanitize_task(row)
        if clean['instance_id'] in seen:
            raise ValueError('Duplicate task ID')
        seen.add(clean['instance_id'])
        if clean['instance_id'] not in excluded:
            groups[clean['repo']].append(clean)
    return [task for repo in sorted(groups) for task in sorted(groups[repo],key=lambda r:digest([seed,r['instance_id']]))[:per_repo]]


def schedule_requests(requests,seed=SEED):
    """Hash-balanced arm order; normalized output still uses task/ARMS order."""
    pairs=[requests[i:i+2] for i in range(0,len(requests),2)]
    return [r['request_sha256'] for pair in pairs for r in (pair if int(digest([seed,pair[0]['instance_id'],'arm-order']),16)%2==0 else pair[::-1])]


def prepare(args):
    pilot=json.loads((args.pilot/'manifest.json').read_text(encoding='utf-8'))
    previous=json.loads((args.pilot/'sensitivity.json').read_text(encoding='utf-8'))
    prior_bound=previous['known_peak_plus_unknown_reservation_cny']
    excluded=set(pilot['task_ids'])
    selected=select_tasks(read_rows(args.tasks),excluded)
    if not selected:
        raise ValueError('No tasks available')
    m={'schema':1,'stage':'disjoint_exploratory_flash_replication','date':'2026-11-02','created_utc':utc_now(),
       'task_ids':[r['instance_id'] for r in selected],
       'excluded_task_ids':sorted(excluded),'excluded_manifest_sha256':file_hash(args.pilot/'manifest.json'),
       'source_tasks_sha256':file_hash(args.tasks),'selection':{'per_repo':3,'seed':SEED,'rule':'lowest SHA256(seed, task ID) per repo, exclude pilot IDs; no label/outcome selection'},
       'repo_counts':{repo:sum(r['repo']==repo for r in selected) for repo in sorted({r['repo'] for r in selected})},
       'config':CONFIG,'api':API_CONFIG,'endpoint':ENDPOINT,'prices':PRICES,
       'source_hashes':{p:file_hash(ROOT/p) for p in SOURCE_PATHS},
       'budget_cny':5-prior_bound,'prior_run_reserved_cny':prior_bound,'combined_budget_cny':5,
       'max_calls':2*len(selected),'request_order_seed':SEED,
       'failure_policy':{'attempts_per_request':1,'timeout_seconds':60,'consecutive_transport_stop':3,
                         'pair_fallback':'if either arm is not ok, BOTH use original ranking; retain raw generation records',
                         'unknown_cost':'null tokens; reserve per-request planning cost; never resend started uncertain calls',
                         'http_failure':'stop; no automatic retry or silent substitution',
                         'integrity_failure':'stop without silently dropping tasks'},
       'evaluation':{'primary':'all scorable tasks, task-macro feedback minus preplanned symbol recall@10 with paired fallback',
                     'secondary':['candidate coverage','original query baseline','complete-pair sensitivity','repository means','gain/loss counts'],
                     'minimum_worthwhile_delta':.02,'bootstrap_seed':SEED,'bootstrap_replicates':5000,
                     'bootstrap_unit':'repository with replacement, keep all tasks in sampled clusters',
                     'interval':'descriptive percentile 95%; one primary contrast, others diagnostic',
                     'automatic_expansion':False,'test_scope':'historically developed Lite; disjoint from 12-task pilot, not unseen confirmation'},
       'limits':['same issue/code windows, same Flash generation parameters and RRF as pilot',
                 'API alias mutable; provider model/fingerprint recorded',
                 'exact API tokenizer unavailable; usage postchecked; preflight UTF-8 reserve is planning estimate',
                 'same resource ceilings do not mean same actual tokens or costs',
                 'not an evidence-state controller or repair-success experiment',
                 'chosen after observing initial pilot; no claim of independent confirmatory dataset']}
    args.run_dir.mkdir(parents=True,exist_ok=False)
    with (args.run_dir/'tasks.jsonl').open('x',encoding='utf-8') as stream:
        for row in selected:stream.write(canonical(row)+'\n')
    m['tasks_sha256']=file_hash(args.run_dir/'tasks.jsonl')
    m['manifest_sha256']=digest(m)
    write_json(args.run_dir/'manifest.json',m)
    print(canonical({'prepared_tasks':len(selected),'planned_calls':m['max_calls'],'repo_counts':m['repo_counts'],'remaining_budget_cny':m['budget_cny']}))


def load_run(directory):
    m=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    fingerprint=m.pop('manifest_sha256')
    if digest(m)!=fingerprint:raise ValueError('Manifest changed')
    m['manifest_sha256']=fingerprint
    if file_hash(directory/'tasks.jsonl')!=m['tasks_sha256']:raise ValueError('Task input changed')
    for name,expected in m['source_hashes'].items():
        if file_hash(ROOT/name)!=expected:raise ValueError(f'Frozen source changed: {name}')
    tasks=[TaskInput.from_mapping(r) for r in read_rows(directory/'tasks.jsonl')]
    if [t.instance_id for t in tasks]!=m['task_ids'] or set(m['task_ids'])&set(m['excluded_task_ids']):
        raise ValueError('Task identity/exclusion mismatch')
    if m['api']!=API_CONFIG or m['config']!=CONFIG or m['endpoint']!=ENDPOINT:raise ValueError('API/config changed')
    return m,tasks


def baseline_config():
    # Parent diagnostic query lists are retained for audit, without scoring them.
    return {'issue_char_limit':20000,'query_char_limit':4000,'max_source_chars':CONFIG['max_source_chars'],
            'max_index_nodes':CONFIG['max_index_nodes'],'body_lines':80,'per_action_candidates':200}


def inputs(args):
    m,tasks=load_run(args.run_dir)
    directory=args.run_dir/'input_tasks'
    directory.mkdir(exist_ok=True)
    sealed=[]
    for i,task in enumerate(tasks):
        path=directory/f'{i:03d}.json'
        if path.exists():
            row=json.loads(path.read_text(encoding='utf-8'))
            if row['instance_id']!=task.instance_id or row['manifest_sha256']!=m['manifest_sha256']:raise ValueError('Stored inputs mismatch')
        else:
            trace=retrieve_task(task,args.repos,baseline_config())
            if trace['status']!='ok':raise RuntimeError('Baseline preprocessing failed; no task dropped')
            snapshot=SnapshotIndex(args.repos).path_for({'instance_id':task.instance_id,'repo':task.repo,'base_commit':task.base_commit})
            files=read_snapshot(snapshot)
            if digest(sorted(files.items()))!=trace['snapshot_content_sha256']:raise ValueError('Snapshot changed during preparation')
            excerpts=code_excerpts(files,trace['actions']['original']['candidates'])
            row={'instance_id':task.instance_id,'manifest_sha256':m['manifest_sha256'],'baseline':trace,
                 'excerpts':excerpts,'requests':paired_requests(task,excerpts)}
            write_json(path,row)
        sealed.append(row)
        print(f'inputs {i+1}/{len(tasks)} {task.instance_id}',flush=True)
    requests=[r for task in sealed for r in task['requests']]
    validate_pair_order(requests,m['task_ids'])
    reservation=sum(reserve_cost(r) for r in requests)
    if reservation>m['budget_cny']:raise ValueError('API planning reservation exceeds remaining budget')
    seal={'manifest_sha256':m['manifest_sha256'],'input_files':{p.name:file_hash(p) for p in sorted(directory.glob('*.json'))},
          'request_ids':[r['request_sha256'] for r in requests],'schedule':schedule_requests(requests),
          'planning_reservation_cny':reservation,'created_utc':utc_now()}
    seal['sha256']=digest(seal)
    write_json(args.run_dir/'inputs.seal.json',seal)
    print(canonical({'inputs_sealed':len(requests),'reservation_cny':reservation,'prior_plus_new_reservation_cny':reservation+m['prior_run_reserved_cny']}))


def load_inputs(directory):
    m,tasks=load_run(directory)
    seal=json.loads((directory/'inputs.seal.json').read_text(encoding='utf-8'))
    expected=seal.pop('sha256')
    if digest(seal)!=expected or seal['manifest_sha256']!=m['manifest_sha256']:raise ValueError('Input seal changed')
    rows=[]
    for name,fingerprint in seal['input_files'].items():
        path=directory/'input_tasks'/name
        if file_hash(path)!=fingerprint:raise ValueError('Input file changed')
        rows.append(json.loads(path.read_text(encoding='utf-8')))
    requests=[r for row in rows for r in row['requests']]
    validate_pair_order(requests,m['task_ids'])
    if [r['request_sha256'] for r in requests]!=seal['request_ids'] or schedule_requests(requests)!=seal['schedule']:raise ValueError('Request order changed')
    return m,rows,requests,seal


def unknown_response(request,m):
    return {'instance_id':request['instance_id'],'arm':request['arm'],'request_sha256':request['request_sha256'],
            'manifest_sha256':m['manifest_sha256'],'model_sha256':digest(API_CONFIG),'model_calls':1,
            'provider_model':None,'system_fingerprint':None,'input_tokens':None,'output_tokens':None,
            'provider_usage':None,'status':'transport_unknown','raw_output':'','queries':[],
            'error':'Uncertain transport/JSON completion; never retried','estimated_cny_idle':None,
            'estimated_cny_peak':None,'reservation_cny':reserve_cost(request)}


def charged_or_reserved(row):
    return row['estimated_cny_peak'] if row['estimated_cny_peak'] is not None else row['reservation_cny']


def generate(args):
    m,_,requests,seal=load_inputs(args.run_dir)
    if (args.run_dir/'responses.jsonl').exists():raise FileExistsError('Response set already complete; refusing more API calls')
    key=load_key(args.env_file)
    by_id={r['request_sha256']:r for r in requests}
    receipts=args.run_dir/'receipts'
    receipts.mkdir(exist_ok=True)
    opener=urllib.request.build_opener(NoRedirect())
    m={**m,'model_sha256':digest(API_CONFIG)}
    rows={}
    consecutive=0
    for i,request_id in enumerate(seal['schedule']):
        request=by_id[request_id]
        path=receipts/f'{i:03d}.json'
        started=receipts/f'{i:03d}.started.json'
        error=receipts/f'{i:03d}.error.json'
        if path.exists():
            receipt=json.loads(path.read_text(encoding='utf-8'))
            if receipt['request_sha256']!=request_id or receipt['manifest_sha256']!=m['manifest_sha256']:raise ValueError('Receipt mismatch')
            row=decode_response(receipt['response'],request,m,receipt['seconds'])
        elif error.exists():
            err=json.loads(error.read_text(encoding='utf-8'))
            if err.get('request_sha256')!=request_id:raise ValueError('Error receipt mismatch')
            if err.get('http_status'):raise RuntimeError('Prior HTTP failure; refusing continuation without review')
            row=unknown_response(request,m)
        else:
            if started.exists():raise RuntimeError('Potentially active request: no resend permitted')
            if sum(charged_or_reserved(r) for r in rows.values())+reserve_cost(request)>m['budget_cny']:raise ValueError('Budget guard stopped before sending')
            write_json(started,{'request_sha256':request_id,'manifest_sha256':m['manifest_sha256'],'started_utc':utc_now()})
            payload={**API_CONFIG,'messages':request['messages']}
            req=urllib.request.Request(ENDPOINT,data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
            start=time.perf_counter()
            try:
                with opener.open(req,timeout=60) as response:raw=json.loads(response.read().decode('utf-8'))
            except urllib.error.HTTPError as exc:
                write_json(error,{'request_sha256':request_id,'http_status':exc.code})
                raise RuntimeError(f'Provider HTTP {exc.code}: stopped without retry') from None
            except Exception:
                write_json(error,{'request_sha256':request_id,'error':'transport_or_json_error','elapsed_seconds':time.perf_counter()-start})
                row=unknown_response(request,m)
            else:
                if key in canonical(raw):raise RuntimeError('Credential echoed; refusing persistence')
                write_json(path,{'request_sha256':request_id,'manifest_sha256':m['manifest_sha256'],
                                 'received_utc':utc_now(),'seconds':time.perf_counter()-start,'response':raw})
                row=decode_response(raw,request,m,time.perf_counter()-start)
        rows[request_id]=row
        consecutive=consecutive+1 if row['status']=='transport_unknown' else 0
        print(f"api {i+1}/{len(requests)} {request['instance_id']} {request['arm']} {row['status']}",flush=True)
        if consecutive>=m['failure_policy']['consecutive_transport_stop']:raise RuntimeError('Three consecutive transport failures; stopped, no retries')
    with (args.run_dir/'responses.jsonl').open('x',encoding='utf-8') as stream:
        for request in requests:stream.write(canonical(rows[request['request_sha256']])+'\n')
    print(canonical({'requests':len(rows),'known_cny_idle':sum(r['estimated_cny_idle'] or 0 for r in rows.values()),
                     'peak_plus_unknown_reservation_cny':sum(charged_or_reserved(r) for r in rows.values())}))


def effective_pair(responses):
    if len(responses)!=2 or [r['arm'] for r in responses]!=list(ARMS):raise ValueError('Expected canonical pair')
    fallback=any(r['status']!='ok' for r in responses)
    return [{**r,'queries':[] if fallback else r['queries'],'status':'paired_fallback' if fallback else 'ok'} for r in responses]


def validate_generated(directory,m,requests):
    responses=read_rows(directory/'responses.jsonl')
    if [(r['instance_id'],r['arm'],r['request_sha256']) for r in responses]!=[(r['instance_id'],r['arm'],r['request_sha256']) for r in requests]:raise ValueError('Response identities changed')
    seal=json.loads((directory/'inputs.seal.json').read_text(encoding='utf-8'))
    schedule_index={rid:i for i,rid in enumerate(seal['schedule'])}
    for row,request in zip(responses,requests):
        i=schedule_index[request['request_sha256']]
        path=directory/'receipts'/f'{i:03d}.json'
        if path.exists():
            receipt=json.loads(path.read_text(encoding='utf-8'))
            expected=decode_response(receipt['response'],request,{**m,'model_sha256':digest(API_CONFIG)},row['seconds'])
        else:
            err=json.loads((directory/'receipts'/f'{i:03d}.error.json').read_text(encoding='utf-8'))
            if err.get('http_status') or err.get('request_sha256')!=request['request_sha256']:raise ValueError('Invalid transport failure record')
            expected=unknown_response(request,m)
        if row!=expected:raise ValueError('Response differs from provider receipt')
    if sum(charged_or_reserved(r) for r in responses)>m['budget_cny']:raise ValueError('Run exceeded reserved budget')
    return responses


def retrieve(args):
    m,inputs,requests,_=load_inputs(args.run_dir)
    responses=validate_generated(args.run_dir,m,requests)
    directory=args.run_dir/'retrieval_tasks'
    directory.mkdir(exist_ok=True)
    for i,item in enumerate(inputs):
        path=directory/f'{i:03d}.json'
        if path.exists():
            saved=json.loads(path.read_text(encoding='utf-8'))
            if saved['manifest_sha256']!=m['manifest_sha256'] or saved['instance_id']!=item['instance_id']:raise ValueError('Stored retrieval identity changed')
            print(f'retrieval cached {i+1}/{len(inputs)}',flush=True)
            continue
        trace=item['baseline']
        snapshot=SnapshotIndex(args.repos).path_for(trace)
        files=read_snapshot(snapshot)
        if digest(sorted(files.items()))!=trace['snapshot_content_sha256']:raise ValueError('Snapshot changed')
        start=time.perf_counter()
        index=build_index(files)
        original=trace['actions']['original']
        replay,_=stable_search(index,original['query'],200)
        if [(x['id'],x['score']) for x in replay]!=[(x['id'],x['score']) for x in original['candidates']]:raise ValueError('Original ranking no longer reproduces')
        shared_seconds=time.perf_counter()-start
        effective=effective_pair(responses[2*i:2*i+2])
        results=[]
        for raw,response in zip(responses[2*i:2*i+2],effective):
            actions=[]
            for query in response['queries']:
                start=time.perf_counter()
                candidates,scored=stable_search(index,query,200)
                actions.append({'query':query,'candidates':candidates,'scored_documents':scored,'seconds':time.perf_counter()-start})
            result={'instance_id':trace['instance_id'],'repo':trace['repo'],'base_commit':trace['base_commit'],
                    'arm':response['arm'],'status':response['status'],'manifest_sha256':m['manifest_sha256'],
                    'request_sha256':response['request_sha256'],'response_sha256':digest(response),'raw_response_sha256':digest(raw),
                    'actions':actions,'order':rank_queries(original['candidates'],[a['candidates'] for a in actions]),
                    'retrieval_calls':1+len(actions),'index_nodes':index.n,
                    'scored_documents':original['cost']['scored_documents']+sum(a['scored_documents'] for a in actions),
                    'source_chars_read':sum(map(len,files.values())),'shared_index_seconds':shared_seconds}
            validate_retrieval(result,response,trace,m)
            results.append(result)
        write_json(path,{'instance_id':trace['instance_id'],'manifest_sha256':m['manifest_sha256'],'results':results})
        print(f'retrieved {i+1}/{len(inputs)} {trace["instance_id"]}',flush=True)


def cluster_interval(rows,seed=SEED,n=5000):
    groups=defaultdict(list)
    for row in rows:groups[row['repo']].append(row['arms']['feedback']['recall_at_10']-row['arms']['preplanned']['recall_at_10'])
    if len(groups)<2:return None
    repos=sorted(groups)
    rng=random.Random(seed)
    draws=sorted(statistics.mean(v for repo in rng.choices(repos,k=len(repos)) for v in groups[repo]) for _ in range(n))
    return [draws[int(.025*(n-1))],draws[int(.975*(n-1))]]


def summarize_rows(rows):
    if not rows:return {'tasks':0}
    means={arm:{metric:statistics.mean(r['arms'][arm][metric] for r in rows) for metric in ('coverage','recall_at_10')} for arm in ARMS}
    return {'tasks':len(rows),'means':means,'primary_delta':means['feedback']['recall_at_10']-means['preplanned']['recall_at_10'],
            'descriptive_repo_bootstrap_95':cluster_interval(rows),
            'improved_tasks':[r['instance_id'] for r in rows if r['arms']['feedback']['recall_at_10']>r['arms']['preplanned']['recall_at_10']],
            'harmed_tasks':[r['instance_id'] for r in rows if r['arms']['feedback']['recall_at_10']<r['arms']['preplanned']['recall_at_10']]}


def evaluate(args):
    from tools.evaluate_query_pilot import gold_targets
    m,inputs,requests,_=load_inputs(args.run_dir)
    responses=validate_generated(args.run_dir,m,requests)
    # Validate ALL paired membership and costs before loading labels.
    retrievals=[]
    for i,item in enumerate(inputs):
        saved=json.loads((args.run_dir/'retrieval_tasks'/f'{i:03d}.json').read_text(encoding='utf-8'))
        if saved['instance_id']!=item['instance_id'] or saved['manifest_sha256']!=m['manifest_sha256']:raise ValueError('Retrieval task identity changed')
        pair=saved['results']
        effective=effective_pair(responses[2*i:2*i+2])
        if len(pair)!=2:raise ValueError('Incomplete retrieval pair')
        for result,response,raw in zip(pair,effective,responses[2*i:2*i+2]):
            if result['raw_response_sha256']!=digest(raw):raise ValueError('Raw response provenance changed')
            validate_retrieval(result,response,item['baseline'],m)
        retrievals.append(pair)
    records=read_rows(args.gold)
    gold={r['instance_id']:r for r in records}
    if len(gold)!=len(records):raise ValueError('Duplicate gold ID')
    scores=[]
    for i,(item,pair) in enumerate(zip(inputs,retrievals)):
        trace=item['baseline']
        record=gold.get(item['instance_id'])
        if record and any(record.get(k)!=trace[k] for k in ('repo','base_commit')):raise ValueError('Gold identity mismatch')
        targets=gold_targets(record) if record else set()
        original=[x['id'] for x in trace['actions']['original']['candidates']]
        def metrics(order):
            return {'coverage':len(set(order)&targets)/len(targets) if targets else None,
                    'recall_at_10':len(set(order[:10])&targets)/len(targets) if targets else None,
                    'new_top_targets':sorted((set(order[:10])&targets)-set(original[:10])),
                    'lost_top_targets':sorted((set(original[:10])&targets)-set(order[:10]))}
        scores.append({'instance_id':item['instance_id'],'repo':trace['repo'],'gold_count':len(targets),'scorable':bool(targets),
                       'gold_status':'missing_record' if record is None else ('symbols' if targets else 'no_symbols'),
                       'original':metrics(original),'paired_fallback':any(r['status']!='ok' for r in responses[2*i:2*i+2]),
                       'raw_statuses':{r['arm']:r['status'] for r in responses[2*i:2*i+2]},
                       'arms':{result['arm']:metrics(result['order']) for result in pair}})
    valid=[r for r in scores if r['scorable']]
    if not valid:raise ValueError('No scorable tasks')
    complete=[r for r in valid if not r['paired_fallback']]
    primary=summarize_rows(valid)
    interval=primary['descriptive_repo_bootstrap_95']
    threshold=m['evaluation']['minimum_worthwhile_delta']
    decision='uncertain'
    if interval and interval[0]>=threshold:decision='effect_warrants_next_stage_exploration'
    elif interval and interval[1]<threshold:decision='no_worthwhile_gain_under_current_protocol'
    key=load_key(args.env_file)
    if any(key in f.read_text(encoding='utf-8') for f in args.run_dir.rglob('*') if f.is_file()):raise ValueError('Credential found in artifacts; refusing summary')
    summary={'manifest_sha256':m['manifest_sha256'],'input_seal_sha256':file_hash(args.run_dir/'inputs.seal.json'),
             'responses_sha256':file_hash(args.run_dir/'responses.jsonl'),'gold_sha256':file_hash(args.gold),
             'retrieval_hashes':{p.name:file_hash(p) for p in sorted((args.run_dir/'retrieval_tasks').glob('*.json'))},
             'selected_tasks':len(scores),'scorable_tasks':len(valid),'missing_gold_records':sum(r['gold_status']=='missing_record' for r in scores),
             'paired_fallback_tasks':[r['instance_id'] for r in scores if r['paired_fallback']],
             'primary':primary,'complete_pair_sensitivity':summarize_rows(complete),'decision':decision,
             'original_means':{metric:statistics.mean(r['original'][metric] for r in valid) for metric in ('coverage','recall_at_10')},
             'by_repo':{repo:summarize_rows([r for r in valid if r['repo']==repo]) for repo in sorted({r['repo'] for r in valid})},
             'provider_models':sorted({r['provider_model'] for r in responses if r['provider_model']}),
             'fingerprints':sorted({r['system_fingerprint'] for r in responses if r['system_fingerprint']}),
             'usage':{arm:{'known_input_tokens':sum(r['input_tokens'] or 0 for r in responses if r['arm']==arm),
                           'known_output_tokens':sum(r['output_tokens'] or 0 for r in responses if r['arm']==arm),
                           'unknown_usage_calls':sum(r['status']=='transport_unknown' for r in responses if r['arm']==arm),
                           'model_calls':sum(r['arm']==arm for r in responses),
                           'retrieval_calls':sum(r['retrieval_calls'] for pair in retrievals for r in pair if r['arm']==arm),
                           'code_chars_exposed':sum(r['code_chars_exposed'] for r in requests if r['arm']==arm)} for arm in ARMS},
             'known_cny_idle':sum(r['estimated_cny_idle'] or 0 for r in responses),
             'peak_plus_unknown_reservation_cny':sum(charged_or_reserved(r) for r in responses),
             'prior_plus_current_peak_reservation_cny':m['prior_run_reserved_cny']+sum(charged_or_reserved(r) for r in responses),
             'credential_scan':'passed','automatic_expansion':False,'limits':m['limits']}
    with (args.run_dir/'scores.jsonl').open('x',encoding='utf-8') as stream:
        for row in scores:stream.write(canonical(row)+'\n')
    write_json(args.run_dir/'summary.json',summary)
    # Avoid flooding logs with every repository or exposing model text.
    print(json.dumps({k:summary[k] for k in ('selected_tasks','scorable_tasks','paired_fallback_tasks','primary','complete_pair_sensitivity','decision','known_cny_idle','prior_plus_current_peak_reservation_cny')},indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    for command in ('prepare','inputs','generate','retrieve','evaluate'):
        ap=sub.add_parser(command)
        ap.add_argument('--run-dir',type=Path,required=True)
        if command=='prepare':
            ap.add_argument('--tasks',type=Path,default=ROOT/'data/swebench_lite.jsonl')
            ap.add_argument('--pilot',type=Path,default=ROOT/'experiments/runs/deepseek-flash-feedback-20261102-v1')
        if command in ('inputs','retrieve'):ap.add_argument('--repos',type=Path,default=ROOT/'data/repos')
        if command in ('generate','evaluate'):ap.add_argument('--env-file',type=Path,default=ROOT/'.env')
        if command=='evaluate':ap.add_argument('--gold',type=Path,default=ROOT/'data/gold_symbols.jsonl')
    args=p.parse_args()
    {'prepare':prepare,'inputs':inputs,'generate':generate,'retrieve':retrieve,'evaluate':evaluate}[args.command](args)


if __name__=='__main__':main()
