"""Frozen strong-ranker diagnostic using saved issue-only queries; no API calls.

prepare -> train -> candidates -> predict -> evaluate
"""
from __future__ import annotations
import argparse
import json
import math
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from experiments.query_pilot import canonical,digest,file_hash,TaskInput
from experiments.buildgraph import build_graph,read_snapshot
from experiments.snapindex import SnapshotIndex
from experiments.symbols import python_symbols
from experiments.strong_query_features import candidate_features
from tools.features import FEATURES
from tools.run_feedback_pilot import write_json
from tools.analyse_candidate_retention import read_rows
from tools.run_flash_replication import load_inputs,validate_generated,effective_pair
from tools.embed_retrieve import qualname_of,source_of

SEEDS=(0,1,2)
ARM_NAMES=('historical','body_original','generated')
MODEL_FILES=('config.json','model.safetensors','tokenizer.json','tokenizer_config.json','vocab.txt','special_tokens_map.json')
SOURCES=('tools/run_strong_query.py','experiments/strong_query_features.py','tools/features.py',
         'tools/rank_with_dense.py','tools/train_rank2.py','tools/embed_retrieve.py',
         'tools/run_flash_replication.py','tools/run_feedback_pilot.py','experiments/query_pilot.py',
         'experiments/buildgraph.py','experiments/retrieve.py','experiments/symbols.py')


def folds_for(repos):
    repos=sorted(set(repos));half=set(repos[::2])
    return [(half,set(repos)-half),(set(repos)-half,half)]


def inference_anchor(row):
    return {key:row[key] for key in ('ids','rows','files')}


def training_data(args):
    rows=read_rows(args.features)
    embeds={r['instance_id']:r for r in read_rows(args.embed)}
    if len({r['instance_id'] for r in rows})!=len(rows):raise ValueError('Duplicate feature task')
    for row in rows:
        if tuple(row['features'])!=FEATURES or len(row['ids'])!=len(row['rows']) or len(row['labels'])!=len(row['rows']):raise ValueError('Training schema mismatch')
        dense=embeds.get(row['instance_id'])
        if dense is None or sorted(dense['candidates'])!=list(range(len(row['rows']))):raise ValueError('Missing dense scores; no task dropped')
        cosine=[None]*len(row['rows'])
        for i,score in zip(dense['candidates'],dense['scores']):cosine[i]=score
        if any(v is None for v in cosine):raise ValueError('Incomplete cosine scores')
        row['cosine']=cosine
    return rows


