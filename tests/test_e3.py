"""E3: the retrieval arms have to be honest before their numbers mean anything."""

import unittest

try:
    from experiments.retrieve import (
        BM25, adjacency, any_hit_at, context_chars, document_text, expand,
        expand_round_robin, fuse, recall_at, tokenize,
    )
except ImportError:  # pragma: no cover
    import pathlib, sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from experiments.retrieve import (
        BM25, adjacency, any_hit_at, context_chars, document_text, expand,
        expand_round_robin, fuse, recall_at, tokenize,
    )


DOCS = {
    "pkg.io.read_csv": "pkg/io.py read_csv load a csv file from disk",
    "pkg.io.write_csv": "pkg/io.py write_csv dump rows to a csv file",
    "pkg.net.fetch": "pkg/net.py fetch download a url over http",
    "pkg.model.fit": "pkg/model.py fit train the estimator",
}


class TestTokenize(unittest.TestCase):
    def test_snake_and_camel_both_split(self):
        self.assertEqual(tokenize("read_csv_file"), ["read", "csv", "file"])
        self.assertEqual(tokenize("readCsvFile"), ["read", "csv", "file"])

    def test_stopwords_and_single_characters_go(self):
        self.assertEqual(tokenize("a value of the thing"), ["value", "thing"])

    def test_digits_survive(self):
        self.assertIn("utf8", tokenize("open_utf8"))


class TestBM25(unittest.TestCase):
    def setUp(self):
        self.bm = BM25(DOCS)

    def test_ranks_by_the_rarer_term(self):
        ranked = [doc for doc, _ in self.bm.search("download url http", 4)]
        self.assertEqual(ranked[0], "pkg.net.fetch")

    def test_csv_query_finds_both_csv_helpers_first(self):
        ranked = [doc for doc, _ in self.bm.search("csv file", 4)]
        self.assertEqual(set(ranked[:2]), {"pkg.io.read_csv", "pkg.io.write_csv"})

    def test_k_caps_the_result(self):
        self.assertEqual(len(self.bm.search("csv file", 1)), 1)

    def test_empty_query_returns_nothing(self):
        self.assertEqual(self.bm.search("", 5), [])

    def test_unknown_terms_do_not_crash(self):
        self.assertEqual(self.bm.search("zzzz qqqq", 5), [])

    def test_empty_corpus_is_safe(self):
        self.assertEqual(BM25({}).search("csv", 3), [])


class TestGraphArms(unittest.TestCase):
    GRAPH = {
        "edges": [
            {"source": "a", "target": "b", "type": "calls"},
            {"source": "b", "target": "c", "type": "calls"},
            {"source": "a", "target": "d", "type": "defines"},
            {"source": "a", "target": "ext.os.path", "type": "imports"},
        ]
    }

    def test_adjacency_is_undirected_and_call_only(self):
        neigh = adjacency(self.GRAPH)
        self.assertEqual(neigh["a"], {"b"})
        self.assertIn("a", neigh["b"])
        self.assertNotIn("d", neigh["a"])
        self.assertNotIn("ext.os.path", neigh["a"])

    def test_adjacency_can_be_restricted_to_high_precision_edges(self):
        graph = {"edges": [
            {"source": "a", "target": "b", "type": "calls", "resolution": "local"},
            {"source": "a", "target": "z", "type": "calls", "resolution": "unresolved"},
        ]}
        self.assertEqual(adjacency(graph)["a"], {"b", "z"})
        self.assertEqual(adjacency(graph, {"local"})["a"], {"b"})

    def test_expand_is_one_hop(self):
        neigh = adjacency(self.GRAPH)
        self.assertEqual(expand(["a"], neigh, 10), ["a", "b"])
        self.assertEqual(expand(["a"], neigh, 2), ["a", "b"])

    def test_expand_keeps_seed_order_first(self):
        neigh = adjacency(self.GRAPH)
        self.assertEqual(expand(["b"], neigh, 10)[0], "b")

    def test_expand_terminates_without_neighbours(self):
        self.assertEqual(expand(["zzz"], {}, 5), ["zzz"])


