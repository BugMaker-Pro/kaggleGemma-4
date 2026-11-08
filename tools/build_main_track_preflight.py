"""Build offline, CPU-only verification controls for frozen development tasks."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from tools.build_main_track import cell, freeze_split, TEST_DEPENDENCY_SETUP, SOURCE_LAYOUT_SETUP, ADDITIONAL_TEST_DEPENDENCY_SETUP

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--task-ids',nargs='+',required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--run-suffix',required=True)
    parser.add_argument('--additional-dependency-kernel')
    parser.add_argument('--dependency-kernel',default='yyyyhhhhwww/gemma4-requests-test-wheels-20261108-v2')
    args=parser.parse_args(argv)
    if args.out.exists():raise ValueError('Refusing to overwrite existing preflight')
    split=freeze_split(ROOT/'.cache/main-track/official/tasks.jsonl')
    if len(args.task_ids)!=len(set(args.task_ids)) or not set(args.task_ids)<=set(split['development']):
        raise ValueError('Preflight task selection must contain unique frozen development IDs only')
    starter=json.loads((ROOT/'.cache/main-track/official-starter.json').read_text(encoding='utf-8-sig'))
    original=json.loads(starter['blob']['source'])
    code='''import asyncio, concurrent.futures, hashlib, json, time
from pathlib import Path
from adk_submission import ModelRegistry
from swegemma.config import EvalConfig
from swegemma.models import load_tasks
from swegemma.deduplication import resolve_task_snapshot_paths
from swegemma.sandbox import SubprocessManager
from swegemma.harness.verification import verify_task
from swegemma.results import append_task_result
DATA_DIR=Path('/kaggle/input/competitions/gemma-4-developer-agent')
WORKING_DIR=Path('/kaggle/working')
TASKS_PATH=DATA_DIR/'tasks.jsonl'
'''
    code+='SPLIT=json.loads('+repr(json.dumps(split))+')\n'
    code+='SELECTED_IDS='+repr(args.task_ids)+'\n'
    code+='''assert hashlib.sha256(TASKS_PATH.read_bytes()).hexdigest()==SPLIT['task_file_sha256']
assert set(SELECTED_IDS)<=set(SPLIT['development'])
tasks={task.instance_id:task for task in load_tasks(TASKS_PATH)}
def run_sync(coroutine):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda:asyncio.run(coroutine)).result()
for task_id in SELECTED_IDS:
    task=tasks[task_id]
    assert task.patch.strip() and task.test_patch.strip()
    snapshot,base_snapshot,snapshot_patch=resolve_task_snapshot_paths(DATA_DIR/'snapshots',task.instance_id,task.repo)
    assert snapshot.exists()
    for arm,patch in [('empty_control',''),('reference_control',task.patch)]:
        output=WORKING_DIR/'results'/task_id/arm
        config=EvalConfig(tasks_path=TASKS_PATH,snapshots_dir=DATA_DIR/'snapshots',results_dir=output,
            submission_dir=DATA_DIR/'sample_submission',models=ModelRegistry(),sandbox='subprocess',
            wheels_dir=DATA_DIR/'wheels',timeout_seconds=60,verification_timeout_seconds=300,display_mode='quiet')
        started=time.perf_counter()
        print('Checking',task_id,arm,flush=True)
        try:
            result=run_sync(verify_task(SubprocessManager(timeout_seconds=60),config,task,snapshot,
                base_snapshot_path=base_snapshot,patch_path=snapshot_patch,agent_patch=patch,start_time=started))
            append_task_result(result,output,[result])
            record={'arm':arm,'task_id':task_id,'resolved':result.resolved,'test_exit_code':result.test_exit_code,
                    'error':result.error,'duration_seconds':result.duration_seconds,'purpose':'development_environment_preflight'}
            print((result.test_output or '')[-1000:],flush=True)
        except Exception as exc:
            record={'arm':arm,'task_id':task_id,'resolved':False,'test_exit_code':-1,
                    'error':type(exc).__name__+': '+str(exc),'duration_seconds':time.perf_counter()-started,
                    'purpose':'development_environment_preflight','infrastructure_exception':True}
        with (WORKING_DIR/'verification_results.jsonl').open('a',encoding='utf-8') as handle:
            handle.write(json.dumps(record)+chr(10))
        print(json.dumps(record),flush=True)
'''
    nb={'nbformat':4,'nbformat_minor':5,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'}},
        'cells':[cell('markdown','# Frozen development environment preflight\n\nNo model inference. All selected development tasks get both empty/reference controls. Dependencies and src-path correction match the passing Requests controls. Failures are retained; no confirmation tasks are accessed for evaluation.\n'),
                 cell('code',''.join(original['cells'][2]['source'])),cell('code',TEST_DEPENDENCY_SETUP),cell('code',SOURCE_LAYOUT_SETUP),*([cell('code',ADDITIONAL_TEST_DEPENDENCY_SETUP)] if args.additional_dependency_kernel else []),cell('code',code)]}
    request={'newTitle':'Gemma4 development preflight '+args.run_suffix,'slug':'gemma4-development-preflight-'+args.run_suffix,
             'text':json.dumps(nb),'language':'python','kernelType':'notebook','isPrivate':True,'enableGpu':False,
             'enableInternet':False,'enableTpu':False,'sessionTimeoutSeconds':3600,
             'dockerImage':starter['metadata']['dockerImage'],'dockerImagePinningType':'original',
             'datasetDataSources':starter['metadata']['datasetDataSources'],'competitionDataSources':['gemma-4-developer-agent'],
             'kernelDataSources':[source for source in (args.dependency_kernel,args.additional_dependency_kernel) if source],'modelDataSources':[]}
    args.out.mkdir(parents=True)
    (args.out/'kernel-request.json').write_text(json.dumps(request),encoding='utf-8')
    (args.out/'preflight.ipynb').write_text(json.dumps(nb,indent=2),encoding='utf-8')
    (args.out/'manifest.json').write_text(json.dumps({'task_ids':args.task_ids,'split':split,'model_inference':False,
        'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'notebook_sha256':hashlib.sha256((args.out/'preflight.ipynb').read_bytes()).hexdigest(),
        'failure_policy':'Retain all tasks and both controls; record infrastructure errors separately'},indent=2),encoding='utf-8')
    print('Prepared',len(args.task_ids),'development tasks,',len(args.task_ids)*2,'CPU controls; no GPU or confirmation evaluation.')
    return 0
if __name__=='__main__':raise SystemExit(main())