def prepare(args):
    parent,inputs,requests,seal=load_inputs(args.parent)
    responses=validate_generated(args.parent,parent,requests)
    rows=training_data(args)
    by_id={r['instance_id']:r for r in rows}
    if set(parent['task_ids'])-by_id.keys():raise ValueError('Some evaluation tasks lack historical candidates')
    folds=folds_for(r['repo'] for r in rows)
    projection=[]
    for row in rows:
        # Labels in the historical training corpus stay in training_data only.
        if row['instance_id'] in parent['task_ids']:
            projection.append({'instance_id':row['instance_id'],'repo':row['repo'],
                               'anchor':inference_anchor(row),'cosine':row['cosine']})
    m={'schema':1,'date':'2026-11-03','stage':'strong_ranker_saved_query_diagnostic',
       'parent_manifest_sha256':parent['manifest_sha256'],'parent_summary_sha256':file_hash(args.parent/'summary.json'),
       'parent_responses_sha256':file_hash(args.parent/'responses.jsonl'),'task_ids':parent['task_ids'],
       'source_hashes':{p:file_hash(ROOT/p) for p in SOURCES},
       'training_features_sha256':file_hash(args.features),'training_dense_sha256':file_hash(args.embed),
       'historical_metrics_sha256':file_hash(args.historical_metrics),
       'encoder_hashes':{p:file_hash(args.model_dir/p) for p in MODEL_FILES},
       'folds':[{'train_repos':sorted(a),'test_repos':sorted(b),'training_task_ids':[r['instance_id'] for r in rows if r['repo'] in a]} for a,b in folds],
       'ranker':{'objective':'lambdarank','metric':'ndcg','ndcg_eval_at':[10],'learning_rate':.05,'num_leaves':15,
                 'min_data_in_leaf':20,'verbose':-1,'deterministic':True,'num_threads':2,'rounds':300,'seeds':list(SEEDS)},
       'encoder':{'issue_chars':1200,'prefix':'Represent this query for retrieving code: ',
                  'body_chars':800,'tokens':512,'precision':'float16','pooling':'normalized CLS','saved_decimals':4,'batch':32},
       'arms':{'historical':'saved metadata top200, sixteen historical features plus saved dense',
               'body_original':'saved body-BM25 top200, same frozen ranker',
               'generated':'saved issue-only generated-query RRF top200, same frozen ranker'},
       'feature_extension':{'query':'original issue for ALL features and cosine',
                            'seeds':'historical metadata first five',
                            'file_stats':'anchored to historical metadata pool; new file best/size zero if absent',
                            'new_metadata_rank':'full-repo original-issue metadata rank, ID ties; no-match rank N+1',
                            'existing':'keep saved BM25 score/rank and dense; independently reproduce other 14 columns',
                            'new':'same formula; no generated-query/RRF score added as feature'},
       'evaluation':{'primary':'generated minus body_original macro symbol recall@10',
                     'secondary':['generated minus historical','coverage','gained/lost symbols','historical full-scale reproduction'],
                     'threshold':.02,'bootstrap_unit':'repository','bootstrap_seed':20261103,'replicates':5000,
                     'failure':'integrity/protocol mismatch stops; no silent omission','automatic_expansion':False},
       'limits':['35 already observed historical-development tasks; diagnostic not unseen confirmation',
                 'new candidates extend feature distribution outside historical top200; no refitting or tuning on 35 task labels',
                 'candidate pools fixed at200 but candidate scoring/encoding cost can differ; recorded',
                 'query-generation API costs from parent already incurred; new API calls zero',
                 'historic dense values reused, new dense values freshly computed from local frozen encoder',
                 'body BM25 versus metadata pool differences isolated by body_original control']}
    args.run_dir.mkdir(parents=True,exist_ok=False)
    with (args.run_dir/'anchors.jsonl').open('x',encoding='utf-8') as stream:
        for row in projection:stream.write(canonical(row)+'\n')
    m['anchors_sha256']=file_hash(args.run_dir/'anchors.jsonl')
    m['manifest_sha256']=digest(m)
    write_json(args.run_dir/'manifest.json',m)
    print(canonical({'tasks':len(projection),'training_tasks':len(rows),'fold_training_counts':[len(f['training_task_ids']) for f in m['folds']], 'new_api_calls':0}))


def load_run(args):
    m=json.loads((args.run_dir/'manifest.json').read_text(encoding='utf-8'))
    expected=m.pop('manifest_sha256')
    if digest(m)!=expected:raise ValueError('Strong scorer manifest changed')
    m['manifest_sha256']=expected
    for p,fingerprint in m['source_hashes'].items():
        if file_hash(ROOT/p)!=fingerprint:raise ValueError(f'Frozen source changed: {p}')
    for path,name in ((args.features,'training_features_sha256'),(args.embed,'training_dense_sha256'),(args.historical_metrics,'historical_metrics_sha256'),(args.run_dir/'anchors.jsonl','anchors_sha256')):
        if file_hash(path)!=m[name]:raise ValueError(f'Frozen input changed: {name}')
    for name,fingerprint in m['encoder_hashes'].items():
        if file_hash(args.model_dir/name)!=fingerprint:raise ValueError('Encoder changed')
    parent,inputs,requests,seal=load_inputs(args.parent)
    if parent['manifest_sha256']!=m['parent_manifest_sha256'] or file_hash(args.parent/'responses.jsonl')!=m['parent_responses_sha256'] or file_hash(args.parent/'summary.json')!=m['parent_summary_sha256']:raise ValueError('Parent run changed')
    responses=validate_generated(args.parent,parent,requests)
    anchors={r['instance_id']:r for r in read_rows(args.run_dir/'anchors.jsonl')}
    if set(anchors)!=set(m['task_ids']):raise ValueError('Anchor task mismatch')
    return m,inputs,responses,anchors


