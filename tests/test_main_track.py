import json
import tempfile
import unittest
from pathlib import Path
from tools.build_main_track import freeze_split, agent_files

class MainTrackPreparationTests(unittest.TestCase):
    def test_single_evidence_arm_materializes_valid_model_discovery_directory(self):
        import hashlib,sys,types
        from unittest.mock import patch
        from tools.build_main_track import make_notebook
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);inputs=root/'input';working=root/'working'
            inputs.mkdir();working.mkdir()
            tasks=inputs/'tasks.jsonl';tasks.write_text('{}')
            split={'smoke_task_id':'task_1','development':['task_1'],
                   'task_file_sha256':hashlib.sha256(tasks.read_bytes()).hexdigest()}
            starter={'blob':{'source':json.dumps({'cells':[{'source':'pass\n'} for _ in range(11)]})}}
            notebook=make_notebook(starter,{'evidence':{'agent.yaml':'name: evidence\n'}},split)
            code=next(''.join(c['source']) for c in notebook['cells'] if 'PAYLOADS = ' in ''.join(c['source']))
            code=code.replace('/kaggle/input/competitions/gemma-4-developer-agent',inputs.as_posix()).replace('/kaggle/working',working.as_posix())
            adk=types.ModuleType('adk_submission')
            adk.validate_directory=lambda path,**kwargs:self.assertTrue((path/'agent.yaml').is_file())
            swe=types.ModuleType('swegemma')
            config=types.ModuleType('swegemma.config');config.build_submission_limits=lambda:(None,None)
            models=types.ModuleType('swegemma.models');models.load_tasks=lambda path:[types.SimpleNamespace(instance_id='task_1')]
            namespace={'Path':Path,'print':lambda *args:None}
            with patch.dict(sys.modules,{'adk_submission':adk,'swegemma':swe,'swegemma.config':config,'swegemma.models':models}):
                exec(compile(code,'notebook_materialization','exec'),namespace)
            self.assertEqual(namespace['AGENT_DIR'],working/'agents'/'evidence')
            self.assertTrue(namespace['AGENT_DIR'].is_dir())

    def test_selection_does_not_use_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tasks.jsonl'
            rows = [{'repo': 'a/repo', 'instance_id': f'a_{i}', 'patch': f'gold-{i}', 'test_patch': 'tests'} for i in range(7)]
            path.write_text('\n'.join(map(json.dumps, rows)), encoding='utf-8')
            first = freeze_split(path)
            for row in rows:
                row['patch'], row['test_patch'] = 'different answer', 'different tests'
            path.write_text('\n'.join(map(json.dumps, reversed(rows))), encoding='utf-8')
            second = freeze_split(path)
            for key in ('development', 'confirmation', 'smoke_task_id'):
                self.assertEqual(first[key], second[key])
            self.assertFalse(set(first['development']) & set(first['confirmation']))
            self.assertEqual(set(first['development']) | set(first['confirmation']), {row['instance_id'] for row in rows})

    def test_duplicate_tasks_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tasks.jsonl'
            row = json.dumps({'repo': 'a/repo', 'instance_id': 'same'})
            path.write_text(row + '\n' + row, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                freeze_split(path)

    def test_engineering_cli_rejects_confirmation_task(self):
        from tools.build_main_track import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            official = root / 'official'
            official.mkdir()
            rows = [{'repo': 'repo/one', 'instance_id': f'task_{i}'} for i in range(6)]
            tasks = official / 'tasks.jsonl'
            tasks.write_text('\n'.join(map(json.dumps, rows)), encoding='utf-8')
            confirmation = freeze_split(tasks)['confirmation'][0]
            with self.assertRaisesRegex(ValueError, 'Engineering task must belong'):
                main(['--official', str(official), '--out', str(root/'build'), '--engineering-task-id', confirmation])
            self.assertFalse((root/'build').exists())

    def test_small_repository_is_not_claimed_as_holdout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tasks.jsonl'
            path.write_text(json.dumps({'repo': 'one/repo', 'instance_id': 'only'}), encoding='utf-8')
            split = freeze_split(path)
            self.assertEqual(split['development'], ['only'])
            self.assertEqual(split['confirmation'], [])

    def test_only_localization_prompt_differs_between_arms(self):
        with tempfile.TemporaryDirectory() as directory:
            sample = Path(directory)
            (sample / 'prompts').mkdir()
            (sample / 'configs').mkdir()
            prompt = 'Shared preamble\n### 1. Identify Target Files Immediately\nOriginal localization\n### 2. Implement\nProtected edit and verification workflow\n'
            (sample / 'prompts/system.md').write_text(prompt, encoding='utf-8')
            (sample / 'configs/sampling.yaml').write_text('temperature: 0.2\n', encoding='utf-8')
            arms = [agent_files(sample, name) for name in ('baseline','evidence','evidence_graph')]
            for files in arms[1:]:
                for name in ('agent.yaml','eval_config.yaml','configs/sampling.yaml'):
                    self.assertEqual(files[name], arms[0][name])
                self.assertEqual(files['prompts/system.md'].split('### 2.')[1], prompt.split('### 2.')[1])
            self.assertNotIn('adapter:', arms[0]['agent.yaml'])
            self.assertNotIn('agent_tool:', arms[0]['agent.yaml'])


class CompletionGuardrailTests(unittest.TestCase):
    def test_common_finish_instructions_do_not_change_model_or_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            sample = Path(directory)
            (sample / 'prompts').mkdir()
            (sample / 'configs').mkdir()
            (sample / 'prompts/system.md').write_text('Shared\n### 1. Identify Target Files Immediately\nLocate\n### 2. Implement\nShared ending\n', encoding='utf-8')
            (sample / 'configs/sampling.yaml').write_text('temperature: 0.2\n', encoding='utf-8')
            endings = []
            for arm in ('baseline', 'evidence', 'evidence_graph'):
                original = agent_files(sample, arm)
                revised = agent_files(sample, arm, completion_guardrails=True)
                for name in ('agent.yaml', 'eval_config.yaml', 'configs/sampling.yaml'):
                    self.assertEqual(original[name], revised[name])
                self.assertTrue(revised['prompts/system.md'].startswith(original['prompts/system.md'].rstrip()))
                endings.append(revised['prompts/system.md'][len(original['prompts/system.md'].rstrip()):])
            self.assertEqual(endings[0], endings[1])
            self.assertEqual(endings[1], endings[2])
            self.assertNotIn('requests_7433', endings[0])


class ContextReservationTests(unittest.TestCase):
    def test_reduced_output_reservation_is_matched_across_arms(self):
        import yaml
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'prompts').mkdir()
            (root/'configs').mkdir()
            (root/'prompts/system.md').write_text('### 1. Identify Target Files Immediately\nLocate\n### 2. Implement\nFix\n')
            (root/'configs/sampling.yaml').write_text('temperature: 0.2\nmax_output_tokens: 16384\nthinking_config:\n  thinking_budget: 4096\n')
            reservations = []
            for arm in ('baseline', 'evidence', 'evidence_graph'):
                files = agent_files(root, arm, max_output_tokens=8192)
                config = yaml.safe_load(files['configs/sampling.yaml'])
                self.assertEqual(config['max_output_tokens'], 8192)
                self.assertEqual(config['thinking_config']['thinking_budget'], 4096)
                reservations.append(config)
            self.assertEqual(reservations[0], reservations[1])
            self.assertEqual(reservations[1], reservations[2])


