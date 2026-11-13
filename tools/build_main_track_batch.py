"""Build matched baseline/evidence/graph batch runs over the frozen official task split.

The competition exposes 129 verifiable tasks (10 development + 119 confirmation).
The old hard cap at 10 was a self-imposed experimental convention, not a Kaggle
or verification limit; all 129 tasks carry test_patch/patch and can be scored by
the official verifier.  Task provenance is still recorded per result so a run
that consumes confirmation tasks is never misreported as untouched held-out.
"""
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from tools.build_main_track import ARMS, MODEL, agent_files, cell, freeze_split, make_notebook, make_zip

def batch_evaluation_code(task_ids, concurrency, display='quiet', *,
                          allow_confirmation=True, scope='development_only'):
    code='''import asyncio, concurrent.futures, hashlib, json, time, yaml
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps._configs import EventsCompactionConfig
from swegemma.config import EvalConfig
from swegemma.evaluate import Evaluator
'''
    code+='BATCH_IDS='+repr(task_ids)+'\nCONCURRENCY='+str(concurrency)+'\nDISPLAY='+repr(display)+'\n'
    allowed=("set(SPLIT['development'])|set(SPLIT.get('confirmation',[]))" if allow_confirmation
             else "set(SPLIT['development'])")
    code+='assert set(BATCH_IDS)<='+allowed+'\n'
    code+='''def run_sync(coro):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:return pool.submit(lambda:asyncio.run(coro)).result()
try:
    for arm in PAYLOADS:
        AGENT_DIR=WORKING_DIR/'agents'/arm
        budget=yaml.safe_load((AGENT_DIR/'eval_config.yaml').read_text())['evaluation']
        config=EvalConfig(tasks_path=TASKS_PATH,snapshots_dir=DATA_DIR/'snapshots',results_dir=WORKING_DIR/'results'/arm,
            submission_dir=AGENT_DIR,models=models,sandbox='subprocess',timeout_seconds=budget['timeout_seconds'],
            verification_timeout_seconds=300,max_time_minutes=budget['max_time_minutes'],max_tool_calls=budget['max_tool_calls'],
            max_turns=budget['max_turns'],limits=limits,generation_constraints=gen_constraints,adapter_manifest=adapters,
            context_cache_config=ContextCacheConfig(min_tokens=2048,ttl_seconds=1800,cache_intervals=10),
            events_compaction_config=EventsCompactionConfig(compaction_interval=15,overlap_size=2,token_threshold=14336,event_retention_size=5),
            graph_dir=GRAPH_DIR,embeddings_dir=EMBEDDINGS_DIR,wheels_dir=DATA_DIR/'wheels',
            task_ids=BATCH_IDS,concurrency=CONCURRENCY,display_mode=DISPLAY,verbose=False)
        print('Starting development batch',arm,BATCH_IDS,flush=True)
        started=time.perf_counter()
        result=run_sync(Evaluator(config).run())
        assert {r.instance_id for r in result.task_results}==set(BATCH_IDS)
        with (WORKING_DIR/'batch-results.jsonl').open('a',encoding='utf-8') as handle:
            for row in result.task_results:
                record={'arm':arm,'task_id':row.instance_id,'resolved':row.resolved,'test_exit_code':row.test_exit_code,
                    'tool_calls':row.tool_calls,'duration_seconds':row.duration_seconds,'error':row.error,
                    'patch_sha256':hashlib.sha256((row.agent_patch or '').encode()).hexdigest(),
                    'patch_chars':len(row.agent_patch or ''),'scope':'development_only'}
                handle.write(json.dumps(record)+chr(10))
                print(json.dumps(record),flush=True)
        print('Batch elapsed seconds',arm,time.perf_counter()-started,flush=True)
finally:
    server_instance.stop()
'''
    code=code.replace("'scope':'development_only'","'scope':'"+scope+"'")
    if scope!='development_only':
        code=code.replace("Starting development batch","Starting "+scope+" batch")
    return code

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--task-ids',nargs='+',required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--run-suffix',required=True)
    parser.add_argument('--concurrency',type=int,choices=(1,2,3,4,6),default=2)
    parser.add_argument('--display',choices=('quiet','single'),default='quiet',
                        help='single streams every agent step to the notebook log; requires concurrency 1')
    parser.add_argument('--arms',nargs='+',choices=ARMS,default=list(ARMS))
    parser.add_argument('--command-timeout',type=int,choices=(60,120),default=60)
    parser.add_argument('--max-time-minutes',type=int,choices=(3,5,8,10,15,30),default=3)
    parser.add_argument('--max-tool-calls',type=int,choices=(30,60,90),default=30,
                        help='per-task tool-call cap; 30 is the frozen default, raise only for an explicit budget contrast')
    parser.add_argument('--max-turns',type=int,choices=(50,80),default=50)
    args=parser.parse_args(argv)
    if args.display=='single' and args.concurrency!=1:
        raise ValueError('display single requires --concurrency 1; the harness downgrades it to a dashboard otherwise')
    if args.out.exists():raise ValueError('Refusing existing batch directory')
    split=freeze_split(ROOT/'.cache/main-track/official/tasks.jsonl')
    all_tasks=set(split['development'])|set(split['confirmation'])
    if len(args.task_ids)!=len(set(args.task_ids)) or not set(args.task_ids)<=all_tasks:
        raise ValueError('Only unique frozen official task ids allowed')
    used_confirmation=sorted(set(args.task_ids)&set(split['confirmation']))
    scope='mixed_exploratory' if used_confirmation else 'development_only'
    starter=json.loads((ROOT/'.cache/main-track/official-starter.json').read_text(encoding='utf-8-sig'))
    payloads={arm:agent_files(ROOT/'.cache/main-track/official/sample_submission',arm,completion_guardrails=True,max_output_tokens=8192,max_time_minutes=args.max_time_minutes,max_tool_calls=args.max_tool_calls,max_turns=args.max_turns) for arm in args.arms}
    for files in payloads.values():
        files['eval_config.yaml']=files['eval_config.yaml'].replace('timeout_seconds: 60','timeout_seconds: '+str(args.command_timeout))
    nb=make_notebook(starter,payloads,split,repair_test_dependencies=True,repair_source_layout=True,
                     additional_test_dependency=True,engineering_task_id=args.task_ids[0])
    code=batch_evaluation_code(args.task_ids,args.concurrency,args.display,scope=scope)
    nb['cells'][-2]=cell('code',code)
    provenance=('Uses '+str(len(used_confirmation))+' frozen confirmation tasks for exploratory capacity testing; '
                'NOT an untouched held-out result. ' if used_confirmation else '')
    nb['cells'][0]=cell('markdown','# Official-task batch\n\nArms: '+', '.join(payloads)+'. '+provenance+'All 129 frozen official tasks are eligible; all failures retained. Command timeout: '+str(args.command_timeout)+' seconds. Environment verified by empty/reference controls before launch. Concurrency: '+str(args.concurrency)+'. This setting does not establish useful throughput or confirmatory performance.\n')
    args.out.mkdir(parents=True)
    manifest={'model':MODEL,'engineering_task_ids':args.task_ids,'split':split,'concurrency':args.concurrency,'arms':{},
              'output_tokens':8192,'command_timeout':args.command_timeout,'max_time_minutes':args.max_time_minutes,
              'max_tool_calls':args.max_tool_calls,'max_turns':args.max_turns,
              'display_mode':args.display,'completion_guardrails':True,
              'scope':('mixed_exploratory_not_held_out' if used_confirmation else 'development_only_not_confirmatory'),
              'confirmation_tasks_used':used_confirmation}
    for arm,files in payloads.items():
        for name,text in files.items():
            target=args.out/arm/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text,encoding='utf-8')
        make_zip(files,args.out/(arm+'_submission.zip'))
        manifest['arms'][arm]={'files':{name:hashlib.sha256(text.encode()).hexdigest() for name,text in files.items()}}
    (args.out/'batch.ipynb').write_text(json.dumps(nb,indent=2),encoding='utf-8')
    manifest['notebook_sha256']=hashlib.sha256((args.out/'batch.ipynb').read_bytes()).hexdigest()
    (args.out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    req={'newTitle':'Gemma4 development batch '+args.run_suffix,'slug':'gemma4-development-batch-'+args.run_suffix,
         'text':json.dumps(nb),'language':'python','kernelType':'notebook','isPrivate':True,'enableGpu':True,'enableInternet':False,
         'enableTpu':False,'sessionTimeoutSeconds':3600,'machineShape':starter['metadata']['machineShape'],
         'dockerImage':starter['metadata']['dockerImage'],'dockerImagePinningType':'original',
         'datasetDataSources':starter['metadata']['datasetDataSources'],'competitionDataSources':['gemma-4-developer-agent'],
         'kernelDataSources':['yyyyhhhhwww/gemma4-requests-test-wheels-20261108-v2','yyyyhhhhwww/gemma4-fastapi-test-wheels-20261108'],
         'modelDataSources':['google/gemma-4/Other/'+MODEL+'/2']}
    (args.out/'kernel-request.json').write_text(json.dumps(req),encoding='utf-8')
    print('Prepared',len(args.task_ids),'tasks x',len(payloads),'arms, concurrency',args.concurrency,'; requires all per-task environment gates.')
    return 0
if __name__=='__main__':raise SystemExit(main())
