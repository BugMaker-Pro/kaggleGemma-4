"""Disjoint issue-only query generation vs fixed cheap fusion; no test-label tuning."""
from __future__ import annotations
import argparse
import json
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from experiments.query_pilot import TaskInput,canonical,digest,file_hash,stable_search
from experiments.feedback_pilot import CONFIG,paired_requests,rank_queries
from experiments.buildgraph import read_snapshot,build_graph
from experiments.snapindex import SnapshotIndex
from experiments.strong_query_features import candidate_features
from experiments.query_validation_anchor import rebuild_anchor
from tools.run_feedback_pilot import write_json,build_index
from tools.analyse_candidate_retention import read_rows
from tools.run_flash_replication import select_tasks,unknown_response,charged_or_reserved,validate_generated
from tools.run_deepseek_feedback import API_CONFIG,ENDPOINT,PRICES,load_key,NoRedirect,utc_now,reserve_cost,decode_response
from tools.run_strong_query_v2 import encoder_documents,inference_anchor,training_data,MODEL_FILES
from tools.run_simple_fusion import simple_pool,score_task,interval

SEED=2026110303
ARMS=('historical','body_original','simple_fusion','generated')


def prepare(args):
    pilot=ROOT/'experiments/runs/deepseek-flash-feedback-20261102-v1'
    replication=ROOT/'experiments/runs/flash-replication-20261102-v1'
    excluded=set()
    exclusion_hashes={}
    for directory in (pilot,replication):
        path=directory/'manifest.json';m=json.loads(path.read_text(encoding='utf-8'))
        excluded.update(m['task_ids']);exclusion_hashes[str(path.relative_to(ROOT))]=file_hash(path)
    selected=select_tasks(read_rows(ROOT/'data/swebench_lite.jsonl'),excluded,per_repo=5,seed=SEED)
    historical=training_data(argparse.Namespace(features=ROOT/'data/features_full.jsonl',embed=ROOT/'data/embed_retrieval.jsonl'))
    byid={r['instance_id']:r for r in historical}
    missing_anchors=[t['instance_id'] for t in selected if t['instance_id'] not in byid]
    sm=json.loads((args.strong/'manifest.json').read_text(encoding='utf-8'))
    audit=json.loads((args.strong/'training_audit.json').read_text(encoding='utf-8'))
    if audit['mismatching_tasks'] or audit['tasks']!=2232:raise ValueError('Strong baseline not reproduced')
    for name,h in audit['model_hashes'].items():
        if file_hash(args.strong/'models'/name)!=h:raise ValueError('Model hash mismatch')
    for path,h in sm['source_hashes'].items():
        if file_hash(ROOT/path)!=h:raise ValueError('Prior scoring source changed')
    previous=json.loads((replication/'summary.json').read_text(encoding='utf-8'))['prior_plus_current_peak_reservation_cny']
    requests=[paired_requests(TaskInput.from_mapping(t),[])[0] for t in selected]
    reserve=sum(reserve_cost(r) for r in requests)
    if previous+reserve>5:raise ValueError('Cumulative planning reserve exceeds 5 CNY')
    args.run_dir.mkdir(parents=True,exist_ok=False)
    anchors=[]
    for task in selected:
        if task['instance_id'] in byid:
            r=byid[task['instance_id']];anchors.append({'instance_id':r['instance_id'],'repo':r['repo'],'anchor':inference_anchor(r),'cosine':r['cosine'],'origin':'historical'})
        else:
            snapshot=SnapshotIndex(args.repos).path_for(task)
            if snapshot is None:raise ValueError('Missing snapshot for anchor rebuild')
            files=read_snapshot(snapshot);graph,_=build_graph(files)
            anchors.append({'instance_id':task['instance_id'],'repo':task['repo'],'anchor':rebuild_anchor(task['problem_statement'],files,graph),'cosine':[],
                            'origin':'rebuilt_without_gold','snapshot_sha256':digest(sorted(files.items()))})
            print('rebuilt anchor '+task['instance_id'],flush=True)
    for name,rows in (('tasks.jsonl',selected),('anchors.jsonl',anchors),('requests.jsonl',requests)):
        with (args.run_dir/name).open('x',encoding='utf-8') as stream:
            for row in rows:stream.write(canonical(row)+'\n')
    sources=['tools/run_query_validation.py','tools/run_flash_replication.py','tools/run_simple_fusion.py','tools/run_deepseek_feedback.py','tools/run_feedback_pilot.py','tools/run_strong_query_v2.py','tools/features.py','tools/embed_retrieve.py']
    sources+=sorted(p.relative_to(ROOT).as_posix() for p in (ROOT/'experiments').glob('*.py'))
    m={'schema':1,'date':'2026-11-03','stage':'disjoint_issue_query_vs_fixed_fusion','created_utc':utc_now(),
       'task_ids':[t['instance_id'] for t in selected],'rebuilt_anchor_tasks':missing_anchors,'excluded_task_ids':sorted(excluded),'exclusion_hashes':exclusion_hashes,
       'sampling':{'per_repo':5,'seed':SEED,'rule':'hash selection from remaining Lite tasks, no labels/outcomes'},
       'repo_counts':{repo:sum(t['repo']==repo for t in selected) for repo in sorted({t['repo'] for t in selected})},
       'config':CONFIG,'api':API_CONFIG,'endpoint':ENDPOINT,'prices':PRICES,'rrf_k':60,'candidate_cap':200,
       'budget_cny':5-previous,'prior_reserved_cny':previous,'combined_budget_cny':5,'planning_reservation_cny':reserve,
       'max_calls':len(requests),'failure_policy':{'consecutive_transport_stop':3,'attempts':1,'timeout_seconds':60,
          'fallback':'generated uses simple_fusion when generation is not ok; report all tasks and successful-only sensitivity'},
       'source_hashes':{p:file_hash(ROOT/p) for p in sources},
       'input_hashes':{n:file_hash(args.run_dir/n) for n in ('tasks.jsonl','anchors.jsonl','requests.jsonl')},
       'historical_input_hashes':{n:file_hash(ROOT/n) for n in ('data/features_full.jsonl','data/embed_retrieval.jsonl')},
       'strong_manifest_sha256':file_hash(args.strong/'manifest.json'),'training_audit_sha256':file_hash(args.strong/'training_audit.json'),
       'model_hashes':audit['model_hashes'],'encoder_hashes':sm['encoder_hashes'],'folds':sm['folds'],
       'evaluation':{'primary':'generated minus simple_fusion macro recall@10','threshold':.02,'cluster':'repository','bootstrap_seed':20261103,'replicates':5000,
          'secondary':['coverage','novel targets outside both original pools','all successes sensitivity','all other arms'],
          'automatic_expansion':False},
       'limits':['37 task target from remaining Lite; sampling rule can yield smaller groups; 47 prior tasks excluded',
                 'historical-development benchmark, not unseen confirmation; public benchmark training contamination unknown',
                 'same frozen ranker and feature extension; no retraining on new labels',
                 'equal 200 final candidates not equal cost: simple2 searches/no generation vs generated3 searches/one generation',
                 'mutable API alias; usage checked after response; UTF8 reservation not exact token bound',
                 'on transport failure completion/billing unknown; never resend uncertain request']}
    m['manifest_sha256']=digest(m);write_json(args.run_dir/'manifest.json',m)
    seal={'manifest_sha256':m['manifest_sha256'],'requests_sha256':file_hash(args.run_dir/'requests.jsonl'),
          'schedule':[r['request_sha256'] for r in requests]};seal['sha256']=digest(seal);write_json(args.run_dir/'inputs.seal.json',seal)
    print(canonical({'selected':len(selected),'repo_counts':m['repo_counts'],'api_calls':len(requests),'planned_cny':reserve,'cumulative_reserved_cny':previous+reserve}))


