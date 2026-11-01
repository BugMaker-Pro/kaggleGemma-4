from __future__ import annotations
import unittest
from experiments.graph_controls import (adjacency, bm25_subset, degree_signature, edge,
                                        file_marked, projection, promote, reachable, rewire)
from experiments.retrieve import BM25


class GraphControlTests(unittest.TestCase):
    def test_projection_uses_only_relevant_internal_edges(self):
        graph = [{'source':a,'target':b,'type':t} for a,b,t in [
            ('a','b','calls'),('b','a','calls'),('a','a','calls'),
            ('a','external','calls'),('b','c','defines'),('b','c','inherits')]]
        self.assertEqual(projection(graph,['a','b','c']),[(0,1),(1,2)])

    def test_seeds_and_base_order_are_preserved(self):
        order = list(range(15))
        result = promote(order,{0,4,8,12,14})
        self.assertEqual(result,[0,1,2,3,4,8,12,14,5,6])
        self.assertEqual(promote(order,set()),order[:10])
        self.assertEqual(promote([2,1],{1}),[2,1])

    def test_file_control_does_not_use_empty_paths(self):
        files=['','a','b','c','d','a','z','']
        self.assertEqual(file_marked(list(range(8)),files),{1,2,3,4,5})

    def test_reach_ignores_self_seed_hits(self):
        self.assertEqual(reachable(list(range(10)),adjacency([(0,1),(2,7),(4,8)])),{7,8})

    def test_subset_bm25_retains_full_corpus_statistics(self):
        docs={'a':'parse tree parse names','b':'tree tree leaf','c':'read file',
              'd':'parse file names tree','outside':'parse parse rare leaf token'}
        expected=dict(BM25(docs).search('parse rare parse tree',len(docs)))
        wanted=['b','a','c']
        actual=bm25_subset(docs.items(),'parse rare parse tree',wanted)
        for name,score in zip(wanted,actual):
            self.assertAlmostEqual(score,expected.get(name,0),places=12)
        restricted=dict(BM25({key:docs[key] for key in wanted}).search('parse rare tree',3))
        self.assertNotAlmostEqual(actual[1],restricted['a'],places=5)

    def test_empty_query_scores_zero_and_missing_candidate_fails(self):
        self.assertEqual(bm25_subset([('a','hello')],'',['a']),[0])
        with self.assertRaises(ValueError):
            bm25_subset([('a','hello')],'hello',['missing'])

    def test_rewire_preserves_degrees_and_file_structure(self):
        files=['a']*6+['b']*6+['c']*6
        edges=sorted({edge(base+i,base+(i+1)%6) for base in (0,6,12) for i in range(6)} |
                     {edge(i,6+i) for i in range(6)} | {edge(6+i,12+i) for i in range(6)})
        for pair in (False,True):
            for seed in (11,23,37):
                altered,stats=rewire(edges,files,'task',seed,pair)
                self.assertEqual(len(altered),len(edges))
                self.assertEqual(len(altered),len(set(altered)))
                self.assertTrue(all(a<b for a,b in altered))
                self.assertEqual(degree_signature(edges,files),degree_signature(altered,files))
                if pair:
                    self.assertEqual(degree_signature(edges,files,True),degree_signature(altered,files,True))
                self.assertGreater(stats['accepted'],0)
                self.assertGreater(stats['changed_fraction'],0)
                self.assertEqual((altered,stats),rewire(reversed(edges),files,'task',seed,pair))

    def test_immobile_graph_is_reported_not_dropped(self):
        edges=[(0,1),(0,2),(0,3)]
        result,stats=rewire(edges,['one']*4,'star',11)
        self.assertEqual(result,edges)
        self.assertEqual(stats['accepted'],0)
        self.assertEqual(stats['changed_fraction'],0)
        self.assertGreater(stats['attempts'],0)
        self.assertEqual(rewire([],[],'empty',11)[1]['edges'],0)

    def test_global_degree_constraints_are_not_file_pair_constraints(self):
        files=['a','b','c','d']
        edges=[(0,1),(2,3)]
        # The stricter ensemble cannot mix these singleton file-pair buckets.
        strict,stats=rewire(edges,files,'task',11,True)
        self.assertEqual(strict,edges)
        self.assertEqual(stats['attempts'],0)
        _,loose_stats=rewire(edges,files,'task',11,False)
        self.assertGreater(loose_stats['accepted'],0)