def train(args):
    import lightgbm as lgb
    import numpy as np
    m,inputs,responses,anchors=load_run(args)
    rows=training_data(args)
    historical={r['instance_id']:r for r in read_rows(args.historical_metrics)}
    directory=args.run_dir/'models';directory.mkdir(exist_ok=True)
    predictions={}
    for fold_index,fold in enumerate(m['folds']):
        train_rows=[r for r in rows if r['repo'] in fold['train_repos']]
        test_rows=[r for r in rows if r['repo'] in fold['test_repos']]
        if [r['instance_id'] for r in train_rows]!=fold['training_task_ids']:raise ValueError('Training fold changed')
        if set(fold['train_repos'])&set(fold['test_repos']):raise ValueError('Repository leakage')
        x=np.array([list(values)+[r['cosine'][i]] for r in train_rows for i,values in enumerate(r['rows'])])
        y=np.array([v for r in train_rows for v in r['labels']]);group=[len(r['rows']) for r in train_rows]
        models=[]
        for seed in SEEDS:
            path=directory/f'fold{fold_index}_seed{seed}.txt'
            if path.exists():model=lgb.Booster(model_file=str(path))
            else:
                params={k:v for k,v in m['ranker'].items() if k not in ('rounds','seeds')};params['seed']=seed
                model=lgb.train(params,lgb.Dataset(x,label=y,group=group),num_boost_round=m['ranker']['rounds'])
                model.save_model(str(path))
            models.append(model)
            print(f'trained fold {fold_index} seed {seed}',flush=True)
        for row in test_rows:
            z=np.array([list(values)+[row['cosine'][i]] for i,values in enumerate(row['rows'])])
            scores=np.mean([model.predict(z,num_threads=2) for model in models],axis=0).tolist()
            order=sorted(range(len(scores)),key=lambda i:-scores[i])
            total=row['gold_total']
            recall=sum(row['labels'][i] for i in order[:10])/total if total else 0
            predictions[row['instance_id']]={'instance_id':row['instance_id'],'scores':scores,'recall_at_10':recall,
                                             'historical_recall':historical[row['instance_id']]['dense_symbol'],
                                             'fold':fold_index}
    if set(predictions)!=set(historical):raise ValueError('Training reproduction task IDs differ')
    mismatch=[r['instance_id'] for r in predictions.values() if abs(r['recall_at_10']-r['historical_recall'])>1e-9]
    report={'tasks':len(predictions),'reproduced_mean':statistics.mean(r['recall_at_10'] for r in predictions.values()),
            'historical_mean':statistics.mean(r['historical_recall'] for r in predictions.values()),
            'mismatching_tasks':mismatch,'model_hashes':{p.name:file_hash(p) for p in sorted(directory.glob('*.txt'))}}
    # Record even a failed reproduction, then STOP; do not tune against the test tasks.
    write_json(args.run_dir/'training_audit.json',report)
    if mismatch:raise ValueError(f'Historical dense ranker failed to reproduce on {len(mismatch)} tasks; stop')
    with (args.run_dir/'historical_predictions.jsonl').open('x',encoding='utf-8') as stream:
        for tid in sorted(predictions):stream.write(canonical(predictions[tid])+'\n')
    print(canonical({k:v for k,v in report.items() if k!='model_hashes'}))


def encoder_documents(ids,nodes,files):
    tables={};documents=[]
    for node_id in ids:
        path=nodes[node_id]['file']
        if path not in tables:tables[path]=python_symbols(files[path])
        body=source_of(tables[path],files[path],qualname_of(node_id,path))
        documents.append(f'{path} :: {node_id}\n{body[:800]}')
    return documents


