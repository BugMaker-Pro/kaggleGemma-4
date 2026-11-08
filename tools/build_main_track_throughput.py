"""Prepare a bounded serial-versus-two-worker development throughput probe."""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from tools.build_main_track import agent_files, cell, freeze_split, make_notebook, make_zip, MODEL

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--task-ids',nargs=2,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--run-suffix',required=True)
    parser.add_argument('--dependency-kernel',default='yyyyhhhhwww/gemma4-requests-test-wheels-20261108-v2')
    args=parser.parse_args(argv)
    if args.out.exists():raise ValueError('Refusing existing throughput output')
    split=freeze_split(ROOT/'.cache/main-track/official/tasks.jsonl')
    if len(set(args.task_ids))!=2 or not set(args.task_ids)<=set(split['development']):
        raise ValueError('Throughput probe needs two distinct frozen development tasks')
    starter=json.loads((ROOT/'.cache/main-track/official-starter.json').read_text(encoding='utf-8-sig'))
    files=agent_files(ROOT/'.cache/main-track/official/sample_submission','baseline',completion_guardrails=True,max_output_tokens=8192)
    notebook=make_notebook(starter,{'baseline':files},split,repair_test_dependencies=True,
                           repair_source_layout=True,engineering_task_id=args.task_ids[0])
    code='''import asyncio, concurrent.futures, json, time, yaml
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps._configs import EventsCompactionConfig
from swegemma.config import EvalConfig
from swegemma.evaluate import Evaluator
'''
    code+='PROBE_IDS='+repr(args.task_ids)+'\n'
    code+='''assert len(set(PROBE_IDS))==2 and set(PROBE_IDS)<=set(SPLIT['development'])
def run_sync(coroutine):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda:asyncio.run(coroutine)).result()
AGENT_DIR=WORKING_DIR/'agents'/'baseline'
budget=yaml.safe_load((AGENT_DIR/'eval_config.yaml').read_text())['evaluation']
measurements=[]
try:
    for round_name, concurrency in [('serial',1),('parallel',2)]:
        config=EvalConfig(tasks_path=TASKS_PATH,snapshots_dir=DATA_DIR/'snapshots',
            results_dir=WORKING_DIR/'results'/round_name,submission_dir=AGENT_DIR,models=models,
            sandbox='subprocess',timeout_seconds=budget['timeout_seconds'],verification_timeout_seconds=300,
            max_time_minutes=budget['max_time_minutes'],max_tool_calls=budget['max_tool_calls'],max_turns=budget['max_turns'],
            limits=limits,generation_constraints=gen_constraints,adapter_manifest=adapters,
            context_cache_config=ContextCacheConfig(min_tokens=2048,ttl_seconds=1800,cache_intervals=10),
            events_compaction_config=EventsCompactionConfig(compaction_interval=15,overlap_size=2,token_threshold=14336,event_retention_size=5),
            graph_dir=GRAPH_DIR,embeddings_dir=EMBEDDINGS_DIR,wheels_dir=DATA_DIR/'wheels',
            task_ids=PROBE_IDS,concurrency=concurrency,display_mode='quiet',verbose=False)
        print('Starting throughput round',round_name,PROBE_IDS,flush=True)
        started=time.perf_counter()
        evaluated=run_sync(Evaluator(config).run())
        elapsed=time.perf_counter()-started
        assert {row.instance_id for row in evaluated.task_results}==set(PROBE_IDS)
        record={'round':round_name,'concurrency':concurrency,'wall_seconds':elapsed,
            'resolved':sum(row.resolved for row in evaluated.task_results),'tasks':len(evaluated.task_results),
            'per_task':[{'id':row.instance_id,'resolved':row.resolved,'tool_calls':row.tool_calls,
                         'duration_seconds':row.duration_seconds,'error':row.error} for row in evaluated.task_results]}
        measurements.append(record)
        (WORKING_DIR/'throughput-results.json').write_text(json.dumps({'rounds':measurements,
            'scope':'Exploratory two-task throughput probe, not an effectiveness comparison',
            'order':'serial then parallel; shared server caches may favor the second round'},indent=2))
        print(json.dumps(record),flush=True)
finally:
    server_instance.stop()
'''
    notebook['cells'][-2]=cell('code',code)
    notebook['cells'][0]=cell('markdown','# Development throughput probe\n\nSame two frozen development tasks, same baseline prompt/model/budget, one serial round then two-worker execution. Shared model is loaded once. Fixed order and shared caches limit causal interpretation of speed differences. Complete per-task outputs and failures are retained.\n')
    args.out.mkdir(parents=True)
    for name,text in files.items():
        target=args.out/'baseline'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text,encoding='utf-8')
    make_zip(files,args.out/'baseline_submission.zip')
    (args.out/'throughput.ipynb').write_text(json.dumps(notebook,indent=2),encoding='utf-8')
    manifest={'engineering_task_ids':args.task_ids,'split':split,'model':MODEL,'arm':'baseline',
              'concurrency_order':[1,2],'completion_guardrails':True,'max_output_tokens':8192,
              'files':{name:hashlib.sha256(text.encode()).hexdigest() for name,text in files.items()},
              'notebook_sha256':hashlib.sha256((args.out/'throughput.ipynb').read_bytes()).hexdigest(),
              'scope':'Exploratory matched two-task throughput; fixed order/cache confounding disclosed'}
    (args.out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    request={'newTitle':'Gemma4 throughput '+args.run_suffix,'slug':'gemma4-throughput-'+args.run_suffix,
             'text':json.dumps(notebook),'language':'python','kernelType':'notebook','isPrivate':True,'enableGpu':True,
             'enableInternet':False,'enableTpu':False,'machineShape':starter['metadata']['machineShape'],
             'sessionTimeoutSeconds':3600,'dockerImage':starter['metadata']['dockerImage'],'dockerImagePinningType':'original',
             'datasetDataSources':starter['metadata']['datasetDataSources'],'competitionDataSources':['gemma-4-developer-agent'],
             'kernelDataSources':[args.dependency_kernel],'modelDataSources':['google/gemma-4/Other/'+MODEL+'/2']}
    (args.out/'kernel-request.json').write_text(json.dumps(request),encoding='utf-8')
    print('Prepared 2 development tasks x serial/parallel; 4 model task runs; no launch.')
    return 0
if __name__=='__main__':raise SystemExit(main())
