"""E1 tests: graph loading and gold-symbol coverage classification."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from experiments.coverage import (
    MATCH_EXACT,
    MATCH_MISS,
    MATCH_MODULE_ONLY,
    MATCH_SUFFIX,
    classify,
    candidate_ids,
    module_prefix,
    nodes_in_module,
)
from experiments.graphfile import summarize

GRAPH = {
    "directed": True,
    "multigraph": True,
    "graph": {"repo": "acme/repo"},
    "nodes": [
        {"id": "pkg.mod.A.m", "name": "pkg.mod.A.m", "text": "def m(self): ..."},
        {"id": "pkg.mod.f", "name": "pkg.mod.f", "text": "def f(): ..."},
        {"id": "other.x", "name": "other.x", "text": ""},
    ],
    "edges": [
        {"source": "pkg.mod.A.m", "target": "pkg.mod.f", "type": "calls", "key": 0}
    ],
}


def _write_graph(payload: object) -> Path:
    path = Path(tempfile.mkdtemp()) / "g.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class GraphSummaryTests(unittest.TestCase):
    def test_reads_nodes_and_edges(self) -> None:
        summary = summarize(_write_graph(GRAPH))
        self.assertTrue(summary.ok)
        self.assertEqual(summary.node_count, 3)
        self.assertEqual(summary.edge_count, 1)
        self.assertTrue(summary.directed)
        self.assertTrue(summary.multigraph)
        self.assertEqual(summary.nodes_with_text, 2)
        self.assertIn("pkg.mod.A.m", summary.node_ids)

    def test_zero_byte_file_is_flagged(self) -> None:
        path = Path(tempfile.mkdtemp()) / "empty.json"
        path.write_bytes(b"")
        summary = summarize(path)
        self.assertFalse(summary.ok)
        self.assertTrue(summary.empty)
        self.assertEqual(summary.node_count, 0)

    def test_bad_json_is_flagged_not_raised(self) -> None:
        path = Path(tempfile.mkdtemp()) / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        summary = summarize(path)
        self.assertFalse(summary.ok)
        self.assertTrue(summary.error.startswith("unreadable:"))

    def test_missing_schema_keys(self) -> None:
        summary = summarize(_write_graph({"directed": True}))
        self.assertFalse(summary.ok)
        self.assertEqual(summary.error, "missing-nodes-or-edges")


class ModulePrefixTests(unittest.TestCase):
    def test_module_package(self) -> None:
        self.assertEqual(module_prefix("pkg/__init__.py"), "pkg")

    def test_nested_module(self) -> None:
        self.assertEqual(module_prefix("fastapi/routing.py"), "fastapi.routing")

    def test_backslashes(self) -> None:
        self.assertEqual(module_prefix("pkg\\sub\\mod.py"), "pkg.sub.mod")


class CandidateTests(unittest.TestCase):
    def test_includes_leaf_fallback(self) -> None:
        self.assertEqual(
            candidate_ids("pkg/mod.py", "A.m"),
            ["pkg.mod.A.m", "pkg.mod.m"],
        )

    def test_no_qualname_falls_back_to_module(self) -> None:
        self.assertEqual(candidate_ids("pkg/mod.py", None), ["pkg.mod"])


class ClassifyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ids = set(GRAPH["nodes"][i]["id"] for i in range(len(GRAPH["nodes"])))

    def test_exact(self) -> None:
        self.assertEqual(classify("pkg/mod.py", "A.m", self.ids)[0], MATCH_EXACT)

    def test_module_present_symbol_missing(self) -> None:
        self.assertEqual(classify("pkg/mod.py", "Z.missing", self.ids)[0], MATCH_MODULE_ONLY)

    def test_suffix_match(self) -> None:
        ids = {"repo.pkg.mod.A.m"}
        self.assertEqual(classify("pkg/mod.py", "A.m", ids)[0], MATCH_SUFFIX)

    def test_miss(self) -> None:
        self.assertEqual(classify("nope/gone.py", "A.m", self.ids)[0], MATCH_MISS)

    def test_nodes_in_module(self) -> None:
        self.assertEqual(nodes_in_module(self.ids, "pkg.mod"), 2)


if __name__ == "__main__":
    unittest.main()