def candidates(args):
    import torch
    from transformers import AutoModel,AutoTokenizer
    m,inputs,responses,anchors=load_run(args)
    audit=json.loads((args.run_dir/'training_audit.json').read_text(encoding='utf-8'))
    if audit['mismatching_tasks']:raise ValueError('Cannot proceed after failed historical reproduction')
    device='cuda' if torch.cuda.is_available() else 'cpu'
    if device!='cuda':raise ValueError('Historical encoder used fp16 CUDA; CPU substitution requires a new protocol')
    tokenizer=AutoTokenizer.from_pretrained(str(args.model_dir),local_files_only=True,trust_remote_code=False)
    model=AutoModel.from_pretrained(str(args.model_dir),local_files_only=True,trust_remote_code=False,dtype=torch.float16).to(device).eval()
    def encode(texts,is_query=False):
        if is_query:texts=['Represent this query for retrieving code: '+text for text in texts]
        encoded=tokenizer(texts,padding=True,truncation=True,max_length=512,return_tensors='pt').to(device)
        with torch.inference_mode():vectors=model(**encoded).last_hidden_state[:,0]
        return torch.nn.functional.normalize(vectors.float(),dim=-1)
    directory=args.run_dir/'candidates';directory.mkdir(exist_ok=True)
    for i,item in enumerate(inputs):
        path=directory/f'{i:03d}.json'
        if path.exists():
            row=json.loads(path.read_text(encoding='utf-8'))
            if row['manifest_sha256']!=m['manifest_sha256'] or row['instance_id']!=item['instance_id']:raise ValueError('Stored candidates mismatch')
            print(f'candidate cached {i+1}/{len(inputs)}',flush=True);continue
        start=time.perf_counter();tid=item['instance_id'];anchor=anchors[tid]
        pair=json.loads((args.parent/'retrieval_tasks'/f'{i:03d}.json').read_text(encoding='utf-8'))['results']
        effective=effective_pair(responses[2*i:2*i+2])
        for result,response in zip(pair,effective):validate_retrieval(result,response,item['baseline'],{'manifest_sha256':json.loads((args.parent/'manifest.json').read_text())['manifest_sha256']})
        generated=next(r['order'] for r in pair if r['arm']=='preplanned')
        arms={'historical':anchor['anchor']['ids'],
              'body_original':[r['id'] for r in item['baseline']['actions']['original']['candidates']],
              'generated':generated}
        wanted=list(dict.fromkeys(n for arm in ARM_NAMES for n in arms[arm]))
        snapshot=SnapshotIndex(args.repos).path_for(item['baseline']);files=read_snapshot(snapshot)
        if digest(sorted(files.items()))!=item['baseline']['snapshot_content_sha256']:raise ValueError('Snapshot changed')
        graph,_=build_graph(files)
        # Full original issue, not the generated query and not a truncated prompt.
        task_rows=[TaskInput.from_mapping(t) for t in read_rows(args.parent/'tasks.jsonl')]
        issue=next(t.problem_statement for t in task_rows if t.instance_id==tid)
        features,feature_audit=candidate_features(issue,files,graph,anchor['anchor'],wanted)
        old_dense=dict(zip(anchor['anchor']['ids'],anchor['cosine']))
        new_ids=[n for n in wanted if n not in old_dense]
        docs=encoder_documents(new_ids,graph.nodes,files)
        query=encode([issue[:1200]],True)
        dense=dict(old_dense)
        for offset in range(0,len(docs),32):
            block=encode(docs[offset:offset+32])
            values=(block@query.T).view(-1).cpu().tolist()
            for node_id,value in zip(new_ids[offset:offset+32],values):dense[node_id]=round(value,4)
        row={'instance_id':tid,'repo':anchor['repo'],'manifest_sha256':m['manifest_sha256'],'arms':arms,
             'ids':wanted,'rows':[values+[dense[n]] for n,values in zip(wanted,features)],
             'feature_names':list(FEATURES)+['dense_cosine'],'feature_audit':feature_audit,
             'new_dense_candidates':len(new_ids),'dense_document_chars':sum(map(len,docs)),
             'source_chars_read':sum(map(len,files.values())),'seconds':time.perf_counter()-start,
             'generated_source_response_sha256':digest(responses[2*i]),'snapshot_sha256':item['baseline']['snapshot_content_sha256']}
        if any(len(pool)>200 for pool in arms.values()):raise ValueError('Candidate cap exceeded')
        write_json(path,row)
        print(f'candidates {i+1}/{len(inputs)} {tid} new_dense={len(new_ids)}',flush=True)


