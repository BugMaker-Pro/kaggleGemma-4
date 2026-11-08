import copy
import unittest
import tests.test_deepseek_feedback as fixtures
from tools.continue_deepseek_feedback import unknown_response, validate_responses
from tools.run_deepseek_feedback import decode_response


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.DeepSeekFeedbackTests(); fixture.setUp()
        self.requests,self.m,self.raw=fixture.requests,fixture.m,fixture.raw

    def test_unknown_usage_stays_unknown_and_falls_back(self):
        rows=[decode_response(self.raw,self.requests[0],self.m,1),unknown_response(self.requests[1],self.m)]
        validate_responses(rows,self.requests,self.m)
        self.assertIsNone(rows[1]['input_tokens'])
        self.assertEqual(rows[1]['queries'],[])
        rows[1]['input_tokens']=0
        with self.assertRaises(ValueError):validate_responses(rows,self.requests,self.m)

    def test_unknown_usage_reserves_budget(self):
        rows=[unknown_response(r,self.m) for r in self.requests]
        with self.assertRaises(ValueError):validate_responses(rows,self.requests,{**self.m,'budget_cny':0})


if __name__=='__main__':unittest.main()
