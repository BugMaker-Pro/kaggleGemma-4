"""Build matched competition agents and a private Kaggle smoke notebook.

Uses downloaded official artifacts. Never reads reference patch/test_patch values.
The generated notebook executes the official harness; local checks are packaging
checks, not claims that the harness or the model has run.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import re
import textwrap
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = 'gemma-4-12b-it-qat-w4a16-ct'
SEED = 'main-track-20261108-v1'
ARMS = ('baseline', 'evidence', 'evidence_graph')
TOOLS = ('run_command', 'read_file', 'edit_file', 'write_file', 'get_status',
         'submit_patch', 'get_code_neighbors', 'search_similar_code', 'get_code_subgraph')

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def freeze_split(path: Path) -> dict:
    groups = defaultdict(list)
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if line.strip():
            raw = json.loads(line)
            groups[raw['repo']].append(raw['instance_id'])
    ids = [item for group in groups.values() for item in group]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate task IDs')
    rank = lambda value: digest((SEED + ':' + value).encode())
    development, confirmation = [], []
    for repo in sorted(groups):
        ordered = sorted(groups[repo], key=rank)
        # Single-task repositories belong to engineering development only.
        count = min(3, len(ordered))
        development.extend(ordered[:count])
        confirmation.extend(ordered[count:])
    smoke_repo = 'psf/requests' if 'psf/requests' in groups else sorted(groups)[0]
    smoke_id = sorted(groups[smoke_repo], key=rank)[0]
    return {'schema_version': 1, 'seed': SEED, 'task_file_sha256': digest(path.read_bytes()),
            'selection_fields': ['repo', 'instance_id'], 'development': development,
            'confirmation': confirmation, 'smoke_task_id': smoke_id,
            'repo_counts': {repo: len(values) for repo, values in sorted(groups.items())},
            'confirmation_is_external_benchmark': False,
            'small_repo_note': 'Repositories with <=3 tasks have no confirmation tasks.'}

def agent_files(sample: Path, arm: str, *, completion_guardrails: bool = False, max_output_tokens: int | None = None,
                max_time_minutes: int = 3, max_tool_calls: int = 30, max_turns: int = 50) -> dict[str, str]:
    prompt = (sample / 'prompts/system.md').read_text(encoding='utf-8')
    if arm != 'baseline':
        policy = (ROOT / 'agent/prompts/localization' / (arm + '.md')).read_text(encoding='utf-8')
        prompt, count = re.subn(r'### 1\. Identify Target Files Immediately\n.*?(?=### 2\.)',
                               lambda _: '### 1. Locate using issue evidence\n\n' + policy + '\n',
                               prompt, count=1, flags=re.S)
        if count != 1:
            raise ValueError('official prompt structure changed')
    if completion_guardrails:
        prompt = prompt.rstrip() + '\n\n' + (ROOT / 'agent/prompts/completion.md').read_text(encoding='utf-8-sig')
    config = ('name: matched_repair_agent\nmodel: ' + MODEL + '\n'
              'instruction: !include prompts/system.md\ntools:\n' +
              ''.join('  - ' + tool + '\n' for tool in TOOLS) +
              'generate_content_config: !include configs/sampling.yaml\n')
    sampling = (sample / 'configs/sampling.yaml').read_text(encoding='utf-8')
    if max_output_tokens is not None:
        if max_output_tokens not in (8192, 16384):
            raise ValueError('Supported output reservations are 8192 and 16384')
        sampling, changed = re.subn(r'^max_output_tokens:\s*\d+\s*$',
                                    'max_output_tokens: ' + str(max_output_tokens), sampling, flags=re.M)
        if changed != 1:
            raise ValueError('Official sampling config must declare exactly one output reservation')
    sampling += '\nseed: 0\n'
    eval_config = ('evaluation:\n  timeout_seconds: 60\n  max_tool_calls: ' + str(max_tool_calls) + '\n'
                   '  max_time_minutes: ' + str(max_time_minutes) + '\n  max_turns: ' + str(max_turns) + '\n')
    return {'agent.yaml': config, 'prompts/system.md': prompt,
            'configs/sampling.yaml': sampling,
            'eval_config.yaml': eval_config}

def make_zip(files: dict[str, str], path: Path):
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, text in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 11, 8, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, text.encode())

def cell(kind: str, source: str) -> dict:
    result = {'id': digest(source.encode())[:12], 'cell_type': kind, 'metadata': {}, 'source': source.splitlines(keepends=True)}
    if kind == 'code':
        ast.parse(source)
        result.update(execution_count=None, outputs=[])
    return result

TEST_DEPENDENCY_SETUP = "import importlib.metadata as md, json, os, subprocess, sys\nfrom pathlib import Path\nmatches=list(Path('/kaggle/input').rglob('dependency-manifest.json'))\nassert len(matches)==1, f'Expected one dependency manifest: {matches}'\nextra_root=matches[0].parent/'request-test-wheels'\nmanifest=json.loads(matches[0].read_text())\nimport hashlib\nfor item in manifest:\n    assert hashlib.sha256((extra_root/item['name']).read_bytes()).hexdigest()==item['sha256']\npytest_before=md.version('pytest')\nconstraints=Path('/tmp/verification-pytest-constraint.txt')\nconstraints.write_text('pytest=='+pytest_before+'\\n')\nsubprocess.run([sys.executable,'-m','pip','install','--no-index','--find-links',str(extra_root),\n               '--constraint',str(constraints),'pytest-httpbin==2.1.0'],check=True)\nassert md.version('pytest')==pytest_before, 'Verification must preserve official pytest version'\nplugins=[{'name':ep.name,'value':ep.value} for ep in md.entry_points(group='pytest11')]\nassert any('httpbin' in ep['value'] for ep in plugins),plugins\nPath('/kaggle/working/environment-repair.json').write_text(json.dumps({\n    'pytest_version':pytest_before,'pytest_httpbin_version':md.version('pytest-httpbin'),\n    'plugins':plugins,'wheel_manifest':manifest,\n    'scope':'Offline local verification dependency repair; official verifier and test files unchanged'},indent=2))\nprint('Test plugin installed offline; unchanged pytest:',pytest_before)\n"


SOURCE_LAYOUT_SETUP = "# Correct only local subprocess import-path setup for src-layout repositories.\n# Official subprocess setup skips editable installation and dependency setup.\nimport json, os, subprocess\nfrom pathlib import Path\nimport swegemma.sandbox.subprocess as sandbox_module\noriginal_environment_builder=sandbox_module.build_sanitized_env\nimport_probes=[]\nprobed_workspaces=set()\ndef source_environment(work_dir,tmp_dir=None,extra_env=None):\n    environment=original_environment_builder(work_dir,tmp_dir,extra_env)\n    source=Path(work_dir)/'src'\n    if source.is_dir():\n        previous=environment.get('PYTHONPATH','')\n        environment['PYTHONPATH']=str(source)+(os.pathsep+previous if previous else '')\n        key=str(Path(work_dir).resolve())\n        if (source/'requests/__init__.py').exists() and key not in probed_workspaces:\n            python_path=str(Path(environment['VIRTUAL_ENV'])/'bin/python3')\n            probe=subprocess.run([python_path,'-s','-c','import requests; print(requests.__file__)'],\n                cwd=work_dir,env=environment,capture_output=True,text=True,check=True)\n            actual=Path(probe.stdout.strip()).resolve()\n            assert actual.is_relative_to(source.resolve()), f'Wrong source module: {actual}'\n            import_probes.append({'workspace':key,'module_path':str(actual),'src_path_added':str(source)})\n            Path('/kaggle/working/source-import-probes.json').write_text(json.dumps(import_probes,indent=2))\n            probed_workspaces.add(key)\n    return environment\nsandbox_module.build_sanitized_env=source_environment\nprint('Local src-layout import correction enabled; test files and verifier unchanged.')\n"


ADDITIONAL_TEST_DEPENDENCY_SETUP = "# additional_test_dependency: real FastAPI test assertion library, installed offline.\nimport hashlib, importlib.metadata as md, json, subprocess, sys\nfrom pathlib import Path\nextra_manifests=list(Path('/kaggle/input').rglob('fastapi-dependency-manifest.json'))\nassert len(extra_manifests)==1,extra_manifests\nextra_manifest=json.loads(extra_manifests[0].read_text())\nextra_wheels=extra_manifests[0].parent/'fastapi-test-wheels'\nfor item in extra_manifest:\n    assert hashlib.sha256((extra_wheels/item['name']).read_bytes()).hexdigest()==item['sha256']\nsubprocess.run([sys.executable,'-m','pip','install','--no-index','--no-deps',\n               '--find-links',str(extra_wheels),'dirty-equals==0.11'],check=True)\nPath('/kaggle/working/additional-test-dependency.json').write_text(json.dumps({\n    'dirty_equals_version':md.version('dirty-equals'),'wheel_manifest':extra_manifest,\n    'scope':'Test assertion library only; no test/score modifications'},indent=2))\nprint('Installed real FastAPI test dependency offline:',md.version('dirty-equals'))\n"


def make_notebook(starter: dict, payloads: dict, split: dict, *, repair_test_dependencies: bool = False, engineering_task_id: str | None = None, repair_source_layout: bool = False, additional_test_dependency: bool = False) -> dict:
    original = json.loads(starter['blob']['source'])
    source = lambda index: ''.join(original['cells'][index]['source'])
    setup = source(2)
    materialize = '''import hashlib
import json
import re
from adk_submission import validate_directory
from swegemma.config import build_submission_limits
from swegemma.models import load_tasks

DATA_DIR = Path('/kaggle/input/competitions/gemma-4-developer-agent')
WORKING_DIR = Path('/kaggle/working')
TASKS_PATH = DATA_DIR / 'tasks.jsonl'
GRAPH_DIR = str(DATA_DIR / 'graphs')
EMBEDDINGS_DIR = str(DATA_DIR / 'embeddings')
'''
    materialize += 'PAYLOADS = json.loads(' + repr(json.dumps(payloads)) + ')\n'
    materialize += 'SPLIT = json.loads(' + repr(json.dumps(split)) + ')\n'
    materialize += 'ENGINEERING_TASK_ID = ' + repr(engineering_task_id or split['smoke_task_id']) + '\n'
    materialize += '''assert hashlib.sha256(TASKS_PATH.read_bytes()).hexdigest() == SPLIT['task_file_sha256'], 'Official tasks changed; rebuild split before running'
limits, gen_constraints = build_submission_limits()
for arm, files in PAYLOADS.items():
    directory = WORKING_DIR / 'agents' / arm
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
    validate_directory(directory, limits=limits)
    print('Official structure validation passed:', arm)
tasks = load_tasks(TASKS_PATH)
selected_tasks = [task for task in tasks if task.instance_id == ENGINEERING_TASK_ID]
assert len(selected_tasks) == 1 and selected_tasks[0].instance_id in (set(SPLIT['development'])|set(SPLIT.get('confirmation',[])))
AGENT_DIR = WORKING_DIR / 'agents' / next(iter(PAYLOADS))
(WORKING_DIR / 'frozen_split.json').write_text(json.dumps(SPLIT, indent=2), encoding='utf-8')
print('Engineering smoke only; task:', ENGINEERING_TASK_ID)
'''
    serving = source(8)
    evaluation = source(10).replace('SAMPLE_TASKS = tasks[:2]', 'SAMPLE_TASKS = selected_tasks')
    evaluation = 'from swegemma.results import append_task_result\n' + evaluation
    evaluation = evaluation.replace("results_dir=WORKING_DIR / 'results',", "results_dir=WORKING_DIR / 'results' / ARM,")
    evaluation = evaluation.replace("    patch = (result.agent_patch or '').strip()", '''    append_task_result(result, eval_config.results_dir, [result])
    record = {'arm': ARM, 'task_id': task.instance_id, 'resolved': result.resolved,
              'test_exit_code': result.test_exit_code, 'tool_calls': result.tool_calls,
              'duration_seconds': result.duration_seconds,
              'patch_sha256': hashlib.sha256((result.agent_patch or '').encode()).hexdigest(),
              'patch_chars': len(result.agent_patch or ''), 'purpose': 'engineering_smoke'}
    with (WORKING_DIR / 'smoke_results.jsonl').open('a', encoding='utf-8') as result_file:
        result_file.write(json.dumps(record) + '\\n')
    patch = (result.agent_patch or '').strip()''')
    evaluation = "try:\n    for ARM in PAYLOADS:\n        AGENT_DIR = WORKING_DIR / 'agents' / ARM\n" + textwrap.indent(evaluation, '        ') + '\nfinally:\n    server_instance.stop()\n'
    packaging = '''import zipfile
for arm, files in PAYLOADS.items():
    archive_path = WORKING_DIR / (arm + '_submission.zip')
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.write(WORKING_DIR / 'agents' / arm / name, name)
    print('Prepared archive:', archive_path.name)
'''
    return {'nbformat': 4, 'nbformat_minor': 5,
            'metadata': {'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'}},
            'cells': [cell('markdown', '# Gemma main-track engineering smoke\n\nThree matched 12B single-agent configurations, one frozen development task. This is not a method-effectiveness estimate. Based on the official Getting Started notebook v3; dummy adapters and the AgentTool delegate are omitted in all arms.\n'),
                      cell('code', setup), *([cell('code', TEST_DEPENDENCY_SETUP)] if repair_test_dependencies else []), *([cell('code', SOURCE_LAYOUT_SETUP)] if repair_source_layout else []), *([cell('code', ADDITIONAL_TEST_DEPENDENCY_SETUP)] if additional_test_dependency else []), cell('code', materialize), cell('code', serving),
                      cell('code', evaluation), cell('code', packaging)]}

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--official', type=Path, default=ROOT / '.cache/main-track/official')
    parser.add_argument('--starter', type=Path, default=ROOT / '.cache/main-track/official-starter.json')
    parser.add_argument('--run-suffix', default='v2')
    parser.add_argument('--completion-guardrails', action='store_true')
    parser.add_argument('--max-output-tokens', type=int, choices=(8192,16384))
    parser.add_argument('--additional-test-dependency-kernel')
    parser.add_argument('--src-layout-repair', action='store_true', help='Explicit local subprocess environment correction, not a submission patch')
    parser.add_argument('--engineering-task-id', help='Must belong to the existing frozen development split')
    parser.add_argument('--test-dependency-kernel', help='Completed wheel-preparation notebook; evaluation remains offline')
    parser.add_argument('--out', type=Path, default=ROOT / '.cache/main-track/build')
    args = parser.parse_args(argv)
    if (args.out / 'kernel-launch.json').exists():
        raise ValueError('Refusing to overwrite an already launched run directory')
    split = freeze_split(args.official / 'tasks.jsonl')
    engineering_task = args.engineering_task_id or split['smoke_task_id']
    if engineering_task not in split['development'] or engineering_task in split['confirmation']:
        raise ValueError('Engineering task must belong exclusively to the frozen development split')
    payloads = {arm: agent_files(args.official / 'sample_submission', arm, completion_guardrails=args.completion_guardrails, max_output_tokens=args.max_output_tokens) for arm in ARMS}
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = {'model': MODEL, 'arms': {}, 'status': 'prepared_not_executed',
                'completion_guardrails': args.completion_guardrails,
                'max_output_tokens_override': args.max_output_tokens,
                'engineering_task_id': engineering_task,
                'src_layout_repair': args.src_layout_repair,
                'baseline': 'Official root prompt; matched single-agent configuration, no adapters, 3min/30-tool budget.',
                'harness_sha256': digest((args.official / 'HARNESS_README.md').read_bytes()),
                'split': split}
    for arm, files in payloads.items():
        for name, content in files.items():
            target = args.out / arm / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
        package = args.out / (arm + '_submission.zip')
        make_zip(files, package)
        manifest['arms'][arm] = {'zip_sha256': digest(package.read_bytes()),
                                'files': {name: digest(text.encode()) for name, text in files.items()}}
    starter = json.loads(args.starter.read_text(encoding='utf-8-sig'))
    notebook = make_notebook(starter, payloads, split, repair_test_dependencies=bool(args.test_dependency_kernel), engineering_task_id=engineering_task, repair_source_layout=args.src_layout_repair, additional_test_dependency=bool(args.additional_test_dependency_kernel))
    (args.out / 'smoke.ipynb').write_text(json.dumps(notebook, indent=2), encoding='utf-8')
    manifest['test_dependency_kernel'] = args.test_dependency_kernel
    manifest['additional_test_dependency_kernel'] = args.additional_test_dependency_kernel
    manifest['notebook_sha256'] = digest((args.out / 'smoke.ipynb').read_bytes())
    (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    metadata = {'newTitle': 'Gemma4 localization smoke 20261108 ' + args.run_suffix,
                'slug': 'gemma4-localization-smoke-20261108-' + args.run_suffix,
                'text': json.dumps(notebook), 'language': 'python', 'kernelType': 'notebook',
                'isPrivate': True, 'enableGpu': True, 'enableInternet': False,
                'enableTpu': False, 'machineShape': starter['metadata']['machineShape'],
                'sessionTimeoutSeconds': 3600,
                'dockerImage': starter['metadata']['dockerImage'],
                'dockerImagePinningType': 'original',
                'datasetDataSources': starter['metadata']['datasetDataSources'],
                'competitionDataSources': ['gemma-4-developer-agent'],
                'kernelDataSources': [source for source in (args.test_dependency_kernel,args.additional_test_dependency_kernel) if source],
                'modelDataSources': ['google/gemma-4/Other/' + MODEL + '/2']}
    (args.out / 'kernel-request.json').write_text(json.dumps(metadata), encoding='utf-8')
    print(json.dumps({'output': str(args.out), 'development': len(split['development']),
                      'confirmation': len(split['confirmation']), 'smoke_task': engineering_task,
                      'arms': list(payloads)}, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