def load_run(args):
    m=json.loads((args.run_dir/'manifest.json').read_text(encoding='utf-8'));h=m.pop('manifest_sha256')
    if digest(m)!=h:raise ValueError('Manifest changed')
    m['manifest_sha256']=h
    for path,h in m['source_hashes'].items():
        if file_hash(ROOT/path)!=h:raise ValueError(f'Frozen source changed: {path}')
    for group,base in (('input_hashes',args.run_dir),('historical_input_hashes',ROOT),('exclusion_hashes',ROOT)):
        for path,h in m[group].items():
            if file_hash(base/path)!=h:raise ValueError('Input changed')
    if file_hash(args.strong/'manifest.json')!=m['strong_manifest_sha256'] or file_hash(args.strong/'training_audit.json')!=m['training_audit_sha256']:raise ValueError('Strong model provenance changed')
    for name,h in m['model_hashes'].items():
        if file_hash(args.strong/'models'/name)!=h:raise ValueError('Trained model changed')
    for name,h in m['encoder_hashes'].items():
        if file_hash(args.model_dir/name)!=h:raise ValueError('Encoder changed')
    tasks=[TaskInput.from_mapping(r) for r in read_rows(args.run_dir/'tasks.jsonl')]
    anchors=read_rows(args.run_dir/'anchors.jsonl');requests=read_rows(args.run_dir/'requests.jsonl')
    if [t.instance_id for t in tasks]!=m['task_ids'] or set(m['task_ids'])&set(m['excluded_task_ids']):raise ValueError('Sample overlap/identity error')
    if len(anchors)!=len(tasks) or requests!=[paired_requests(t,[])[0] for t in tasks]:raise ValueError('Unsafe or changed request input')
    for a,t in zip(anchors,tasks):
        if a['instance_id']!=t.instance_id or a['repo']!=t.repo or set(a['anchor'])!={'ids','rows','files'}:raise ValueError('Anchor projection mismatch')
    seal=json.loads((args.run_dir/'inputs.seal.json').read_text(encoding='utf-8'));h=seal.pop('sha256')
    if digest(seal)!=h or seal['manifest_sha256']!=m['manifest_sha256'] or seal['requests_sha256']!=file_hash(args.run_dir/'requests.jsonl') or seal['schedule']!=[r['request_sha256'] for r in requests]:raise ValueError('Request seal changed')
    return m,tasks,anchors,requests,seal


