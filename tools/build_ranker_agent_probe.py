"""Build a matched evidence baseline versus the full executable ranker on development tasks."""
from pathlib import Path
import argparse,hashlib,json,re,sys
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from tools.build_main_track import cell,agent_files,freeze_split,make_notebook,MODEL
DATASET='yyyyhhhhwww/gemma4-complete-ranker-20261108-v1'


def staged_overrides(baseline,locator_thinking_budget=0):
    """Use the supported sequential workflow; only the first stage has the skill.

    The locator emits one tool call, so its reasoning budget is a latency knob rather
    than a quality knob: 4096 thinking tokens can consume most of the shared 3-minute
    task budget before the skill ever runs. The repair stage keeps the baseline
    sampling file unchanged. Pass None to keep one shared sampling file.
    """
    root = 'agent_class: SequentialAgent\nname: full_ranker_pipeline\nsub_agents:\n  - config_path: ranker_stage.yaml\n  - config_path: repair_stage.yaml\n'
    sampling = baseline.get('configs/sampling.yaml')
    if locator_thinking_budget is not None and locator_thinking_budget <= 0:
        locator_thinking_budget = None
    locator_sampling = None
    sampling_include = 'configs/sampling.yaml'
    if locator_thinking_budget is not None:
        if not sampling or 'thinking_budget:' not in sampling:
            raise ValueError('locator thinking budget requires a baseline sampling file with thinking_budget')
        locator_sampling = re.sub(r'thinking_budget:\s*\d+','thinking_budget: '+str(locator_thinking_budget),sampling)
        if locator_sampling == sampling:
            raise ValueError('locator sampling override did not change any value')
        sampling_include = 'configs/locator_sampling.yaml'
    locator = ('name: full_ranker_locator\nmodel: '+MODEL+'\ninstruction: !include prompts/localize.md\n'
               'skills:\n  - skills/ranker\ntools: []\noutput_key: localization_report\n'
               'disallow_transfer_to_parent: true\ndisallow_transfer_to_peers: true\n'
               'generate_content_config: !include '+sampling_include+'\n')
    repair = baseline['agent.yaml'].replace('name: matched_repair_agent','name: localized_repair_agent')
    prompt = """You are the repository localization stage. Your entire job is to execute the full ranker once, even if the issue already specifies the fix. You have no code editing or shell tools.

First call run_skill_script with skill_name="ranker", file_path="scripts/localize.py", and args containing mode="full" and issue equal to the COMPLETE original problem below. Preserve all text, code blocks and line endings; never summarize or add the task budget or workspace layout. Do not call list_skills, load_skill or load_skill_resource; the interface above is complete. Do not read the skill's model weights or scripts. Do not skip the execution or invent rankings.

After the actual tool returns, finish this stage immediately with a short report of its status and the first three source locations. On an explicit error, report the error and finish. Do not repeat the call, attempt repairs, or call any other tool after receiving the result. The next stage will handle the code repair.

Original problem:
{problem_description}
"""
    repair_prompt = ('Use the localization report from the previous stage, which is already in this conversation, to '
                     'choose where to read before editing. The ranker has already run; do not run it again. If that stage '
                     'failed or produced no report, use normal search and still submit a non-empty source patch.\n\n'
                     +baseline['prompts/system.md'])
    result = {'agent.yaml':root,'ranker_stage.yaml':locator,'repair_stage.yaml':repair,
              'prompts/localize.md':prompt,'prompts/system.md':repair_prompt}
    # The mounted ranker package carries its own budget file; override it so both arms
    # run under the same session budget the baseline was built with.
    if 'eval_config.yaml' in baseline:
        result['eval_config.yaml']=baseline['eval_config.yaml']
    if sampling:
        result['configs/sampling.yaml']=sampling
    if locator_sampling is not None:
        result['configs/locator_sampling.yaml']=locator_sampling
    return result

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument('--task-ids',nargs='+',default=['requests_7433'])
    ap.add_argument('--out',type=Path,default=ROOT/'.cache/main-track/ranker-agent-smoke-v1')
    ap.add_argument('--suffix',default='20261108-v1')
    ap.add_argument('--staged',action='store_true')
    ap.add_argument('--ranker-only',action='store_true')
    ap.add_argument('--batch',action='store_true')
    ap.add_argument('--concurrency',type=int,choices=(1,2),default=2)
    ap.add_argument('--locator-thinking-budget',type=int,default=0,
                    help='thinking tokens for the localization stage; 0 shares the repair-stage sampling (default), 4096 matches it')
    ap.add_argument('--max-time-minutes',type=int,choices=(3,5),default=3)
    ap.add_argument('--display',choices=('quiet','single'),default='quiet',
                    help='single streams every agent step to the notebook log; requires concurrency 1')
    args=ap.parse_args(argv)
    if args.out.exists():raise ValueError('Refusing existing integration run')
    if args.display=='single' and args.concurrency!=1:
        raise ValueError('display single requires --concurrency 1; the harness downgrades it to a dashboard otherwise')
    split=freeze_split(ROOT/'.cache/main-track/official/tasks.jsonl')
    if len(set(args.task_ids))!=len(args.task_ids) or not set(args.task_ids)<=set(split['development']):
        raise ValueError('Only unique frozen development tasks allowed')
    starter=json.loads((ROOT/'.cache/main-track/official-starter.json').read_text(encoding='utf-8-sig'))
    package=json.loads((ROOT/'artifacts/ranker-agent-v1/manifest.json').read_text())
    baseline=agent_files(ROOT/'.cache/main-track/official/sample_submission','evidence',completion_guardrails=True,max_output_tokens=8192,max_time_minutes=args.max_time_minutes)
    baseline['eval_config.yaml']=baseline['eval_config.yaml'].replace('timeout_seconds: 60','timeout_seconds: 120')
    overrides=staged_overrides(baseline,args.locator_thinking_budget) if args.staged else {}
    runtime_files=dict(package['files'])
    runtime_files.update({name:hashlib.sha256(text.encode()).hexdigest() for name,text in overrides.items()})
    notebook=make_notebook(starter,{'baseline':baseline},split,repair_test_dependencies=True,repair_source_layout=True,
                           additional_test_dependency=True,engineering_task_id=args.task_ids[0])
    # Mounted immutable files avoid embedding model weights in notebook source.
    install='''import hashlib,json,shutil,zipfile
from pathlib import Path
'''
    install+='EXPECTED_PACKAGE=json.loads('+repr(json.dumps(package))+')\n'
    install+='RUNTIME_FILES=json.loads('+repr(json.dumps(runtime_files))+')\n'
    install+='OVERRIDES=json.loads('+repr(json.dumps(overrides))+')\n'
    install+='''archives=list(Path('/kaggle/input').rglob('ranker-agent.zip'))
ranker_dir=WORKING_DIR/'agents'/'ranker'
ranker_dir.mkdir(parents=True,exist_ok=True)
if archives:
    assert len(archives)==1
    assert hashlib.sha256(archives[0].read_bytes()).hexdigest()==EXPECTED_PACKAGE['zip_sha256']
    with zipfile.ZipFile(archives[0]) as archive:
        for item in archive.infolist():
            target=(ranker_dir/item.filename).resolve()
            assert target.is_relative_to(ranker_dir.resolve())
            assert (item.external_attr>>16)&0o170000!=0o120000
            if not item.is_dir():
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(item))
else:
    manifests=list(Path('/kaggle/input').rglob('ranker-package-manifest.json'))
    assert len(manifests)==1
    for name,digest in EXPECTED_PACKAGE['files'].items():
        target=ranker_dir/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(manifests[0].parent/name,target)
for name,digest in EXPECTED_PACKAGE['files'].items():
    assert hashlib.sha256((ranker_dir/name).read_bytes()).hexdigest()==digest,name
for name,text in OVERRIDES.items():
    target=ranker_dir/name
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(text,encoding='utf-8')
for name,digest in RUNTIME_FILES.items():
    assert hashlib.sha256((ranker_dir/name).read_bytes()).hexdigest()==digest,name
validate_directory(ranker_dir,limits=limits)
PAYLOADS['ranker']={name:(ranker_dir/name).read_text(encoding='utf-8') for name in RUNTIME_FILES}
assert (ranker_dir/'eval_config.yaml').read_text()==(WORKING_DIR/'agents/baseline/eval_config.yaml').read_text()
assert (ranker_dir/'configs/sampling.yaml').read_text()==(WORKING_DIR/'agents/baseline/configs/sampling.yaml').read_text()
(WORKING_DIR/'ranker-integration-manifest.json').write_text(json.dumps(EXPECTED_PACKAGE,indent=2))
print('Full ranker attached; matched model/sampling/time/tool budgets; no reference labels in skill.')
'''
    if args.ranker_only:install+="PAYLOADS.pop('baseline')\n"
    # Insert after materialization but before vLLM startup.
    serving_index=next(i for i,c in enumerate(notebook['cells']) if c['cell_type']=='code' and 'vllm_cfg = VllmConfig(' in ''.join(c['source']))
    notebook['cells'].insert(serving_index,cell('code',install))
    evaluation_index=next(i for i,c in enumerate(notebook['cells']) if c['cell_type']=='code' and 'for ARM in PAYLOADS:' in ''.join(c['source']))
    eval_source=''.join(notebook['cells'][evaluation_index]['source'])
    eval_source=eval_source.replace('SAMPLE_TASKS = selected_tasks','SAMPLE_TASKS = [task for task in tasks if task.instance_id in '+repr(args.task_ids)+']')
    if args.batch:
        from tools.build_main_track_batch import batch_evaluation_code
        eval_source=batch_evaluation_code(args.task_ids,args.concurrency,args.display)
    notebook['cells'][evaluation_index]=cell('code',eval_source)
    notebook['cells'][0]=cell('markdown','# Full ranker agent integration\n\nExecutable full-ranker evaluation; the run manifest specifies whether a control arm is included. The ranker is an INT8 deployment variant trained excluding competition repositories. Actual tool invocation, query fidelity, ranker output and repair tests must be audited. Development tasks only; not an untouched confirmation test or leaderboard score.\n')
    args.out.mkdir(parents=True)
    for name,text in baseline.items():
        target=args.out/'baseline'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text,encoding='utf-8')
    manifest={'model':MODEL,'split':split,'engineering_task_ids':args.task_ids,'engineering_task_id':args.task_ids[0],
              'ranker_asset_dataset':DATASET,'ranker_asset_zip_sha256':package['zip_sha256'],
              'arms':{'baseline':{'files':{name:hashlib.sha256(text.encode()).hexdigest() for name,text in baseline.items()}},
                      'ranker':{'files':runtime_files}},
              'scope':'Development integration of compact full ranker, not original paper estimator',
              'fairness':'Same model, sampling, '+str(args.max_time_minutes)+'min/30-tool limits and 120s command timeout; ranker computation consumes session time'}
    manifest['workflow']='sequential' if args.staged else 'single_agent'
    manifest['result_file']='batch-results.jsonl' if args.batch else 'smoke_results.jsonl'
    manifest['max_time_minutes']=args.max_time_minutes
    manifest['display_mode']=args.display
    if args.staged and args.locator_thinking_budget is not None:
        manifest['locator_thinking_budget']=args.locator_thinking_budget
        manifest['fairness']+=('; the locator stage alone uses '+str(args.locator_thinking_budget)+
                               ' thinking tokens because it emits a single tool call, while the repair stage and the '
                               'control arm keep the baseline sampling')

    manifest['concurrency']=args.concurrency if args.batch else 1
    if args.ranker_only:
        manifest['arms'].pop('baseline')
        manifest['scope']+='; ranker-only integration probe, no contemporaneous baseline'
    (args.out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (args.out/'integration.ipynb').write_text(json.dumps(notebook,indent=2),encoding='utf-8')
    req={'newTitle':'Gemma4 ranker '+args.suffix,'slug':'gemma4-ranker-'+args.suffix,
         'text':json.dumps(notebook),'language':'python','kernelType':'notebook','isPrivate':True,'enableGpu':True,'enableInternet':False,
         'enableTpu':False,'machineShape':starter['metadata']['machineShape'],'sessionTimeoutSeconds':3600,
         'dockerImage':starter['metadata']['dockerImage'],'dockerImagePinningType':'original',
         'datasetDataSources':starter['metadata']['datasetDataSources']+[DATASET],
         'competitionDataSources':['gemma-4-developer-agent'],
         'kernelDataSources':['yyyyhhhhwww/gemma4-requests-test-wheels-20261108-v2','yyyyhhhhwww/gemma4-fastapi-test-wheels-20261108'],
         'modelDataSources':['google/gemma-4/Other/'+MODEL+'/2']}
    (args.out/'kernel-request.json').write_text(json.dumps(req),encoding='utf-8')
    print('Prepared ranker evaluation:',args.task_ids,'arms',list(manifest['arms']),'request bytes',(args.out/'kernel-request.json').stat().st_size)
if __name__=='__main__':main()
