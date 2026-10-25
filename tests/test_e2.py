"""E2: the rebuilt graph has to be right before any coverage number means anything."""

import unittest

try:
    from experiments.buildgraph import (
        EDGE_CALLS, EDGE_DEFINES, EDGE_IMPORTS,
        R_AMBIGUOUS, R_EXTERNAL, R_IMPORT, R_LOCAL,
        build_graph, iter_python_files, module_of,
    )
except ImportError:  # pragma: no cover
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from experiments.buildgraph import (
        EDGE_CALLS, EDGE_DEFINES, EDGE_IMPORTS,
        R_AMBIGUOUS, R_EXTERNAL, R_IMPORT, R_LOCAL,
        build_graph, iter_python_files, module_of,
    )

REPO = {
    "pkg/__init__.py": '"""Package docstring."""\n',
    "pkg/base.py": (
        "class Base:\n"
        "    def run(self):\n"
        "        return 1\n"
    ),
    "pkg/other.py": (
        "def helper(x):\n"
        '    """Add one."""\n'
        "    return x + 1\n"
    ),
    "pkg/mod.py": (
        "import os\n"
        "from pkg.other import helper\n"
        "from pkg.base import Base\n"
        "\n"
        "\n"
        "def local_fn():\n"
        "    return 2\n"
        "\n"
        "\n"
        "class Thing(Base):\n"
        "    def method(self):\n"
        "        helper(1)\n"
        "        local_fn()\n"
        '        return os.path.join("a", "b")\n'
    ),
}


def build():
    return build_graph(dict(REPO))


class TestModules(unittest.TestCase):
    def test_package_init_is_the_package(self):
        self.assertEqual(module_of("pkg/__init__.py"), "pkg")
        self.assertEqual(module_of("pkg/mod.py"), "pkg.mod")
        self.assertEqual(module_of("a/b/c.py"), "a.b.c")

    def test_skips_vendored_directories(self):
        names = ["pkg/mod.py", "pkg/__pycache__/mod.py", ".tox/x.py", "docs/conf.py"]
        self.assertEqual(iter_python_files(names), ["docs/conf.py", "pkg/mod.py"])


class TestNodes(unittest.TestCase):
    def setUp(self):
        self.graph, self.stats = build()

    def test_every_symbol_is_a_node(self):
        for node_id in (
            "pkg", "pkg.base", "pkg.base.Base", "pkg.base.Base.run",
            "pkg.other", "pkg.other.helper",
            "pkg.mod", "pkg.mod.local_fn", "pkg.mod.Thing", "pkg.mod.Thing.method",
        ):
            self.assertIn(node_id, self.graph.nodes)

    def test_node_carries_what_a_retriever_needs(self):
        node = self.graph.nodes["pkg.other.helper"]
        self.assertEqual(node["name"], "helper")
        self.assertEqual(node["doc"], "Add one.")
        self.assertEqual(node["signature"], "def helper(x)")
        self.assertEqual(node["kind"], "function")
        self.assertEqual(node["file"], "pkg/other.py")

    def test_method_is_tagged_as_a_method(self):
        self.assertEqual(self.graph.nodes["pkg.mod.Thing.method"]["kind"], "method")

    def test_text_is_opt_in(self):
        self.assertIsNone(self.graph.nodes["pkg.other.helper"]["text"])
        graph, _ = build_graph(dict(REPO), keep_text=True)
        self.assertIn("return x + 1", graph.nodes["pkg.other.helper"]["text"])

    def test_line_numbers_locale_the_symbol(self):
        node = self.graph.nodes["pkg.mod.Thing.method"]
        lines = REPO["pkg/mod.py"].splitlines()
        self.assertEqual(lines[node["lineno"] - 1].strip(), "def method(self):")
        self.assertEqual(lines[node["end_lineno"] - 1].strip(), 'return os.path.join("a", "b")')