class RuntimeArtifactAuditTests(unittest.TestCase):
    def _make_run(self, root):
        import hashlib, zipfile
        split = {'smoke_task_id': 'task_1', 'development': ['task_1'], 'confirmation': ['task_2']}
        content = 'Prompt with Unicode: \u2014\n'
        fingerprint = hashlib.sha256(content.encode()).hexdigest()
        (root / 'manifest.json').write_text(json.dumps({'split': split, 'arms': {'baseline': {'files': {'prompts/system.md': fingerprint}}}}), encoding='utf-8')
        output = root / 'output'
        prompt = output / 'agents/baseline/prompts/system.md'
        prompt.parent.mkdir(parents=True)
        prompt.write_bytes(content.encode())
        (output / 'frozen_split.json').write_text(json.dumps(split), encoding='utf-8')
        (output / 'smoke_results.jsonl').write_text(json.dumps({'arm': 'baseline', 'task_id': 'task_1', 'resolved': False}), encoding='utf-8')
        with zipfile.ZipFile(output / 'baseline_submission.zip', 'w') as archive:
            archive.writestr('prompts/system.md', content.encode())
        traces = output / 'results/baseline/traces'
        traces.mkdir(parents=True)
        (traces / 'trace_task_1.json').write_text(json.dumps({'steps': [{'source': 'system', 'message': content.rstrip()}], 'final_metrics': {}}), encoding='utf-8')
        return prompt

    def test_missing_diagnostics_are_disclosed_not_invented(self):
        from tools.audit_main_track import audit_run
        with tempfile.TemporaryDirectory() as directory:
            self._make_run(Path(directory))
            row = audit_run(Path(directory))['arms'][0]
            self.assertFalse(row['full_patch_saved'])
            self.assertFalse(row['verification_log_saved'])
            self.assertEqual(row['graph_calls'], 0)
            self.assertIsNone(row['first_edit_elapsed_seconds'])

    def test_changed_runtime_prompt_is_rejected(self):
        from tools.audit_main_track import audit_run
        with tempfile.TemporaryDirectory() as directory:
            prompt = self._make_run(Path(directory))
            prompt.write_text('Different prompt', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Runtime agent file differs'):
                audit_run(Path(directory))

    def test_confirmation_task_cannot_be_relabelled_as_smoke(self):
        from tools.audit_main_track import audit_run
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._make_run(root)
            path = root / 'output/frozen_split.json'
            split = json.loads(path.read_text())
            split['smoke_task_id'] = 'task_2'
            path.write_text(json.dumps(split))
            with self.assertRaisesRegex(ValueError, 'Frozen task split differs'):
                audit_run(root)

class DevelopmentBatchAuditTests(unittest.TestCase):
    def test_missing_arm_results_are_rejected(self):
        from tools.audit_main_track import audit_development_batch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'output').mkdir()
            split={'development':['dev_1'],'confirmation':['confirm_1']}
            manifest={'engineering_task_ids':['dev_1'],'split':split,'arms':{'baseline':{},'evidence':{}}}
            (root/'manifest.json').write_text(json.dumps(manifest))
            (root/'output/frozen_split.json').write_text(json.dumps(split))
            (root/'output/batch-results.jsonl').write_text(json.dumps({'arm':'baseline','task_id':'dev_1'}))
            with self.assertRaisesRegex(ValueError,'Missing or duplicated'):
                audit_development_batch(root)


