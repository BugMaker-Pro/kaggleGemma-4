import json,math,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agent/ranker/scripts'))
from tree_predict import ensemble_scores
from localize import source_files,dense_documents
from localization_features import candidate_features
from experiments.buildgraph import build_graph

class PortableRankerTests(unittest.TestCase):
    def test_trace_distinguishes_real_ranker_output_from_tool_presence(self):
        from tools.audit_main_track import summarize_trace
        result={'status':'ok','mode':'full','query_sha256':'abc','results':[]}
        trace={'steps':[{'tool_calls':[{'function_name':'run_skill_script','arguments':{'skill_name':'ranker','file_path':'scripts/localize.py','args':{'issue':'original'}}}],
                        'observation':{'content':json.dumps({'skill_name':'ranker','stdout':json.dumps(result)})}}]}
        summary=summarize_trace(trace)
        self.assertEqual(len(summary['ranker_calls']),1)
        self.assertEqual(summary['ranker_outputs'][0]['query_sha256'],'abc')
        self.assertEqual(summarize_trace({'steps':[]})['ranker_outputs'],[])

    def test_full_integration_requires_call_and_matching_original_issue(self):
        import hashlib
        from tools.audit_ranker_agent import ranker_evidence
        issue='Title\n\nOriginal\r\nproblem'
        query=issue.replace('\r\n','\n')
        call={'script':'scripts/localize.py','args':{'mode':'full','issue':query}}
        output={'status':'ok','mode':'full','candidate_count':200,
                'query_sha256':hashlib.sha256(query.encode()).hexdigest(),'results':[{}]*10}
        details={'ranker_calls':[call],'ranker_outputs':[output]}
        report=ranker_evidence(details,issue)
        self.assertTrue(report['full_pipeline_executed_with_original_issue'])
        self.assertEqual(report['exact_original_issue_full_ranker_invocations'],0)
        self.assertFalse(ranker_evidence({'ranker_calls':[],'ranker_outputs':[output]},issue)['full_pipeline_executed_with_original_issue'])
        self.assertFalse(ranker_evidence(details,issue+' changed')['full_pipeline_executed_with_original_issue'])
        call['args']['issue']=query+'\n'
        output['query_sha256']=hashlib.sha256((query+'\n').encode()).hexdigest()
        adjusted=ranker_evidence(details,issue)
        self.assertTrue(adjusted['full_pipeline_executed_with_text_equivalent_issue'])
        self.assertFalse(adjusted['full_pipeline_executed_with_original_issue'])
        self.assertFalse(ranker_evidence(details,issue+' changed')['full_pipeline_executed_with_text_equivalent_issue'])
        output['status']='error'
        self.assertFalse(ranker_evidence(details,issue)['full_pipeline_executed_with_original_issue'])

    def test_staged_locator_cannot_edit_and_hands_output_to_repair(self):
        import yaml
        from tools.build_ranker_agent_probe import staged_overrides,MODEL
        sampling='temperature: 0.2\ntop_p: 0.95\nthinking_config:\n  thinking_budget: 4096\n  include_thoughts: true\n'
        base={'agent.yaml':'name: matched_repair_agent\nmodel: '+MODEL+'\ntools: [read_file, edit_file]\n',
              'prompts/system.md':'Repair the original issue.','configs/sampling.yaml':sampling,
              'eval_config.yaml':'evaluation:\n  max_time_minutes: 5\n'}
        files=staged_overrides(base,1024)
        root=yaml.safe_load(files['agent.yaml'])
        self.assertEqual(root['agent_class'],'SequentialAgent')
        self.assertEqual([a['config_path'] for a in root['sub_agents']],['ranker_stage.yaml','repair_stage.yaml'])
        class Loader(yaml.SafeLoader):pass
        Loader.add_constructor('!include',lambda loader,node:loader.construct_scalar(node))
        locator=yaml.load(files['ranker_stage.yaml'],Loader=Loader)
        repair=yaml.safe_load(files['repair_stage.yaml'])
        self.assertEqual(locator['tools'],[])
        self.assertEqual(locator['skills'],['skills/ranker'])
        self.assertEqual(locator['model'],repair['model'])
        self.assertEqual(locator['output_key'],'localization_report')
        self.assertEqual(locator['generate_content_config'],'configs/locator_sampling.yaml')
        self.assertIn('thinking_budget: 1024',files['configs/locator_sampling.yaml'])
        self.assertIn('thinking_budget: 4096',base['configs/sampling.yaml'])
        self.assertIn('max_time_minutes: 5',files['eval_config.yaml'])
        self.assertEqual(files['configs/sampling.yaml'],sampling)
        shared=staged_overrides(base,None)
        self.assertNotIn('configs/locator_sampling.yaml',shared)
        self.assertIn('configs/sampling.yaml',shared['ranker_stage.yaml'])
        default_files=staged_overrides(base)
        self.assertNotIn('configs/locator_sampling.yaml',default_files)
        self.assertIn('configs/sampling.yaml',default_files['ranker_stage.yaml'])
        self.assertIn('{problem_description}',files['prompts/localize.md'])
        self.assertIn('execute the full ranker once',files['prompts/localize.md'])
        self.assertIn('finish this stage immediately',files['prompts/localize.md'])
        self.assertIn('Do not call list_skills, load_skill or load_skill_resource',files['prompts/localize.md'])
        self.assertNotIn('sibling',files['prompts/localize.md'])
        self.assertNotIn('{localization_report}',files['prompts/system.md'])
        self.assertIn('already in this conversation',files['prompts/system.md'])

    def test_comparison_rejects_changed_budget_or_partial_selection(self):
        from tools.compare_ranker_development import matched_settings
        with tempfile.TemporaryDirectory() as directory:
            ranker=Path(directory)/'ranker';control=Path(directory)/'control'
            ranker.mkdir();control.mkdir()
            common={'model':'same','split':{'development':['task_1'],'confirmation':['task_2']},
                    'engineering_task_ids':['task_1'],'concurrency':2}
            files={'configs/sampling.yaml':'same_sampling','eval_config.yaml':'same_budget'}
            rm={**common,'ranker_asset_dataset':'weights','arms':{'ranker':{'files':files}}}
            cm={**common,'arms':{'evidence':{'files':dict(files)}}}
            (ranker/'manifest.json').write_text(json.dumps(rm))
            (control/'manifest.json').write_text(json.dumps(cm))
            (ranker/'kernel-request.json').write_text(json.dumps({'datasetDataSources':['base','weights']}))
            (control/'kernel-request.json').write_text(json.dumps({'datasetDataSources':['base']}))
            for root in (ranker,control):
                (root/'verification-gate-task_1.json').write_text(json.dumps({'passed':True}))
            self.assertEqual(matched_settings(ranker,control)['tasks'],1)
            cm['arms']['evidence']['files']['eval_config.yaml']='different_timeout'
            (control/'manifest.json').write_text(json.dumps(cm))
            with self.assertRaisesRegex(ValueError,'budgets differ'):matched_settings(ranker,control)
            cm['engineering_task_ids']=[]
            (control/'manifest.json').write_text(json.dumps(cm))
            with self.assertRaisesRegex(ValueError,'entire same frozen'):matched_settings(ranker,control)

    def test_tree_threshold_and_missing_branch(self):
        tree={'split_feature':0,'threshold':1.0,'decision_type':'<=','default_left':False,'missing_type':'NaN',
              'left_child':{'leaf_value':-2},'right_child':{'leaf_value':3}}
        model={'max_feature_idx':0,'tree_info':[{'tree_structure':tree}]}
        self.assertEqual(ensemble_scores([model],[[1],[1.1],[float('nan')]]),[-2,3,3])
        with self.assertRaisesRegex(ValueError,'width'):ensemble_scores([model],[[1,2]])

    def test_compressed_tree_container_is_lossless(self):
        import base64,zlib
        from tree_predict import load_ranker
        model={'max_feature_idx':0,'tree_info':[{'tree_structure':{'leaf_value':1.25}}]}
        raw=json.dumps({'models':[model]}).encode()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'ranker.json'
            path.write_text(json.dumps({'format':'zlib-json-v1','payload':base64.b85encode(zlib.compress(raw)).decode()}))
            self.assertEqual(load_ranker(path),[model])
            self.assertEqual(ensemble_scores(load_ranker(path),[[3]]),[1.25])

    def test_agent_probe_dev_only_flag_restores_the_ten_task_cap(self):
        from tools.build_ranker_agent_probe import main
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'probe'
            with patch('tools.build_ranker_agent_probe.freeze_split',return_value={'development':['dev'],'confirmation':['confirm']}):
                # Default now accepts all 129 frozen official tasks; --dev-only
                # is the opt-in way to restore the old 10-task restriction.
                with self.assertRaisesRegex(ValueError,'unique frozen official'):
                    main(['--task-ids','confirm','--out',str(output),'--dev-only'])
            self.assertFalse(output.exists())

    def test_source_scan_excludes_executor_and_dependency_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'module.py').write_text('def target():\n    return 1\n')
            (root/'.adk_exec_123.py').write_text('raise RuntimeError("must not parse")')
            (root/'.venv').mkdir();(root/'.venv/dep.py').write_text('def other(): pass')
            files=source_files(root)
            self.assertEqual(set(files),{'module.py'})

    def test_runtime_features_accept_no_label_or_task_object(self):
        files={'module.py':'def add(a, b):\n    """Add values."""\n    return a + b\n\ndef wrapper(a):\n    return add(a, 1)\n'}
        graph,_=build_graph(files)
        actual=candidate_features('add returns wrong value',files,graph)
        self.assertEqual(set(actual),{'ids','rows','files'})
        self.assertTrue(actual['ids'])
        self.assertTrue(all(len(row)==16 for row in actual['rows']))
        docs=dense_documents(actual['ids'],actual['files'],files)
        self.assertEqual(len(docs),len(actual['ids']))
        self.assertTrue(any('return a + b' in doc for doc in docs))

    def test_full_mode_does_not_silently_fall_back(self):
        from localize import rank
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'module.py').write_text('def target():\n    return 1\n')
            with patch('dense_encoder.dense_scores',side_effect=ImportError('no dense runtime')):
                with self.assertRaisesRegex(ImportError,'no dense runtime'):
                    rank('target returns incorrect value',root,root/'missing_assets','full')

if __name__=='__main__':unittest.main()