class TestEdges(unittest.TestCase):
    def setUp(self):
        self.graph, _ = build()
        self.edges = {(e["source"], e["target"], e["type"]): e for e in self.graph.edges}

    def test_definitions_hang_off_their_parent(self):
        self.assertIn(("pkg.mod", "pkg.mod.Thing", EDGE_DEFINES), self.edges)
        self.assertIn(("pkg.mod.Thing", "pkg.mod.Thing.method", EDGE_DEFINES), self.edges)
        self.assertIn(("pkg.base", "pkg.base.Base", EDGE_DEFINES), self.edges)

    def test_same_module_call_resolves_locally(self):
        e = self.edges[("pkg.mod.Thing.method", "pkg.mod.local_fn", EDGE_CALLS)]
        self.assertEqual(e["resolution"], R_LOCAL)

    def test_imported_call_resolves_through_the_alias(self):
        e = self.edges[("pkg.mod.Thing.method", "pkg.other.helper", EDGE_CALLS)]
        self.assertEqual(e["resolution"], R_IMPORT)

    def test_stdlib_call_is_external_not_a_failure(self):
        e = self.edges[("pkg.mod.Thing.method", "os.path.join", EDGE_CALLS)]
        self.assertEqual(e["resolution"], R_EXTERNAL)

    def test_inheritance_edge(self):
        found = [e for e in self.graph.edges
                 if e["type"] == "inherits" and e["source"] == "pkg.mod.Thing"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["target"], "pkg.base.Base")

    def test_import_edges(self):
        targets = {e["target"] for e in self.graph.edges if e["type"] == EDGE_IMPORTS}
        self.assertIn("pkg.other.helper", targets)
        self.assertIn("pkg.base.Base", targets)
        self.assertIn("os", targets)


class TestFailureModes(unittest.TestCase):
    def test_syntax_error_is_counted_not_fatal(self):
        repo = dict(REPO)
        repo["pkg/broken.py"] = "def f(:\n"
        graph, stats = build_graph(repo)
        self.assertEqual(stats["syntax_error"], 1)
        self.assertIn("pkg.mod.Thing.method", graph.nodes)

    def test_ambiguous_name_is_not_guessed(self):
        repo = {
            "a/one.py": "def dup():\n    return 1\n",
            "b/two.py": "def dup():\n    return 2\n",
            "c/caller.py": "def go():\n    dup()\n",
        }
        graph, _ = build_graph(repo)
        calls = [e for e in graph.edges if e["type"] == EDGE_CALLS]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["resolution"], R_AMBIGUOUS)
        self.assertEqual(calls[0]["target"], "")

    def test_nested_def_calls_are_attributed_to_the_nested_def(self):
        repo = {
            "m.py": (
                "def inner():\n    helper()\n\n"
                "def outer():\n    def inner2():\n        helper()\n    inner2()\n\n"
                "def helper():\n    return 1\n"
            )
        }
        graph, _ = build_graph(repo)
        calls = {(e["source"], e["target"]) for e in graph.edges if e["type"] == EDGE_CALLS}
        # inner2's body calls helper, so inner2 owns that edge
        self.assertIn(("m.outer.inner2", "m.helper"), calls)
        # outer's own body only calls inner2 -- it must not inherit the inner call
        self.assertIn(("m.outer", "m.outer.inner2"), calls)
        self.assertNotIn(("m.outer", "m.helper"), calls)


class TestJsonShape(unittest.TestCase):
    def test_matches_the_shipped_asset_shape(self):
        from experiments.buildgraph import to_json
        graph, _ = build()
        payload = to_json(graph)
        self.assertTrue(payload["directed"])
        self.assertTrue(payload["multigraph"])
        for key in ("id", "name", "text"):
            self.assertIn(key, payload["nodes"][0])
        for key in ("source", "target", "type", "key"):
            self.assertIn(key, payload["edges"][0])


if __name__ == "__main__":
    unittest.main()
