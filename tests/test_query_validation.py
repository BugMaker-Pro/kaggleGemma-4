import argparse
import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from experiments.buildgraph import build_graph
from experiments.query_pilot import TaskInput,canonical
from experiments.feedback_pilot import paired_requests
from experiments.query_validation_anchor import rebuild_anchor
from experiments.strong_query_features import candidate_features
from tools.run_query_validation import generated_pool,generate
from tools.run_flash_replication import select_tasks,validate_generated
from tools.run_simple_fusion import simple_pool


class QueryValidationTests(unittest.TestCase):
    def test_rebuild_never_opens_gold_and_reproduces_feature_extension(self):
        files={'core.py':'def convert(x):\n    """Convert timezone."""\n    return x\n','other.py':'def unrelated():\n    return 1\n'}
        graph,_=build_graph(files)
        with patch('builtins.open',side_effect=AssertionError('No IO allowed')):
            anchor=rebuild_anchor('convert timezone',files,graph)
            rows,audit=candidate_features('convert timezone',files,graph,anchor,anchor['ids'])
        self.assertEqual(rows,anchor['rows'])
        self.assertEqual(set(anchor),{'ids','rows','files'})
        self.assertEqual(audit['existing_rows_verified'],len(anchor['ids']))

    def test_empty_issue_anchor_is_valid(self):
        files={'core.py':'def run():\n    return 1\n'}
        graph,_=build_graph(files)
        self.assertEqual(rebuild_anchor('',files,graph),{'ids':[],'rows':[],'files':[]})

    def test_generation_failure_returns_exact_control_copy(self):
        simple=['a','b'];original=[{'id':'c','score':1}]
        for status in ('transport_unknown','invalid_output'):
            result=generated_pool(original,[],{'status':status},simple)
            self.assertEqual(result,simple);self.assertIsNot(result,simple)
        with self.assertRaises(ValueError):generated_pool(original,[],{'status':'ok'},simple)

    def test_success_matches_fixed_rrf(self):
        original=[{'id':'a','score':1}]
        actions=[{'candidates':[{'id':'b','score':1}]},{'candidates':[{'id':'b','score':1}]}]
        self.assertEqual(generated_pool(original,actions,{'status':'ok'},['a']),['b','a'])

    def test_missing_history_is_not_used_to_resample(self):
        tasks=[{'instance_id':str(i),'repo':'o/r','base_commit':'abc','problem_statement':'issue'} for i in range(8)]
        selected=select_tasks(tasks,{'0'},5,2026110303)
        self.assertEqual(len(selected),5)
        self.assertNotIn('0',{r['instance_id'] for r in selected})
        self.assertEqual(selected,select_tasks(tasks[::-1],{'0'},5,2026110303))

    def test_single_arm_api_transport_failure_has_no_retry(self):
        request=paired_requests(TaskInput('task','o/r','abc','timezone'),[])[0]
        seal={'schedule':[request['request_sha256']]}
        manifest={'manifest_sha256':'frozen','budget_cny':4,'failure_policy':{'consecutive_transport_stop':3}}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);args=argparse.Namespace(run_dir=path,env_file=path/'.env')
            with patch('tools.run_query_validation.load_inputs',return_value=(manifest,[],[request],seal)),patch('tools.run_query_validation.load_key',return_value='fixture-secret'),patch('urllib.request.build_opener') as network,contextlib.redirect_stdout(io.StringIO()):
                network.return_value.open.side_effect=urllib.error.URLError('fixture')
                generate(args)
                self.assertEqual(network.return_value.open.call_count,1)
                with self.assertRaises(FileExistsError):generate(args)
            (path/'inputs.seal.json').write_text(canonical(seal),encoding='utf-8')
            rows=validate_generated(path,manifest,[request])
            self.assertEqual(rows[0]['status'],'transport_unknown')
            self.assertIsNone(rows[0]['input_tokens'])
            self.assertEqual(generated_pool([],[],rows[0],['control']),['control'])
            for f in path.rglob('*.json*'):self.assertNotIn('fixture-secret',f.read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main()
