import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.buildgraph import build_graph
from experiments.snapindex import SnapshotIndex
from experiments.strong_query_features import candidate_features
from tools import features as historical
from tools.run_strong_query_v2 import encoder_documents, folds_for, inference_anchor, cluster_interval


class StrongQueryTests(unittest.TestCase):
    def test_candidate_stage_has_required_validation_import(self):
        from tools.run_strong_query_v2 import validate_retrieval
        self.assertTrue(callable(validate_retrieval))

    def fixture(self):
        files={'pkg/core.py':'def convert(value):\n    """Convert timezone."""\n    return helper(value)\n\ndef helper(value):\n    return value\n',
               'elsewhere.py':'def unrelated():\n    """Unrelated operation."""\n    return 1\n'}
        issue='convert timezone'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);snapshot=root/'task';snapshot.mkdir()
            for name,content in files.items():
                path=snapshot/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content,encoding='utf-8')
            task={'instance_id':'task','repo':'o/r','base_commit':'abc','problem_statement':issue,'patch':''}
            with patch.object(historical,'_INDEX',SnapshotIndex(root)),patch.object(historical,'KEEP_EMPTY_GOLD',True):
                rows=historical._work(task)
        graph,_=build_graph(files)
        return issue,files,graph,rows

    def test_historical_fourteen_columns_reproduce_and_saved_bm25_preserved(self):
        issue,files,graph,rows=self.fixture()
        anchor=inference_anchor(rows)
        rebuilt,audit=candidate_features(issue,files,graph,anchor,anchor['ids'])
        self.assertEqual(rebuilt,anchor['rows'])
        self.assertEqual(audit['new_rows'],0)
        self.assertEqual(audit['existing_rows_verified'],len(anchor['ids']))

    def test_gold_labels_rejected_from_inference_anchor(self):
        issue,files,graph,rows=self.fixture()
        anchor=inference_anchor(rows)
        self.assertEqual(set(anchor),{'ids','rows','files'})
        with self.assertRaises(ValueError):
            candidate_features(issue,files,graph,{**anchor,'labels':rows['labels']},anchor['ids'])

    def test_new_unmatched_candidate_has_zero_score_and_no_new_file_context(self):
        issue,files,graph,rows=self.fixture()
        anchor=inference_anchor(rows)
        wanted=list(anchor['ids'])+['elsewhere.unrelated']
        actual,audit=candidate_features(issue,files,graph,anchor,wanted)
        self.assertEqual(actual[:-1],anchor['rows'])
        new=actual[-1]
        self.assertEqual(new[0],0)
        self.assertEqual(new[1],round(1/(len(graph.nodes)+1),4))
        self.assertEqual(new[12:14],[0,0])
        self.assertEqual(audit['new_rows'],1)

    def test_saved_feature_corruption_is_detected(self):
        issue,files,graph,rows=self.fixture()
        anchor=inference_anchor(rows)
        anchor['rows'][0][10]=999
        with self.assertRaisesRegex(ValueError,'reproduction failed'):
            candidate_features(issue,files,graph,anchor,anchor['ids'])

    def test_candidate_pools_do_not_change_anchored_context(self):
        issue,files,graph,rows=self.fixture()
        anchor=inference_anchor(rows)
        first,_=candidate_features(issue,files,graph,anchor,['pkg.core.convert'])
        extra,_=candidate_features(issue,files,graph,anchor,['elsewhere.unrelated','pkg.core.convert'])
        self.assertEqual(first[0],extra[1])

    def test_invalid_or_duplicate_candidate_fails(self):
        issue,files,graph,rows=self.fixture()
        anchor=inference_anchor(rows)
        for wanted in (['missing'],['pkg.core.convert']*2):
            with self.assertRaises(ValueError):candidate_features(issue,files,graph,anchor,wanted)

    def test_repository_folds_are_disjoint_and_cover_all(self):
        repos=['o/a','o/b','o/c','o/d']
        folds=folds_for(repos)
        self.assertEqual(folds,folds_for(list(reversed(repos))))
        for train,test in folds:
            self.assertFalse(train&test)
            self.assertEqual(train|test,set(repos))
        self.assertEqual(folds[0][0],folds[1][1])

    def test_dense_documents_follow_historical_recipe(self):
        issue,files,graph,rows=self.fixture()
        docs=encoder_documents(['pkg.core.convert','pkg.core'],graph.nodes,files)
        self.assertTrue(docs[0].startswith('pkg/core.py :: pkg.core.convert\ndef convert'))
        self.assertEqual(docs[1],'pkg/core.py :: pkg.core\n')

    def test_repository_cluster_interval_not_independent_tasks(self):
        rows=[{'repo':'o/a','arms':{'generated':{'recall_at_10':1},'body_original':{'recall_at_10':0}}} for _ in range(3)]
        self.assertIsNone(cluster_interval(rows,'body_original',100))
        rows.append({'repo':'o/b','arms':{'generated':{'recall_at_10':0},'body_original':{'recall_at_10':0}}})
        self.assertEqual(cluster_interval(rows,'body_original',100),[0,1])


if __name__=='__main__':unittest.main()