def predict(args):
    import lightgbm as lgb
    import numpy as np
    m,inputs,responses,anchors=load_run(args)
    audit=json.loads((args.run_dir/'training_audit.json').read_text(encoding='utf-8'))
    for name,fingerprint in audit['model_hashes'].items():
        if file_hash(args.run_dir/'models'/name)!=fingerprint:raise ValueError('Trained model changed')
    models={i:[lgb.Booster(model_file=str(args.run_dir/'models'/f'fold{i}_seed{seed}.txt')) for seed in SEEDS] for i in range(2)}
    baseline={r['instance_id']:r for r in read_rows(args.run_dir/'historical_predictions.jsonl')}
    with (args.run_dir/'predictions.jsonl').open('x',encoding='utf-8') as stream:
        for i,item in enumerate(inputs):
            path=args.run_dir/'candidates'/f'{i:03d}.json';row=json.loads(path.read_text(encoding='utf-8'))
            if row['instance_id']!=item['instance_id'] or row['manifest_sha256']!=m['manifest_sha256']:raise ValueError('Candidate identity mismatch')
            fold=next(j for j,f in enumerate(m['folds']) if row['repo'] in f['test_repos'])
            if row['repo'] in m['folds'][fold]['train_repos']:raise ValueError('Test repository in training')
            scores=np.mean([model.predict(np.array(row['rows']),num_threads=2) for model in models[fold]],axis=0).tolist()
            lookup=dict(zip(row['ids'],scores))
            old_scores=[lookup[n] for n in row['arms']['historical']]
            if any(abs(a-b)>1e-9 for a,b in zip(old_scores,baseline[row['instance_id']]['scores'])):raise ValueError('Historical pool scores differ under extension')
            arms={arm:sorted(pool,key=lambda n:-lookup[n]) for arm,pool in row['arms'].items()}
            stream.write(canonical({'instance_id':row['instance_id'],'repo':row['repo'],'manifest_sha256':m['manifest_sha256'],
                                    'fold':fold,'candidate_sha256':file_hash(path),'arms':arms,
                                    'scores':lookup,'new_dense_candidates':row['new_dense_candidates']})+'\n')
    print(canonical({'predicted_tasks':len(inputs),'historical_score_equality':'passed','new_api_calls':0}))


def cluster_interval(rows,comparison,replicates=5000):
    groups=defaultdict(list)
    for row in rows:groups[row['repo']].append(row['arms']['generated']['recall_at_10']-row['arms'][comparison]['recall_at_10'])
    rng=random.Random(20261103);repos=sorted(groups)
    if len(repos)<2:return None
    draws=sorted(statistics.mean(d for repo in rng.choices(repos,k=len(repos)) for d in groups[repo]) for _ in range(replicates))
    return [draws[int(.025*(replicates-1))],draws[int(.975*(replicates-1))]]


