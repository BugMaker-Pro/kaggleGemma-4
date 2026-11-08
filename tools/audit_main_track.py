"""Audit downloaded main-track artifacts and summarize observable tool behavior."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path

GRAPH_TOOLS = {'get_code_neighbors', 'get_code_subgraph'}

def summarize_trace(trace: dict) -> dict:
    calls = [(step, call) for step in trace['steps'] for call in step.get('tool_calls', [])]
    first_edit = next((call.get('extra', {}).get('elapsed_s') for _, call in calls
                       if call.get('function_name') == 'edit_file'), None)
    errors = Counter()
    scratch = set()
    for step, call in calls:
        arguments = call.get('arguments', {})
        if call.get('function_name') == 'write_file':
            path = arguments.get('filepath', '')
            if path.endswith('.py') and '/' not in path:
                scratch.add(path)
        command = arguments.get('command', '')
        if isinstance(command, str):
            scratch.update(re.findall(r'>\s*([\w.-]+\.py)\b', command))
    for step in trace['steps']:
        observation = step.get('observation') or {}
        if not isinstance(observation, dict):
            continue
        try:
            value = json.loads(observation.get('content', '{}'))
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and value.get('status') == 'error':
            errors[value.get('error_type', 'unknown')] += 1
    tools = Counter(call['function_name'] for _, call in calls)
    ranker_calls=[]
    for step, call in calls:
        args=call.get('arguments', {})
        if call.get('function_name')=='run_skill_script' and args.get('skill_name')=='ranker':
            ranker_calls.append({'script':args.get('file_path'),'args':args.get('args'),
                                 'elapsed_seconds':call.get('extra',{}).get('elapsed_s')})
    ranker_outputs=[]
    for step in trace['steps']:
        observation=step.get('observation') or {}
        if not isinstance(observation,dict):continue
        content=observation.get('content','')
        try:value=json.loads(content)
        except (ValueError,TypeError):continue
        if not isinstance(value,dict) or value.get('skill_name')!='ranker':continue
        for line in (value.get('stdout') or '').splitlines():
            try:result=json.loads(line)
            except ValueError:continue
            if isinstance(result,dict) and result.get('mode') in ('full','lexical'):
                ranker_outputs.append(result)
    return {'ranker_calls':ranker_calls,'ranker_outputs':ranker_outputs,
            'tool_invocations_including_rejected_and_free': dict(tools),
            'graph_calls': sum(tools[name] for name in GRAPH_TOOLS),
            'first_edit_elapsed_seconds': first_edit,
            'explicit_submit': tools['submit_patch'] > 0,
            'workspace_scratch_files_observed': sorted(scratch),
            'tool_errors': dict(errors), 'model_usage_from_trace': trace.get('final_metrics', {})}

def audit_run(directory: Path) -> dict:
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8-sig'))
    output = directory/'output'
    actual_split = json.loads((output/'frozen_split.json').read_text(encoding='utf-8-sig'))
    if actual_split != manifest['split']:
        raise ValueError('Frozen task split differs from prepared manifest')
    task_id = manifest.get('engineering_task_id', actual_split['smoke_task_id'])
    if task_id not in actual_split['development'] or task_id in actual_split['confirmation']:
        raise ValueError('Smoke task is not exclusively in development')
    rows = [json.loads(line) for line in (output/'smoke_results.jsonl').read_text(encoding='utf-8').splitlines() if line]
    if len(rows) != len(manifest['arms']) or {r['arm'] for r in rows} != set(manifest['arms']):
        raise ValueError('Incomplete or duplicated arm population')
    checks = 0
    summaries = []
    for row in rows:
        arm = row['arm']
        if row['task_id'] != task_id or not isinstance(row['resolved'], bool):
            raise ValueError('Unexpected task ID or resolution type')
        with zipfile.ZipFile(output/(arm+'_submission.zip')) as archive:
            if set(archive.namelist()) != set(manifest['arms'][arm]['files']):
                raise ValueError('Runtime package file set differs')
            for name, expected in manifest['arms'][arm]['files'].items():
                saved = output/'agents'/arm/name
                if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                    raise ValueError(f'Runtime ZIP differs: {arm}/{name}')
                if hashlib.sha256(saved.read_bytes()).hexdigest() != expected:
                    raise ValueError(f'Runtime agent file differs: {arm}/{name}')
                checks += 2
        trace_path = output/'results'/arm/'traces'/('trace_'+task_id+'.json')
        trace = json.loads(trace_path.read_text(encoding='utf-8'))
        instruction = (output/'agents'/arm/'prompts/system.md').read_text(encoding='utf-8')
        if trace['steps'][0].get('message', '').rstrip('\r\n') != instruction.rstrip('\r\n'):
            raise ValueError(f'Trace system instruction differs: {arm}')
        summary = dict(row)
        summary.update(summarize_trace(trace))
        summary['full_patch_saved'] = (output/'results'/arm/'patches'/(task_id+'.patch')).is_file()
        summary['verification_log_saved'] = (output/'results'/arm/'test_outputs'/(task_id+'.log')).is_file()
        summary['empty_patch_recorded'] = row.get('patch_chars') == 0
        if summary['full_patch_saved']:
            patch_bytes = (output/'results'/arm/'patches'/(task_id+'.patch')).read_bytes()
            if hashlib.sha256(patch_bytes).hexdigest() != row['patch_sha256']:
                raise ValueError(f'Saved patch differs from result hash: {arm}')
            checks += 1
        task_result_path = output/'results'/arm/'task_results.jsonl'
        if task_result_path.is_file():
            task_results = [json.loads(line) for line in task_result_path.read_text(encoding='utf-8').splitlines() if line]
            if len(task_results) != 1 or task_results[0]['resolved'] != row['resolved'] or task_results[0]['test_exit_code'] != row['test_exit_code']:
                raise ValueError(f'Raw task result differs from smoke summary: {arm}')
            summary['harness_error'] = task_results[0].get('error')
            checks += 1
        summaries.append(summary)
        checks += 1
    return {'purpose': 'engineering_smoke_not_confirmation', 'task_id': task_id,
            'checks': checks, 'arms': summaries,
            'interpretation_limit': 'One development task cannot establish method effectiveness; missing verification logs prevent attributing unresolved outcomes.'}

def audit_development_batch(directory: Path) -> dict:
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    output=directory/'output'
    split=json.loads((output/'frozen_split.json').read_text(encoding='utf-8'))
    ids=set(manifest['engineering_task_ids'])
    if split!=manifest['split'] or not ids<=set(split['development']) or ids&set(split['confirmation']):
        raise ValueError('Batch split or task selection differs')
    rows=[json.loads(line) for line in (output/'batch-results.jsonl').read_text(encoding='utf-8').splitlines() if line]
    expected={(arm,task_id) for arm in manifest['arms'] for task_id in ids}
    actual={(row['arm'],row['task_id']) for row in rows}
    if len(rows)!=len(actual) or actual!=expected:
        raise ValueError('Missing or duplicated development task/arm results')
    checks=0
    for arm,definition in manifest['arms'].items():
        with zipfile.ZipFile(output/(arm+'_submission.zip')) as archive:
            if set(archive.namelist())!=set(definition['files']):raise ValueError('Batch package files differ')
            for name,digest in definition['files'].items():
                if hashlib.sha256(archive.read(name)).hexdigest()!=digest:raise ValueError('Batch ZIP hash differs')
                if hashlib.sha256((output/'agents'/arm/name).read_bytes()).hexdigest()!=digest:raise ValueError('Batch agent file differs')
                checks+=2
        raw_rows=[json.loads(line) for line in (output/'results'/arm/'task_results.jsonl').read_text(encoding='utf-8').splitlines() if line]
        if len(raw_rows)!=len(ids) or {r['instance_id'] for r in raw_rows}!=ids:raise ValueError('Raw batch results incomplete')
        raw={r['instance_id']:r for r in raw_rows}
        for row in [r for r in rows if r['arm']==arm]:
            original=raw[row['task_id']]
            for metric in ('resolved','test_exit_code','tool_calls'):
                if original[metric]!=row[metric]:raise ValueError('Batch summary disagrees with task result')
                checks+=1
            patch=output/'results'/arm/'patches'/(row['task_id']+'.patch')
            content=patch.read_bytes() if patch.exists() else b''
            if hashlib.sha256(content).hexdigest()!=row['patch_sha256'] or len(content.decode())!=row['patch_chars']:
                raise ValueError('Full patch differs or is missing')
            if row['resolved'] and not (output/'results'/arm/'test_outputs'/(row['task_id']+'.log')).is_file():
                raise ValueError('Resolved result lacks verification output')
            trace_path=output/'results'/arm/'traces'/('trace_'+row['task_id']+'.json')
            if trace_path.exists():
                trace=json.loads(trace_path.read_text(encoding='utf-8'))
                instruction=(output/'agents'/arm/'prompts/system.md').read_text(encoding='utf-8')
                if trace['steps'][0].get('message','').rstrip()!=instruction.rstrip():raise ValueError('Batch trace prompt differs')
                row['trace_summary']=summarize_trace(trace)
            elif not row.get('error'):
                raise ValueError('Missing trace without recorded error')
            checks+=1
    summary={arm:{'tasks':len(ids),'resolved':sum(bool(r['resolved']) for r in rows if r['arm']==arm),
                  'recorded_errors':sum(bool(r.get('error')) for r in rows if r['arm']==arm)} for arm in manifest['arms']}
    return {'passed':True,'checks':checks,'scope':'Development batch only; not a confirmatory performance estimate',
            'arms':summary,'results':rows}


def audit_verification(directory: Path, task_id: str | None = None) -> dict:
    output = directory / 'output'
    path = output / 'verification_results.jsonl'
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]
    if task_id is not None:
        rows = [row for row in rows if row['task_id'] == task_id]
    controls = {row['arm']: row for row in rows}
    if len(controls) != len(rows) or not {'empty_control', 'reference_control'} <= controls.keys():
        raise ValueError('Incomplete or duplicated verification controls')
    task_ids = {row['task_id'] for row in rows}
    if len(task_ids) != 1:
        raise ValueError('Verification controls use different tasks')
    task_id = next(iter(task_ids))
    result_root = output / 'results' / task_id if (output / 'results' / task_id).is_dir() else output / 'results'
    reports = {}
    for arm in ('empty_control', 'reference_control'):
        row = controls[arm]
        log = result_root / arm / 'test_outputs' / (task_id + '.log')
        saved = result_root / arm / 'task_results.jsonl'
        records = [json.loads(line) for line in saved.read_text(encoding='utf-8').splitlines() if line]
        if len(records) != 1 or records[0]['resolved'] != row['resolved'] or records[0]['test_exit_code'] != row['test_exit_code']:
            raise ValueError('Verification summary differs from saved task result')
        if not log.is_file() or not log.stat().st_size:
            raise ValueError('Missing verification test output')
        reports[arm] = {'resolved': row['resolved'], 'test_exit_code': row['test_exit_code'],
                        'test_output_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
    passed = (controls['reference_control']['resolved'] is True
              and controls['reference_control']['test_exit_code'] == 0
              and controls['empty_control']['resolved'] is False
              and controls['empty_control']['test_exit_code'] > 0)
    request = json.loads((directory / 'kernel-request.json').read_text(encoding='utf-8'))
    environment = {key: request.get(key) for key in
                   ('dockerImage', 'datasetDataSources', 'competitionDataSources', 'kernelDataSources', 'enableInternet')}
    notebook = json.loads(request['text'])
    setup_markers = ('WHEELHOUSE_DIR = Path(', 'pytest_before=md.version', 'original_environment_builder=', 'additional_test_dependency:')
    setup_hashes = []
    for cell in notebook['cells']:
        source = ''.join(cell.get('source', []))
        if cell['cell_type'] == 'code' and any(marker in source for marker in setup_markers):
            setup_hashes.append(hashlib.sha256(source.encode()).hexdigest())
    return {'task_id': task_id, 'passed': passed, 'controls': reports,
            'environment': environment, 'environment_setup_sha256': setup_hashes,
            'source_results_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'scope': 'Expected reference-pass/empty-fail controls only; not a method-effectiveness result'}


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--run-dir', type=Path)
    group.add_argument('--verification-dir', type=Path)
    group.add_argument('--batch-dir', type=Path)
    parser.add_argument('--verification-task-id', help='Select one complete pair from a development batch')
    args = parser.parse_args()
    if args.batch_dir:
        report=audit_development_batch(args.batch_dir)
        (args.batch_dir/'audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({'passed':report['passed'],'checks':report['checks'],'arms':report['arms']}))
        return
    if args.verification_dir:
        gate = audit_verification(args.verification_dir, args.verification_task_id)
        gate_name = 'verification-gate.json' if args.verification_task_id is None else 'verification-gate-' + gate['task_id'].replace('/', '_') + '.json'
        (args.verification_dir / gate_name).write_text(json.dumps(gate, indent=2), encoding='utf-8')
        print(f"Verification gate: task={gate['task_id']}; passed={gate['passed']}")
        return
    report = audit_run(args.run_dir)
    target = args.run_dir/'audit.json'
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"{report['checks']} artifact checks passed; task {report['task_id']}")
    for row in report['arms']:
        first_edit = row['first_edit_elapsed_seconds']
        edit_text = f'{first_edit:.1f}s' if first_edit is not None else 'none'
        print(f"{row['arm']}: resolved={row['resolved']}; tools={row['tool_calls']}; "
              f"graph_calls={row['graph_calls']}; first_edit={edit_text}; "
              f"explicit_submit={row['explicit_submit']}; verification_log={row['verification_log_saved']}")
    print('Engineering smoke only; no effectiveness claim.')

if __name__ == '__main__':
    main()
