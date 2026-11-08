from pathlib import Path
import ast,json,hashlib,textwrap
root=Path.cwd()
import sys
sys.path.insert(0,str(root))
from tools.build_main_track import cell,freeze_split
starter=json.loads((root/'.cache/main-track/official-starter.json').read_text(encoding='utf-8-sig'))
original=json.loads(starter['blob']['source'])
setup=''.join(original['cells'][2]['source'])
trace_path=root/'.cache/main-track/build-v2/output/results/baseline/traces/trace_requests_7433.json'
trace=json.loads(trace_path.read_text())
patches=[]
for step in trace['steps']:
    obs=step.get('observation') or {}
    if isinstance(obs,dict) and obs.get('extra',{}).get('tool_name')=='edit_file':
        response=json.loads(obs['content'])
        if response.get('status')=='ok':patches.append(response['diff'])
assert len(patches)==1
split=freeze_split(root/'.cache/main-track/official/tasks.jsonl')
body='''import asyncio, concurrent.futures, hashlib, json, time
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
body+='SPLIT=json.loads('+repr(json.dumps(split))+')\n'
body+='EDIT_ONLY_PATCH='+repr(patches[0])+'\n'
body+='''assert hashlib.sha256(TASKS_PATH.read_bytes()).hexdigest()==SPLIT['task_file_sha256']
task=next(task for task in load_tasks(TASKS_PATH) if task.instance_id==SPLIT['smoke_task_id'])
assert task.instance_id in SPLIT['development']
assert task.patch.strip() and task.test_patch.strip()
snapshot,base_snapshot,snapshot_patch=resolve_task_snapshot_paths(DATA_DIR/'snapshots',task.instance_id,task.repo)
assert snapshot.exists()

def run_sync(coroutine):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda:asyncio.run(coroutine)).result()

# Reference labels are used only in this host-side verification control.
# No model or repair agent is instantiated in this notebook.
for arm, patch in [('empty_control',''),('reference_control',task.patch),('baseline_edit_only',EDIT_ONLY_PATCH)]:
    output=WORKING_DIR/'results'/arm
    config=EvalConfig(tasks_path=TASKS_PATH,snapshots_dir=DATA_DIR/'snapshots',
        results_dir=output,submission_dir=DATA_DIR/'sample_submission',models=ModelRegistry(),
        sandbox='subprocess',wheels_dir=DATA_DIR/'wheels',timeout_seconds=60,
        verification_timeout_seconds=300,display_mode='quiet')
    manager=SubprocessManager(timeout_seconds=60)
    result=run_sync(verify_task(manager,config,task,snapshot,base_snapshot_path=base_snapshot,
        patch_path=snapshot_patch,agent_patch=patch,start_time=time.perf_counter()))
    append_task_result(result,output,[result])
    record={'arm':arm,'task_id':task.instance_id,'resolved':result.resolved,
            'test_exit_code':result.test_exit_code,'error':result.error,
            'duration_seconds':result.duration_seconds,'purpose':'verification_environment_control',
            'candidate_is_original_agent_patch':False}
    with (WORKING_DIR/'verification_results.jsonl').open('a') as out:out.write(json.dumps(record)+chr(10))
    print(json.dumps(record))
    print((result.test_output or '')[-5000:])
'''
nb={'nbformat':4,'nbformat_minor':5,'metadata':original.get('metadata',{}),
    'cells':[cell('markdown','# Verification environment controls\n\nNo model inference. Empty patch, reference patch, and the baseline edit-only diff are checked with the unchanged official verifier. The edit-only diff is reconstructed from the trace and is not asserted identical to the original full agent patch.\n'),cell('code',setup),cell('code',body)]}
out=root/'.cache/main-track/verification-v1';out.mkdir(parents=True,exist_ok=True)
(out/'verification.ipynb').write_text(json.dumps(nb,indent=2),encoding='utf-8')
request={'newTitle':'Gemma4 verification controls 20261108','slug':'gemma4-verification-controls-20261108',
 'text':json.dumps(nb),'language':'python','kernelType':'notebook','isPrivate':True,'enableGpu':False,
 'enableInternet':False,'enableTpu':False,'sessionTimeoutSeconds':1800,
 'dockerImage':starter['metadata']['dockerImage'],'dockerImagePinningType':'original',
 'datasetDataSources':starter['metadata']['datasetDataSources'],'competitionDataSources':['gemma-4-developer-agent'],
 'modelDataSources':[]}
(out/'kernel-request.json').write_text(json.dumps(request),encoding='utf-8')
(out/'manifest.json').write_text(json.dumps({'task_id':split['smoke_task_id'],'task_file_sha256':split['task_file_sha256'],
 'trace_sha256':hashlib.sha256(trace_path.read_bytes()).hexdigest(),'edit_patch_sha256':hashlib.sha256(patches[0].encode()).hexdigest(),
 'notebook_sha256':hashlib.sha256((out/'verification.ipynb').read_bytes()).hexdigest(),'gpu':False,'scope':'development verification controls'},indent=2))
print('Prepared CPU-only verification controls for',split['smoke_task_id'])
