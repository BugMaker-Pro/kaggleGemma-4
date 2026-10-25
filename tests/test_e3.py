"""E3: the retrieval arms have to be honest before their numbers mean anything."""

import unittest

try:
    from experiments.retrieve import (
        BM25, adjacency, any_hit_at, context_chars, document_text, expand,
        recall_at, tokenize,
    )
except ImportError:  # pragma: no cover
    import pathlib, sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from experiments.retrieve import (
        BM25, adjacency, any_hit_at, context_chars, document_text, expand,
        recall_at, tokenize,
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

    def test_expand_is_one_hop(self):
        neigh = adjacency(self.GRAPH)
        self.assertEqual(expand(["a"], neigh, 10), ["a", "b"])
        self.assertEqual(expand(["a"], neigh, 2), ["a", "b"])

    def test_expand_keeps_seed_order_first(self):
        neigh = adjacency(self.GRAPH)
        self.assertEqual(expand(["b"], neigh, 10)[0], "b")

    def test_expand_terminates_without_neighbours(self):
        self.assertEqual(expand(["zzz"], {}, 5), ["zzz"])


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
