"""Fixed cheap-fusion tests: no gold, API, GPU, or retraining in replay."""
import copy
import unittest
from unittest.mock import patch

from tools.run_simple_fusion import simple_pool,replay_task,score_task,interval


class SimpleFusionTests(unittest.TestCase):
    def fixture(self):
        candidate={'instance_id':'task','repo':'o/r','arms':{
            'historical':['a','b','shared'],'body_original':['c','shared','d'],'generated':['target','shared','a']}}
        prediction={'instance_id':'task','scores':{'a':1,'b':2,'shared':3,'c':4,'d':5,'target':6}}
        return candidate,prediction

    def test_equal_weight_rrf_aggregates_and_is_symmetric(self):
        self.assertEqual(simple_pool(['a','b','shared'],['c','shared','d'],2),['shared','a'])
        self.assertEqual(simple_pool(['a','b'],['b','c']),simple_pool(['b','c'],['a','b']))

    def test_id_ties_and_duplicate_dedup_across_lists(self):
        self.assertEqual(simple_pool(['b'],['a']),['a','b'])
        self.assertEqual(simple_pool(['a','b'],['a','b']),['a','b'])
        with self.assertRaises(ValueError):simple_pool(['a','a'],[])

    def test_empty_and_invalid_settings(self):
        self.assertEqual(simple_pool([],[]),[])
        self.assertEqual(simple_pool(['a'],[],0),[])
        with self.assertRaises(ValueError):simple_pool([],[],-1)
        with self.assertRaises(ValueError):simple_pool([],[],1,0)

    def test_membership_cap_precedes_strong_scoring(self):
        # A high learned score cannot pull back a candidate excluded by top-200 RRF.
        metadata=[f'm{i:03d}' for i in range(200)]
        body=[f'b{i:03d}' for i in range(200)]
        candidate={'instance_id':'task','repo':'o/r','arms':{
            'historical':metadata,'body_original':body,'generated':['target']}}
        scores={n:0 for n in metadata+body+['target']}
        scores[metadata[-1]]=999
        row=replay_task(candidate,{'instance_id':'task','scores':scores})
        self.assertEqual(len(row['pools']['simple_fusion']),200)
        self.assertNotIn(metadata[-1],row['orders']['simple_fusion'])
        self.assertEqual(set(row['pools']['simple_fusion']),set(simple_pool(metadata,body)))

    def test_frozen_scores_and_stable_pool_ties(self):
        candidate,prediction=self.fixture()
        frozen=copy.deepcopy((candidate,prediction))
        row=replay_task(candidate,prediction)
        self.assertEqual(row['orders']['generated'],['target','shared','a'])
        self.assertEqual(row['orders']['simple_fusion'][0],'d')
        self.assertEqual((candidate,prediction),frozen)
        prediction['scores']={n:1 for n in prediction['scores']}
        row=replay_task(candidate,prediction)
        self.assertEqual(row['orders']['simple_fusion'],row['pools']['simple_fusion'])

    def test_no_label_inputs_or_missing_scores(self):
        candidate,prediction=self.fixture()
        with self.assertRaises(ValueError):replay_task({**candidate,'gold':['a']},prediction)
        with self.assertRaises(ValueError):replay_task(candidate,{**prediction,'labels':[1]})
        prediction['scores'].pop('d')
        with self.assertRaises(ValueError):replay_task(candidate,prediction)

    def test_replay_requires_no_file_or_network_access(self):
        candidate,prediction=self.fixture()
        with patch('builtins.open',side_effect=AssertionError('IO prohibited')):
            row=replay_task(candidate,prediction)
        self.assertEqual(row['logical_retrieval_calls']['simple_fusion'],2)
        self.assertEqual(row['logical_generation_calls']['simple_fusion'],0)
        self.assertEqual(row['logical_generation_calls']['generated'],1)

    def test_novel_gold_is_outside_untruncated_original_union(self):
        candidate,prediction=self.fixture()
        row=replay_task(candidate,prediction)
        scored=score_task(row,{'target','shared','absent'})
        self.assertEqual(scored['generated_top_targets_outside_original_union'],['target'])
        self.assertEqual(scored['arms']['generated']['coverage'],2/3)
        self.assertEqual(scored['arms']['simple_fusion']['coverage'],1/3)
        self.assertFalse(score_task(row,set())['scorable'])

    def test_cluster_interval_treats_repo_as_unit(self):
        rows=[{'repo':'o/a','arms':{'generated':{'recall_at_10':1},'simple_fusion':{'recall_at_10':0}}} for _ in range(3)]
        self.assertIsNone(interval(rows))
        rows.append({'repo':'o/b','arms':{'generated':{'recall_at_10':0},'simple_fusion':{'recall_at_10':0}}})
        self.assertEqual(interval(rows),[0,1])


if __name__=='__main__':unittest.main()