def load_inputs(directory):
    # Adapter for the same tested single-attempt API transport implementation.
    args=argparse.Namespace(run_dir=directory,strong=ROOT/'experiments/runs/strong-query-20261103-v2',model_dir=ROOT/'models/bge-small-en-v1.5')
    m,tasks,anchors,requests,seal=load_run(args)
    return m,[],requests,seal


def generated_pool(original,actions,response,simple):
    if response['status']!='ok':return list(simple)
    if len(actions)!=2:raise ValueError('Two generated actions required')
    return rank_queries(original,[a['candidates'] for a in actions])


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



def score(args):
    import torch
    import lightgbm as lgb
    import numpy as np
    from transformers import AutoModel,AutoTokenizer
    m,tasks,anchors,requests,_=load_run(args)
    responses=validate_generated(args.run_dir,m,requests)
    if not torch.cuda.is_available():raise ValueError('Frozen fp16 CUDA encoder requires CUDA')
    tokenizer=AutoTokenizer.from_pretrained(str(args.model_dir),local_files_only=True,trust_remote_code=False)
    encoder=AutoModel.from_pretrained(str(args.model_dir),local_files_only=True,trust_remote_code=False,dtype=torch.float16).to('cuda').eval()
    models={i:[lgb.Booster(model_file=str(args.strong/'models'/f'fold{i}_seed{seed}.txt')) for seed in (0,1,2)] for i in (0,1)}
    def encode(texts,query=False):
        if query:texts=['Represent this query for retrieving code: '+t for t in texts]
        batch=tokenizer(texts,padding=True,truncation=True,max_length=512,return_tensors='pt').to('cuda')
        with torch.inference_mode():v=encoder(**batch).last_hidden_state[:,0]
        return torch.nn.functional.normalize(v.float(),dim=-1)
    directory=args.run_dir/'scored_candidates';directory.mkdir(exist_ok=True)
    for i,(task,anchor,response) in enumerate(zip(tasks,anchors,responses)):
        path=directory/f'{i:03d}.json'
        if path.exists():
            r=json.loads(path.read_text(encoding='utf-8'))
            if r['manifest_sha256']!=m['manifest_sha256'] or r['response_sha256']!=digest(response):raise ValueError('Checkpoint mismatch')
            print(f'cached {i+1}/{len(tasks)}',flush=True);continue
        start=time.perf_counter();snapshot=SnapshotIndex(args.repos).path_for({'instance_id':task.instance_id,'repo':task.repo,'base_commit':task.base_commit})
        if snapshot is None:raise ValueError('Missing snapshot; no task dropped')
        files=read_snapshot(snapshot)
        if anchor['origin']=='rebuilt_without_gold' and digest(sorted(files.items()))!=anchor['snapshot_sha256']:raise ValueError('Rebuilt anchor snapshot changed')
        index=build_index(files)
        original,original_scored=stable_search(index,task.problem_statement[:20000],200)
        body=[r['id'] for r in original];simple=simple_pool(anchor['anchor']['ids'],body)
        actions=[]
        for query in response['queries']:
            candidates,scored=stable_search(index,query,200)
            actions.append({'query':query,'candidates':candidates,'scored_documents':scored})
        if original_scored+sum(a['scored_documents'] for a in actions)>CONFIG['max_scored_documents']:raise ValueError('Retrieval scoring cap exceeded')
        generated=generated_pool(original,actions,response,simple)
        pools={'historical':anchor['anchor']['ids'],'body_original':body,'simple_fusion':simple,'generated':generated}
        if any(len(p)>200 or len(p)!=len(set(p)) for p in pools.values()):raise ValueError('Candidate cap/dedup failure')
        wanted=list(dict.fromkeys(n for p in pools.values() for n in p))
        graph,_=build_graph(files)
        features,feature_audit=candidate_features(task.problem_statement,files,graph,anchor['anchor'],wanted)
        dense=dict(zip(anchor['anchor']['ids'],anchor['cosine']));new=[n for n in wanted if n not in dense]
        docs=encoder_documents(new,graph.nodes,files);q=encode([task.problem_statement[:1200]],True)
        for offset in range(0,len(docs),32):
            values=(encode(docs[offset:offset+32])@q.T).view(-1).cpu().tolist()
            dense.update({n:round(v,4) for n,v in zip(new[offset:offset+32],values)})
        rows=[r+[dense[n]] for n,r in zip(wanted,features)]
        fold=next(j for j,f in enumerate(m['folds']) if task.repo in f['test_repos'])
        if task.repo in m['folds'][fold]['train_repos'] or task.instance_id in m['folds'][fold]['training_task_ids']:raise ValueError('Training leakage')
        values=np.mean([model.predict(np.array(rows),num_threads=2) for model in models[fold]],axis=0).tolist()
        lookup=dict(zip(wanted,values));orders={a:sorted(p,key=lambda n:-lookup[n]) for a,p in pools.items()}
        raw={'instance_id':task.instance_id,'repo':task.repo,'base_commit':task.base_commit,'manifest_sha256':m['manifest_sha256'],
             'request_sha256':requests[i]['request_sha256'],'response_sha256':digest(response),'status':response['status'],'fallback':response['status']!='ok',
             'snapshot_content_sha256':digest(sorted(files.items())),'original':original,'generated_actions':actions,'pools':pools,'orders':orders,
             'ids':wanted,'rows':rows,'strong_scores':lookup,'fold':fold,'feature_audit':feature_audit,
             'new_dense_candidates':len(new),'source_chars':sum(map(len,files.values())),'dense_document_chars':sum(map(len,docs)),
             'retrieval_scored_documents':original_scored+sum(a['scored_documents'] for a in actions),'seconds':time.perf_counter()-start}
        write_json(path,raw);print(f'scored {i+1}/{len(tasks)} {task.instance_id} new_dense={len(new)}',flush=True)


