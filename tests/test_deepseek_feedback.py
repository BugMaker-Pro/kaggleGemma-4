"""Offline API adapter tests: never contact DeepSeek."""
import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.feedback_pilot import paired_requests
from experiments.query_pilot import TaskInput
from tools.run_deepseek_feedback import (API_CONFIG, NoRedirect, decode_response, generate, load_key,
                                        reserve_cost, usage_cost, validate_responses)
import urllib.error


class DeepSeekFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.requests=paired_requests(TaskInput("task","o/r","abc","timezone conversion"),[])
        self.m={"manifest_sha256":"frozen","model_sha256":"api","budget_cny":5}
        self.raw={"id":"test","model":"deepseek-flash","choices":[{"finish_reason":"stop","message":{
            "content":'{"queries":["timezone conversion","convert offset"]}'}}],
            "usage":{"prompt_tokens":100,"completion_tokens":20,"prompt_cache_hit_tokens":40,"prompt_cache_miss_tokens":60}}

    def test_env_reader_accepts_alias_quotes_and_never_interpolates(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{},clear=True):
            path=Path(folder)/".env"
            path.write_text('# comment\nAPI_KEY="fixture-credential"\n',encoding="utf-8-sig")
            self.assertEqual(load_key(path),"fixture-credential")
            path.write_text('export DEEPSEEK_API_KEY=fixture-value # comment\n',encoding="utf-8")
            self.assertEqual(load_key(path),"fixture-value")
            path.write_text('API_KEY=secret with spaces\n',encoding="utf-8")
            with self.assertRaises(ValueError) as ctx: load_key(path)
            self.assertNotIn("secret",str(ctx.exception))

    def test_cost_counts_cache_and_completion(self):
        self.assertAlmostEqual(usage_cost(self.raw["usage"],"idle"),(40*.02+60+20*4)/1e6)
        self.assertAlmostEqual(usage_cost(self.raw["usage"],"peak"),2*usage_cost(self.raw["usage"],"idle"))
        bad={**self.raw["usage"],"prompt_cache_miss_tokens":99}
        with self.assertRaises(ValueError): usage_cost(bad,"idle")
        self.assertGreater(reserve_cost(self.requests[0]),0)

    def test_success_and_usage_validation(self):
        rows=[decode_response(self.raw,r,self.m,1.0) for r in self.requests]
        validate_responses(rows,self.requests,self.m)
        rows[0]["queries"]=["changed","target"]
        with self.assertRaises(ValueError): validate_responses(rows,self.requests,self.m)

    def test_invalid_output_falls_back_without_repair(self):
        for content,finish in [('not json','stop'),('{"queries":["x","y"]}','length')]:
            raw={**self.raw,"choices":[{"finish_reason":finish,"message":{"content":content}}]}
            row=decode_response(raw,self.requests[0],self.m,1)
            self.assertEqual(row["status"],"invalid_output")
            self.assertEqual(row["queries"],[])

    def test_reasoning_missing_usage_and_over_budget_fail(self):
        raw={**self.raw,"choices":[{"finish_reason":"stop","message":{"content":"{}","reasoning_content":"thinking"}}]}
        with self.assertRaises(ValueError): decode_response(raw,self.requests[0],self.m,1)
        for usage in ({},{"prompt_tokens":8193,"completion_tokens":20},{"prompt_tokens":100,"completion_tokens":257}):
            with self.assertRaises(ValueError): decode_response({**self.raw,"usage":usage},self.requests[0],self.m,1)

    def test_redirect_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError):
            NoRedirect().redirect_request(type('R',(),{'full_url':'https://api.deepseek.com/chat/completions'})(),None,302,'moved',{},'https://other.example')

    def test_uncertain_request_never_resent(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'receipts').mkdir()
            (root/'receipts/000.started.json').write_text('{}',encoding='utf-8')
            args=argparse.Namespace(run_dir=root,env_file=root/'.env')
            with patch('tools.run_deepseek_feedback.load_run',return_value=(self.m,self.requests,[])),patch('tools.run_deepseek_feedback.load_key',return_value='fixture-key'),patch('urllib.request.build_opener') as network:
                with self.assertRaisesRegex(RuntimeError,'uncertain'): generate(args)
                network.return_value.open.assert_not_called()

    def test_mocked_generation_is_bounded_and_receipts_have_no_secret(self):
        class Reply:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(inner): return json.dumps(self.raw).encode()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            args=argparse.Namespace(run_dir=root,env_file=root/'.env')
            with patch('tools.run_deepseek_feedback.load_run',return_value=(self.m,self.requests,[])),patch('tools.run_deepseek_feedback.load_key',return_value='fixture-secret'),patch('urllib.request.build_opener') as network,contextlib.redirect_stdout(io.StringIO()):
                network.return_value.open.return_value=Reply()
                generate(args)
                self.assertEqual(network.return_value.open.call_count,2)
                sent=json.loads(network.return_value.open.call_args[0][0].data)
                self.assertEqual(sent['thinking'],{'type':'disabled'})
                self.assertEqual(sent['max_tokens'],256)
                self.assertEqual(sent['model'],'deepseek-flash')
                with self.assertRaises(FileExistsError): generate(args)
            for file in root.rglob('*.json*'):
                self.assertNotIn('fixture-secret',file.read_text(encoding='utf-8'))


if __name__=='__main__': unittest.main()