class CachedGraphTests(unittest.TestCase):
    def test_exact_graph_and_body_parity_across_source_changes(self):
        from experiments.cached_graph import CachedBuilder, cached_body_scores
        from experiments.buildgraph import build_graph, to_json
        from experiments.graph_controls import body_documents
        builder=CachedBuilder()
        files={'pkg/__init__.py':'from .a import alpha\n',
               'pkg/a.py':'import os\ndef alpha(x):\n    """Read names."""\n    return os.path.join(x, "leaf")\n',
               'pkg/b.py':'from pkg.a import alpha\nclass C:\n    def run(self):\n        return alpha("tree")\n',
               'broken.py':'def :\n'}
        for iteration in range(3):
            if iteration==1:
                files['pkg/b.py']+='\ndef other():\n    return alpha("other")\n'
            if iteration==2:
                files.pop('pkg/a.py')
            expected,_=build_graph(files)
            actual,counts,stats=builder.build(files,'fixture')
            self.assertEqual(to_json(expected),to_json(actual))
            wanted=list(expected.nodes)
            direct=bm25_subset(body_documents(expected.nodes,files),'alpha names tree',wanted)
            self.assertEqual(direct,cached_body_scores(counts,'alpha names tree',wanted))
            if iteration:
                self.assertGreater(stats['cache_hits'],0)


class InferenceTests(unittest.TestCase):
    def test_holm_is_monotone_and_capped(self):
        from tools.analyse_graph_controls import holm
        actual=holm({'a':0.01,'b':0.04,'c':0.03,'d':0.9})
        self.assertAlmostEqual(actual['a'],0.04)
        self.assertAlmostEqual(actual['c'],0.09)
        self.assertAlmostEqual(actual['b'],0.09)
        self.assertAlmostEqual(actual['d'],0.9)

    def test_cluster_signflip_uses_repositories_not_tasks(self):
        from tools.analyse_graph_controls import paired_summary
        # Three positive independent units give 2/8, regardless of task counts.
        stats=paired_summary([1.0]*5+ [0.5,0.25],['a']*5+['b','c'],resamples=100)
        self.assertEqual(stats['repositories'],3)
        self.assertEqual(stats['repository_signflip_p'],0.25)
        self.assertAlmostEqual(stats['delta'],5.75/7)
        zero=paired_summary([0.0]*4,['a','a','b','c'],resamples=100)
        self.assertEqual(zero['repository_signflip_p'],1.0)
        self.assertEqual(zero['cluster_ci95'],[0.0,0.0])

    def test_seed_average_is_within_task(self):
        from tools.analyse_graph_controls import value
        row={'representations':{'dense':{'arms':{
            f'rewired_{seed}':{'symbol':position/4} for position,seed in enumerate((11,23,37,51,71))}}}}
        self.assertEqual(value(row,'dense','rewired'),0.5)


class HeadroomDiagnosticTests(unittest.TestCase):
    def test_seed_saturation_and_pool_misses_remain_separate(self):
        import json
        import tempfile
        from pathlib import Path
        from tools.analyse_graph_controls import retained_seed_diagnostics
        # One gold symbol is outside the pool: no oracle may call it recovered.
        context={'instance_id':'fixture','labels':[1,0,0,0,0,0,0,0,0,0,1,0],
                 'gold_total':3,'orders':{
                     'metadata':list(range(12)),
                     'body':[0,10,1,2,3,4,5,6,7,8,9,11],
                     'dense':list(range(12))}}
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'tmp') as directory:
            path=Path(directory)/'context.jsonl'
            path.write_text(json.dumps(context)+'\n',encoding='utf-8')
            result=retained_seed_diagnostics(path,{'fixture'})
        self.assertAlmostEqual(result['metadata']['seed_recall'],1/3)
        self.assertAlmostEqual(result['metadata']['remaining_slot_oracle'],2/3)
        self.assertAlmostEqual(result['metadata']['available_recall_gain'],1/3)
        self.assertAlmostEqual(result['body']['seed_recall'],2/3)
        self.assertEqual(result['body']['available_recall_gain'],0)
        self.assertEqual(result['body']['tasks_with_reordering_headroom'],0)


if __name__=='__main__':
    unittest.main()