def evaluate(args):
    from tools.evaluate_query_pilot import gold_targets
    m,tasks,anchors,requests,_=load_run(args);responses=validate_generated(args.run_dir,m,requests)
    candidate_rows=[]
    for i,(task,anchor,response) in enumerate(zip(tasks,anchors,responses)):
        row=json.loads((args.run_dir/'scored_candidates'/f'{i:03d}.json').read_text(encoding='utf-8'))
        if row['instance_id']!=task.instance_id or row['manifest_sha256']!=m['manifest_sha256'] or row['response_sha256']!=digest(response):raise ValueError('Scored candidate provenance mismatch')
        if row['pools']['historical']!=anchor['anchor']['ids'] or row['pools']['body_original']!=[r['id'] for r in row['original']]:raise ValueError('Source pool changed')
        simple=simple_pool(row['pools']['historical'],row['pools']['body_original'])
        if row['pools']['simple_fusion']!=simple or row['pools']['generated']!=generated_pool(row['original'],row['generated_actions'],response,simple):raise ValueError('Fusion rule changed')
        if [a['query'] for a in row['generated_actions']]!=response['queries']:raise ValueError('Executed query changed')
        for arm,pool in row['pools'].items():
            if len(pool)>200 or len(set(pool))!=len(pool) or row['orders'][arm]!=sorted(pool,key=lambda n:-row['strong_scores'][n]):raise ValueError('Rank or cap violation')
        fold=m['folds'][row['fold']]
        if task.repo in fold['train_repos'] or task.repo not in fold['test_repos']:raise ValueError('Fold leakage')
        x=dict(zip(row['ids'],row['rows']))
        for n,f in zip(anchor['anchor']['ids'],anchor['anchor']['rows']):
            if x[n][:16]!=f:raise ValueError('Anchor feature drift')
        for n,c in zip(anchor['anchor']['ids'],anchor['cosine']):
            if x[n][16]!=c:raise ValueError('Historical cosine drift')
        candidate_rows.append(row)
    # All retrieval decisions have been checked before loading gold.
    records=read_rows(args.gold);gold={r['instance_id']:r for r in records}
    if len(gold)!=len(records):raise ValueError('Duplicate gold')
    scores=[]
    for task,row in zip(tasks,candidate_rows):
        record=gold.get(task.instance_id)
        if record and any(record.get(k)!=getattr(task,k) for k in ('repo','base_commit')):raise ValueError('Gold identity mismatch')
        union=sorted(set(row['pools']['historical'])|set(row['pools']['body_original']))
        scored=score_task({**row,'metadata_body_union':union},gold_targets(record) if record else set())
        scored.update(status=row['status'],fallback=row['fallback'],gold_status='missing_record' if record is None else ('symbols' if scored['scorable'] else 'no_symbols'))
        scores.append(scored)
    valid=[r for r in scores if r['scorable']]
    def summarize(rows):
        if not rows:return {'tasks':0}
        means={a:{k:statistics.mean(r['arms'][a][k] for r in rows) for k in ('coverage','recall_at_10')} for a in ARMS}
        return {'tasks':len(rows),'means':means,'primary_delta':means['generated']['recall_at_10']-means['simple_fusion']['recall_at_10'],
                'descriptive_repo_bootstrap_95':interval(rows),
                'improved_tasks':[r['instance_id'] for r in rows if r['arms']['generated']['recall_at_10']>r['arms']['simple_fusion']['recall_at_10']],
                'harmed_tasks':[r['instance_id'] for r in rows if r['arms']['generated']['recall_at_10']<r['arms']['simple_fusion']['recall_at_10']]}
    if not valid:raise ValueError('No scorable tasks')
    primary=summarize(valid);ci=primary['descriptive_repo_bootstrap_95'];decision='uncertain'
    if ci and ci[0]>=.02:decision='worth_further_exploration'
    elif ci and ci[1]<.02:decision='no_worthwhile_gain_under_fixed_control'
    key=load_key(args.env_file)
    if any(key in p.read_text(encoding='utf-8') for p in args.run_dir.rglob('*') if p.is_file()):raise ValueError('Credential in artifacts')
    summary={'manifest_sha256':m['manifest_sha256'],'responses_sha256':file_hash(args.run_dir/'responses.jsonl'),'gold_sha256':file_hash(args.gold),
             'candidate_hashes':{p.name:file_hash(p) for p in sorted((args.run_dir/'scored_candidates').glob('*.json'))},
             'selected_tasks':len(tasks),'scorable_tasks':len(valid),'unscorable_tasks':[{'instance_id':r['instance_id'],'gold_status':r['gold_status']} for r in scores if not r['scorable']],'missing_gold_tasks':[r['instance_id'] for r in scores if r['gold_status']=='missing_record'],
             'primary':primary,'success_only':summarize([r for r in valid if not r['fallback']]),'decision':decision,
             'fallback_tasks':[r['instance_id'] for r in scores if r['fallback']],
             'novel_top_target_tasks':[r['instance_id'] for r in valid if r['generated_top_targets_outside_original_union']],
             'known_input_tokens':sum(r['input_tokens'] or 0 for r in responses),'known_output_tokens':sum(r['output_tokens'] or 0 for r in responses),
             'known_idle_cny':sum(r['estimated_cny_idle'] or 0 for r in responses),
             'peak_plus_unknown_reservation_cny':sum(charged_or_reserved(r) for r in responses),
             'cumulative_reserved_cny':m['prior_reserved_cny']+sum(charged_or_reserved(r) for r in responses),
             'provider_models':sorted({r['provider_model'] for r in responses if r['provider_model']}),
             'fingerprints':sorted({r['system_fingerprint'] for r in responses if r['system_fingerprint']}),
             'new_dense_candidates':sum(r['new_dense_candidates'] for r in candidate_rows),
             'new_training_runs':0,'limits':m['limits'],'automatic_expansion':False,'credential_scan':'passed'}
    with (args.run_dir/'scores.jsonl').open('x',encoding='utf-8') as stream:
        for r in scores:stream.write(canonical(r)+'\n')
    write_json(args.run_dir/'summary.json',summary)
    print(json.dumps({k:summary[k] for k in ('selected_tasks','scorable_tasks','primary','success_only','fallback_tasks','novel_top_target_tasks','decision','known_idle_cny','cumulative_reserved_cny')},indent=2))


def main():
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    for command in ('prepare','generate','score','evaluate'):
        p=sub.add_parser(command);p.add_argument('--run-dir',type=Path,required=True)
        p.add_argument('--strong',type=Path,default=ROOT/'experiments/runs/strong-query-20261103-v2')
        p.add_argument('--model-dir',type=Path,default=ROOT/'models/bge-small-en-v1.5')
        p.add_argument('--repos',type=Path,default=ROOT/'data/repos')
        p.add_argument('--env-file',type=Path,default=ROOT/'.env')
        p.add_argument('--gold',type=Path,default=ROOT/'data/gold_symbols.jsonl')
    args=ap.parse_args();{'prepare':prepare,'generate':generate,'score':score,'evaluate':evaluate}[args.command](args)


if __name__=='__main__':main()