def evaluate(args):
    from tools.evaluate_query_pilot import gold_targets
    m,inputs,responses,anchors=load_run(args)
    predictions=read_rows(args.run_dir/'predictions.jsonl')
    if [r['instance_id'] for r in predictions]!=m['task_ids']:raise ValueError('Prediction task set changed')
    records=read_rows(args.gold);gold={r['instance_id']:r for r in records}
    if len(gold)!=len(records):raise ValueError('Duplicate gold ID')
    scores=[]
    for i,(item,row) in enumerate(zip(inputs,predictions)):
        if row['manifest_sha256']!=m['manifest_sha256'] or row['candidate_sha256']!=file_hash(args.run_dir/'candidates'/f'{i:03d}.json'):raise ValueError('Candidate provenance changed')
        record=gold.get(row['instance_id'])
        if record and any(record.get(k)!=item['baseline'][k] for k in ('repo','base_commit')):raise ValueError('Gold identity mismatch')
        targets=gold_targets(record) if record else set()
        historical_top=set(row['arms']['historical'][:10])
        arms={name:{'coverage':len(set(order)&targets)/len(targets) if targets else None,
                    'recall_at_10':len(set(order[:10])&targets)/len(targets) if targets else None,
                    'new_targets_vs_historical':sorted((set(order[:10])&targets)-historical_top),
                    'lost_targets_vs_historical':sorted((historical_top&targets)-set(order[:10]))} for name,order in row['arms'].items()}
        scores.append({'instance_id':row['instance_id'],'repo':row['repo'],'gold_count':len(targets),'scorable':bool(targets),'arms':arms})
    valid=[r for r in scores if r['scorable']]
    means={arm:{metric:statistics.mean(r['arms'][arm][metric] for r in valid) for metric in ('coverage','recall_at_10')} for arm in ARM_NAMES}
    comparisons={}
    for base in ('body_original','historical'):
        comparisons[base]={'delta':means['generated']['recall_at_10']-means[base]['recall_at_10'],
                           'descriptive_repo_bootstrap_95':cluster_interval(valid,base),
                           'improved_tasks':[r['instance_id'] for r in valid if r['arms']['generated']['recall_at_10']>r['arms'][base]['recall_at_10']],
                           'harmed_tasks':[r['instance_id'] for r in valid if r['arms']['generated']['recall_at_10']<r['arms'][base]['recall_at_10']]}
    ci=comparisons['body_original']['descriptive_repo_bootstrap_95'];decision='uncertain'
    if ci and ci[0]>=.02:decision='worth_further_exploration'
    elif ci and ci[1]<.02:decision='no_worthwhile_gain_under_current_protocol'
    summary={'manifest_sha256':m['manifest_sha256'],'predictions_sha256':file_hash(args.run_dir/'predictions.jsonl'),
             'gold_sha256':file_hash(args.gold),'training_audit_sha256':file_hash(args.run_dir/'training_audit.json'),
             'tasks':len(scores),'scorable_tasks':len(valid),'means':means,'comparisons':comparisons,'decision':decision,
             'new_dense_candidates':sum(r['new_dense_candidates'] for r in predictions),'new_api_calls':0,
             'limits':m['limits'],'automatic_expansion':False}
    with (args.run_dir/'scores.jsonl').open('x',encoding='utf-8') as stream:
        for row in scores:stream.write(canonical(row)+'\n')
    write_json(args.run_dir/'summary.json',summary)
    print(json.dumps({k:summary[k] for k in ('tasks','scorable_tasks','means','comparisons','decision','new_dense_candidates','new_api_calls')},indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    for command in ('prepare','train','candidates','predict','evaluate'):
        ap=sub.add_parser(command);ap.add_argument('--run-dir',type=Path,required=True)
        ap.add_argument('--parent',type=Path,default=ROOT/'experiments/runs/flash-replication-20261102-v1')
        ap.add_argument('--features',type=Path,default=ROOT/'data/features_full.jsonl')
        ap.add_argument('--embed',type=Path,default=ROOT/'data/embed_retrieval.jsonl')
        ap.add_argument('--historical-metrics',type=Path,default=ROOT/'data/dense_scores.jsonl')
        ap.add_argument('--model-dir',type=Path,default=ROOT/'models/bge-small-en-v1.5')
        ap.add_argument('--repos',type=Path,default=ROOT/'data/repos')
        ap.add_argument('--gold',type=Path,default=ROOT/'data/gold_symbols.jsonl')
    args=p.parse_args();{'prepare':prepare,'train':train,'candidates':candidates,'predict':predict,'evaluate':evaluate}[args.command](args)


if __name__=='__main__':main()