class TestOpenArm(unittest.TestCase):
    """The treatment arm must be able to introduce a symbol BM25 never ranked."""

    NEIGH = {
        "s1": {"n1", "n2", "n3"},
        "s2": {"n4"},
    }

    def test_head_is_untouched(self):
        out = expand_round_robin(["s1", "s2", "x", "y"], self.NEIGH, k=8, seeds=2)
        self.assertEqual(out[:2], ["s1", "s2"])

    def test_neighbours_are_interleaved_across_seeds(self):
        out = expand_round_robin(["s1", "s2", "x", "y"], self.NEIGH, k=4, seeds=2)
        self.assertEqual(out, ["s1", "s2", "n1", "n4"])

    def test_a_hub_seed_cannot_take_every_slot(self):
        out = expand_round_robin(["s1", "s2"], self.NEIGH, k=4, seeds=2)
        self.assertIn("n4", out)

    def test_padding_comes_from_the_text_tail(self):
        out = expand_round_robin(["s1", "x", "y", "z"], {"s1": {"n1"}}, k=4, seeds=1)
        self.assertEqual(out, ["s1", "n1", "x", "y"])

    def test_no_duplicates(self):
        out = expand_round_robin(["s1", "n1"], {"s1": {"n1", "n2"}}, k=4, seeds=2)
        self.assertEqual(len(out), len(set(out)))

    def test_k_is_respected(self):
        self.assertEqual(len(expand_round_robin(["s1"], self.NEIGH, k=2, seeds=1)), 2)
        self.assertEqual(expand_round_robin(["s1"], self.NEIGH, k=0), [])

    def test_isolated_seed_still_returns_k(self):
        out = expand_round_robin(["a", "b", "c", "d", "e"], {}, k=5, seeds=2)
        self.assertEqual(out, ["a", "b", "c", "d", "e"])


class TestFusion(unittest.TestCase):
    POOL = [("a", 10.0), ("b", 8.0), ("c", 6.0), ("d", 4.0), ("e", 2.0)]
    NEIGH = {"a": {"x"}, "b": {"c"}}

    def test_weight_zero_is_plain_text(self):
        self.assertEqual(fuse(self.POOL, self.NEIGH, k=5, weight=0.0),
                         ["a", "b", "c", "d", "e"])

    def test_neighbour_can_enter_a_shortlist_it_was_absent_from(self):
        # x inherits 0.5 of a's score, which is enough to beat d and e but not c
        out = fuse(self.POOL, self.NEIGH, k=4, seeds=1, weight=0.5)
        self.assertEqual(out, ["a", "b", "c", "x"])

    def test_high_weight_lets_a_neighbour_outrank_its_seed(self):
        out = fuse(self.POOL, {"a": {"x"}}, k=2, seeds=1, weight=1.5)
        self.assertEqual(out[0], "x")

    def test_text_hits_survive_when_there_is_room(self):
        out = fuse(self.POOL, self.NEIGH, k=6, seeds=5, weight=0.5)
        for node_id in ("a", "b", "c", "d", "e"):
            self.assertIn(node_id, out)

    def test_a_neighbour_displaces_only_the_weakest_text_hit(self):
        out = fuse(self.POOL, self.NEIGH, k=5, seeds=5, weight=0.5)
        self.assertEqual(out, ["a", "b", "c", "x", "d"])

    def test_empty_pool(self):
        self.assertEqual(fuse([], self.NEIGH, k=5), [])

    def test_k_is_respected(self):
        self.assertEqual(len(fuse(self.POOL, self.NEIGH, k=2)), 2)


class TestMetrics(unittest.TestCase):
    def test_recall_counts_the_targets_found(self):
        self.assertEqual(recall_at(["a", "b", "c"], {"b", "z"}, 3), 0.5)
        self.assertEqual(recall_at(["a", "b", "c"], {"b", "z"}, 1), 0.0)

    def test_recall_of_no_targets_is_nan(self):
        self.assertNotEqual(recall_at(["a"], set(), 1), recall_at(["a"], set(), 1))

    def test_any_hit(self):
        self.assertEqual(any_hit_at(["a", "b"], {"b"}, 2), 1.0)
        self.assertEqual(any_hit_at(["a", "b"], {"b"}, 1), 0.0)

    def test_context_budget_is_measured_not_guessed(self):
        nodes = {"a": {"file": "f.py", "qualname": "a", "doc": "x" * 1000}}
        self.assertEqual(context_chars(["a"], nodes, cap=10), 11)
        self.assertEqual(context_chars([], nodes), 0)


class TestDocumentText(unittest.TestCase):
    def test_path_and_qualname_are_searchable(self):
        text = document_text({"file": "pkg/mod.py", "qualname": "Cls.method",
                              "name": "method", "signature": "def method(self)",
                              "doc": "does a thing"})
        for expected in ("pkg/mod.py", "Cls method", "does a thing"):
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
