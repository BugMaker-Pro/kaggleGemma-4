"""Offline prospective replication tests, including transport failure asymmetry."""
import argparse
import contextlib
import copy
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from experiments.feedback_pilot import paired_requests
from experiments.query_pilot import TaskInput,canonical,digest
from tools.run_flash_replication import (ARMS, API_CONFIG, charged_or_reserved, cluster_interval,
                                        effective_pair, generate, schedule_requests, select_tasks,
                                        summarize_rows, validate_generated, prepare, inputs, retrieve, evaluate)


class FlashReplicationTests(unittest.TestCase):
    def test_selection_excludes_previous_ids_and_is_patch_independent(self):
        rows=[{'instance_id':f'{repo}-{i}','repo':repo,'base_commit':'abc','problem_statement':'issue','patch':'secret'}
              for repo in ('o/a','o/b') for i in range(5)]
        chosen=select_tasks(rows,{'o/a-0','o/b-1'},per_repo=3)
        self.assertEqual(len(chosen),6)
        self.assertFalse({r['instance_id'] for r in chosen}&{'o/a-0','o/b-1'})
        self.assertTrue(all(set(r)=={'instance_id','repo','base_commit','problem_statement'} for r in chosen))
        for row in rows:row['patch']='different';row['gold']='target'
        self.assertEqual(chosen,select_tasks(list(reversed(rows)),{'o/a-0','o/b-1'},per_repo=3))

    def test_sampling_all_remaining_in_small_repository(self):
        rows=[{'instance_id':str(i),'repo':'o/r','base_commit':'abc','problem_statement':'issue'} for i in range(3)]
        self.assertEqual(len(select_tasks(rows,{'0'},per_repo=3)),2)
        with self.assertRaises(ValueError):select_tasks(rows+rows,{},per_repo=3)

    def test_hash_schedule_is_stable_and_preserves_all_requests(self):
        requests=[r for i in range(20) for r in paired_requests(TaskInput(str(i),'o/r','abc','issue'),[])]
        scheduled=schedule_requests(requests)
        self.assertEqual(scheduled,schedule_requests(requests))
        self.assertEqual(set(scheduled),{r['request_sha256'] for r in requests})
        self.assertEqual(len(scheduled),len(set(scheduled)))
        by_id={r['request_sha256']:r['arm'] for r in requests}
        self.assertEqual({by_id[scheduled[i]] for i in range(0,len(scheduled),2)},set(ARMS))

    def test_paired_fallback_removes_asymmetric_false_improvement(self):
        rows=[{'arm':'preplanned','status':'ok','queries':['query','code']},
              {'arm':'feedback','status':'transport_unknown','queries':[]}]
        untouched=copy.deepcopy(rows)
        effective=effective_pair(rows)
        self.assertTrue(all(r['queries']==[] and r['status']=='paired_fallback' for r in effective))
        self.assertEqual(rows,untouched)
        rows[1]={'arm':'feedback','status':'invalid_output','queries':[]}
        self.assertTrue(all(not r['queries'] for r in effective_pair(rows)))
        with self.assertRaises(ValueError):effective_pair(rows[::-1])

    def test_valid_pair_keeps_both_queries(self):
        rows=[{'arm':arm,'status':'ok','queries':['one','two']} for arm in ARMS]
        self.assertEqual(effective_pair(rows),rows)

    def test_repository_interval_keeps_within_repo_tasks_clustered(self):
        rows=[{'instance_id':f'r{i}','repo':'o/a','arms':{'preplanned':{'recall_at_10':0,'coverage':1},'feedback':{'recall_at_10':1,'coverage':1}}} for i in range(3)]
        self.assertIsNone(cluster_interval(rows))
        rows.append({'instance_id':'s','repo':'o/b','arms':{'preplanned':{'recall_at_10':0,'coverage':1},'feedback':{'recall_at_10':0,'coverage':1}}})
        summary=summarize_rows(rows)
        self.assertEqual(summary['primary_delta'],.75)
        self.assertEqual(cluster_interval(rows,n=100),[0.0,1.0])
        self.assertEqual(summarize_rows([]),{'tasks':0})

    def fixture(self):
        requests=paired_requests(TaskInput('task','o/r','abc','timezone conversion'),[])
        m={'manifest_sha256':'frozen','budget_cny':4.9,'failure_policy':{'consecutive_transport_stop':3}}
        seal={'schedule':schedule_requests(requests)}
        raw={'model':'deepseek-flash','id':'fixture','choices':[{'finish_reason':'stop','message':{
            'content':'{"queries":["timezone conversion","offset handling"]}'}}],
             'usage':{'prompt_tokens':100,'completion_tokens':15}}
        return m,requests,seal,raw

    def test_transport_failure_not_retried_and_responses_keep_null_usage(self):
        m,requests,seal,raw=self.fixture()
        class Reply:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps(raw).encode()
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)
            args=argparse.Namespace(run_dir=directory,env_file=directory/'.env')
            with patch('tools.run_flash_replication.load_inputs',return_value=(m,[],requests,seal)),patch('tools.run_flash_replication.load_key',return_value='fixture-secret'),patch('urllib.request.build_opener') as network,contextlib.redirect_stdout(io.StringIO()):
                network.return_value.open.side_effect=[urllib.error.URLError('fixture'),Reply()]
                generate(args)
                self.assertEqual(network.return_value.open.call_count,2)
                with self.assertRaises(FileExistsError):generate(args)
            (directory/'inputs.seal.json').write_text(canonical(seal),encoding='utf-8')
            rows=validate_generated(directory,m,requests)
            self.assertEqual(sum(r['status']=='transport_unknown' for r in rows),1)
            unknown=next(r for r in rows if r['status']=='transport_unknown')
            self.assertIsNone(unknown['input_tokens'])
            self.assertGreater(charged_or_reserved(unknown),0)
            self.assertTrue(all(not r['queries'] for r in effective_pair(rows)))
            for file in directory.rglob('*.json*'):self.assertNotIn('fixture-secret',file.read_text(encoding='utf-8'))

    def test_started_request_without_receipt_is_never_sent_again(self):
        m,requests,seal,_=self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder);(directory/'receipts').mkdir()
            (directory/'receipts/000.started.json').write_text('{}',encoding='utf-8')
            args=argparse.Namespace(run_dir=directory,env_file=directory/'.env')
            with patch('tools.run_flash_replication.load_inputs',return_value=(m,[],requests,seal)),patch('tools.run_flash_replication.load_key',return_value='fixture-secret'),patch('urllib.request.build_opener') as network:
                with self.assertRaisesRegex(RuntimeError,'active'):generate(args)
                network.return_value.open.assert_not_called()


    def test_all_stages_with_synthetic_snapshots_and_one_failed_request(self):
        class Reply:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps({'id':'fixture','model':'deepseek-flash',
                'choices':[{'finish_reason':'stop','message':{'content':'{"queries":["convert timezone","offset value"]}'}}],
                'usage':{'prompt_tokens':100,'completion_tokens':20}}).encode()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);pilot=root/'pilot';pilot.mkdir();repos=root/'repos';repos.mkdir()
            (pilot/'manifest.json').write_text(canonical({'task_ids':['excluded']}),encoding='utf-8')
            (pilot/'sensitivity.json').write_text(canonical({'known_peak_plus_unknown_reservation_cny':.1}),encoding='utf-8')
            tasks=[]
            for i in range(4):
                tid=f'task-{i}';snapshot=repos/tid;snapshot.mkdir()
                (snapshot/'core.py').write_text('def convert(value):\n    """Convert timezone offset."""\n    return value\n',encoding='utf-8')
                tasks.append({'instance_id':tid,'repo':f'o/r{i//2}','base_commit':'abc','problem_statement':'convert timezone offset','patch':'NEVER_EXPOSE_PATCH'})
            (root/'raw.jsonl').write_text(''.join(canonical(t)+'\n' for t in tasks),encoding='utf-8')
            args=argparse.Namespace(run_dir=root/'run',pilot=pilot,tasks=root/'raw.jsonl',repos=repos,env_file=root/'.env',gold=root/'gold.jsonl')
            with contextlib.redirect_stdout(io.StringIO()),patch('tools.run_flash_replication.load_key',return_value='fixture-secret'):
                prepare(args);inputs(args)
                with patch('urllib.request.build_opener') as network:
                    network.return_value.open.side_effect=[urllib.error.URLError('fixture')]+[Reply() for _ in range(7)]
                    generate(args)
                    self.assertEqual(network.return_value.open.call_count,8)
                retrieve(args)
                self.assertFalse(args.gold.exists())
                gold=[{'instance_id':t['instance_id'],'repo':t['repo'],'base_commit':'abc',
                       'files':[{'path':'core.py','language':'python','symbols':[{'qualname':'convert'}]}]} for t in tasks]
                args.gold.write_text(''.join(canonical(r)+'\n' for r in gold),encoding='utf-8')
                evaluate(args)
            summary=json.loads((args.run_dir/'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['scorable_tasks'],4)
            self.assertEqual(len(summary['paired_fallback_tasks']),1)
            self.assertEqual(summary['complete_pair_sensitivity']['tasks'],3)
            self.assertEqual(summary['primary']['primary_delta'],0)
            self.assertEqual(summary['prior_plus_current_peak_reservation_cny'],.1+summary['peak_plus_unknown_reservation_cny'])
            for file in args.run_dir.rglob('*.json*'):
                value=file.read_text(encoding='utf-8')
                self.assertNotIn('NEVER_EXPOSE_PATCH',value)
                self.assertNotIn('fixture-secret',value)


if __name__=='__main__':unittest.main()