class VerificationGateTests(unittest.TestCase):
    def test_only_reference_pass_and_empty_fail_allow_progress(self):
        from tools.audit_main_track import audit_verification
        for empty_resolved, reference_resolved, expected in ((False, True, True), (False, False, False), (True, True, False)):
            with self.subTest(empty=empty_resolved, reference=reference_resolved), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                rows = []
                for arm, resolved in (('empty_control', empty_resolved), ('reference_control', reference_resolved)):
                    record = {'arm': arm, 'task_id': 'task_1', 'resolved': resolved, 'test_exit_code': 0 if resolved else 1}
                    rows.append(record)
                    result_dir = root/'output/results'/arm
                    (result_dir/'test_outputs').mkdir(parents=True)
                    (result_dir/'test_outputs/task_1.log').write_text('real output', encoding='utf-8')
                    (result_dir/'task_results.jsonl').write_text(json.dumps(record), encoding='utf-8')
                (root/'output/verification_results.jsonl').write_text('\n'.join(map(json.dumps, rows)), encoding='utf-8')
                setup = 'WHEELHOUSE_DIR = Path("official")'
                notebook = {'cells': [{'cell_type': 'code', 'source': [setup]}]}
                request = {'text': json.dumps(notebook), 'enableInternet': False}
                (root/'kernel-request.json').write_text(json.dumps(request), encoding='utf-8')
                gate = audit_verification(root)
                self.assertEqual(gate['passed'], expected)
                self.assertEqual(len(gate['environment_setup_sha256']), 1)


class BatchPreparationTests(unittest.TestCase):
    def test_preflight_rejects_confirmation_tasks_without_writing_outputs(self):
        from unittest.mock import patch
        from tools.build_main_track_preflight import main
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'preflight'
            split = {'development': ['dev_1'], 'confirmation': ['confirm_1']}
            with patch('tools.build_main_track_preflight.freeze_split', return_value=split):
                with self.assertRaisesRegex(ValueError, 'frozen development'):
                    main(['--task-ids','confirm_1','--out',str(output),'--run-suffix','test'])
            self.assertFalse(output.exists())

    def test_batch_refuses_confirmation_task(self):
        from unittest.mock import patch
        from tools.build_main_track_batch import main
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'batch'
            split={'development':['dev_1'],'confirmation':['confirm_1']}
            with patch('tools.build_main_track_batch.freeze_split',return_value=split):
                with self.assertRaisesRegex(ValueError,'frozen development'):
                    main(['--task-ids','confirm_1','--out',str(output),'--run-suffix','test'])
            self.assertFalse(output.exists())

    def test_throughput_needs_two_distinct_development_tasks(self):
        from unittest.mock import patch
        from tools.build_main_track_throughput import main
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'throughput'
            split = {'development': ['dev_1','dev_2'], 'confirmation': ['confirm_1']}
            with patch('tools.build_main_track_throughput.freeze_split', return_value=split):
                for task_ids in (['dev_1','dev_1'], ['dev_1','confirm_1']):
                    with self.assertRaisesRegex(ValueError, 'distinct frozen development'):
                        main(['--task-ids',*task_ids,'--out',str(output),'--run-suffix','test'])
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
