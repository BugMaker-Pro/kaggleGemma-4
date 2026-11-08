"""Build a CPU-only probe using the official skill tool and sandbox executor."""
from pathlib import Path
import argparse,hashlib,json,sys
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from tools.build_main_track import cell,freeze_split

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',type=Path,default=ROOT/'.cache/main-track/ranker-tool-probe-v1')
    args=ap.parse_args()
    if args.out.exists():raise ValueError('Refusing existing probe')
    starter=json.loads((ROOT/'.cache/main-track/official-starter.json').read_text(encoding='utf-8-sig'))
    original=json.loads(starter['blob']['source'])
    package=json.loads((ROOT/'artifacts/ranker-agent-v1/manifest.json').read_text())
    split=freeze_split(ROOT/'.cache/main-track/official/tasks.jsonl')
    code='''import asyncio, concurrent.futures, hashlib, json, shutil, time, zipfile
from pathlib import Path
from types import SimpleNamespace
from adk_submission import validate_directory
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset, RunSkillScriptTool
from swegemma.config import build_submission_limits
from swegemma.models import load_tasks
from swegemma.deduplication import resolve_task_snapshot_paths
from swegemma.sandbox import SubprocessManager, AdkSandboxCodeExecutor
from swegemma.context import SwegemmaContext
from swegemma.harness.container_setup import extract_snapshot, setup_baseline_commit, setup_git_exclude
WORK=Path('/kaggle/working')
DATA=Path('/kaggle/input/competitions/gemma-4-developer-agent')
PACKAGE=WORK/'ranker-agent'
'''
    code+='EXPECTED_PACKAGE=json.loads('+repr(json.dumps(package))+')\n'
    code+='SPLIT=json.loads('+repr(json.dumps(split))+')\n'
    code+='''archives=list(Path('/kaggle/input').rglob('ranker-agent.zip'))
if archives:
    assert len(archives)==1
    assert hashlib.sha256(archives[0].read_bytes()).hexdigest()==EXPECTED_PACKAGE['zip_sha256']
    PACKAGE.mkdir(exist_ok=True)
    with zipfile.ZipFile(archives[0]) as archive:
        for item in archive.infolist():
            target=(PACKAGE/item.filename).resolve()
            assert target.is_relative_to(PACKAGE.resolve())
            assert (item.external_attr>>16)&0o170000 != 0o120000
            if not item.is_dir():
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(item))
else:
    manifests=list(Path('/kaggle/input').rglob('ranker-package-manifest.json'))
    assert len(manifests)==1,manifests
    shutil.copytree(manifests[0].parent,PACKAGE)
for name,digest in EXPECTED_PACKAGE['files'].items():
    assert hashlib.sha256((PACKAGE/name).read_bytes()).hexdigest()==digest,name
limits,_=build_submission_limits()
validate_directory(PACKAGE,limits=limits)
skill=load_skill_from_dir(PACKAGE/'skills/ranker')
assert 'encoder/weights-int8.txt' in skill.resources.list_assets()
assert hashlib.sha256((DATA/'tasks.jsonl').read_bytes()).hexdigest()==SPLIT['task_file_sha256']
task=next(t for t in load_tasks(DATA/'tasks.jsonl') if t.instance_id==SPLIT['smoke_task_id'])
assert task.instance_id in SPLIT['development']
snapshot,base_snapshot,snapshot_patch=resolve_task_snapshot_paths(DATA/'snapshots',task.instance_id,task.repo)
manager=SubprocessManager(timeout_seconds=120)
sandbox_id=manager.start()
try:
    extract_snapshot(manager,sandbox_id,snapshot,base_snapshot_path=base_snapshot,patch_path=snapshot_patch)
    setup_git_exclude(manager,sandbox_id)
    setup_baseline_commit(manager,sandbox_id,'ranker_probe_baseline')
    # Only issue text and repository identity enter the skill context.
    context=SwegemmaContext(docker_manager=manager,container_id=sandbox_id,
        problem_statement=task.problem_statement,task_id=task.instance_id,repo=task.repo,
        max_time_minutes=5,max_exec_seconds=120,max_tool_calls=10)
    context.start_agent_session()
    executor=AdkSandboxCodeExecutor(sandbox=context.sandbox,timeout_seconds=120,
        start_time=context.agent_start_time,max_time_minutes=5,budget_check_fn=context.check_budget)
    toolset=SkillToolset(skills=[skill],code_executor=executor,script_timeout=120)
    tool=RunSkillScriptTool(toolset)
    invocation=SimpleNamespace(invocation_id='ranker_cpu_probe',_invocation_context=None)
    started=time.monotonic()
    async def invoke():
        return await tool.run_async(args={'skill_name':'ranker','file_path':'scripts/localize.py',
            'args':{'issue':task.problem_statement,'mode':'full'}},tool_context=invocation)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        output=pool.submit(lambda:asyncio.run(invoke())).result()
    (WORK/'ranker-tool-output.json').write_text(json.dumps(output,indent=2))
    elapsed=time.monotonic()-started
    rows=[]
    for line in output.get('stdout','').splitlines():
        try:rows.append(json.loads(line))
        except ValueError:pass
    result=next((row for row in reversed(rows) if isinstance(row,dict) and 'status' in row),{})
    check=manager.exec(sandbox_id,'git diff --binary HEAD && git ls-files --others --exclude-standard')
    report={'task_id':task.instance_id,'official_tool_status':output.get('status'),
        'localization_status':result.get('status'),'candidate_count':result.get('candidate_count'),
        'encoder_precision':result.get('encoder_precision'),'seconds':elapsed,
        'repository_unchanged':check.exit_code==0 and not check.stdout.strip(),
        'package_skill_bytes':EXPECTED_PACKAGE['skill_bytes'],'results':result.get('results',[]),
        'error':result.get('error') or output.get('error'),'mode':'official_skill_tool_inside_local_subprocess',
        'scope':'CPU skill integration; no repair model and no reference patch used by the tool; not official Docker compatibility'}
    (WORK/'ranker-tool-probe.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True)
    assert report['repository_unchanged'],'Skill changed repository'
    assert result.get('status')=='ok',output
    assert len(result['results'])==10 and result['mode']=='full'
finally:
    manager.stop(sandbox_id)
'''
    nb={'nbformat':4,'nbformat_minor':5,'metadata':{'kernelspec':{'name':'python3','display_name':'Python 3','language':'python'}},
        'cells':[cell('markdown','# Complete ranker: official skill execution probe\n\nOffline CPU integration test. Executes the uploaded full retrieval skill through RunSkillScriptTool and AdkSandboxCodeExecutor on one frozen development snapshot. No repair model or reference patch is passed to the skill.\n'),cell('code',''.join(original['cells'][2]['source'])),cell('code',code)]}
    args.out.mkdir(parents=True)
    (args.out/'probe.ipynb').write_text(json.dumps(nb,indent=2),encoding='utf-8')
    req={'newTitle':'Gemma4 full ranker tool probe 20261108','slug':'gemma4-full-ranker-tool-probe-20261108','text':json.dumps(nb),
        'language':'python','kernelType':'notebook','isPrivate':True,'enableGpu':False,'enableInternet':False,'enableTpu':False,'sessionTimeoutSeconds':1800,
        'dockerImage':starter['metadata']['dockerImage'],'dockerImagePinningType':'original',
        'datasetDataSources':starter['metadata']['datasetDataSources']+['yyyyhhhhwww/gemma4-complete-ranker-20261108-v1'],
        'competitionDataSources':['gemma-4-developer-agent'],'modelDataSources':[]}
    (args.out/'kernel-request.json').write_text(json.dumps(req),encoding='utf-8')
    (args.out/'manifest.json').write_text(json.dumps({'task_id':split['smoke_task_id'],'package_zip_sha256':package['zip_sha256'],'official_tool':True,'model_inference':False,'expected_mode':'full','scope':'development CPU integration'},indent=2),encoding='utf-8')
    print('Prepared official skill CPU probe; notebook bytes',(args.out/'probe.ipynb').stat().st_size)
if __name__=='__main__':main()
