"""Unit tests for the runtime-evidence parser and resolver (no sandbox needed)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.failure_prelocalize import (  # noqa: E402
    Frame, build_coverage_command, build_runtime_report, build_test_command, coverage_scores,
    format_coverage_report, format_report, fuse_scores, is_test_path, module_name,
    ochiai_score, parse_coverage_json, parse_pytest_output, resolve_definition, source_frames,
    suspiciousness_scores, test_name_prior,
)

SAMPLE = """=========================== FAILURES ============================
________________________ test_core ________________________
tests/test_core.py:12: in test_core
    assert add(2, 2) == 5
src/core.py:5: in add
    return a + b
E   assert 4 == 5
========================= short test summary info ==========================
FAILED tests/test_core.py::test_core - assert 4 == 5
"""

SOURCE = "def outer():\n    def inner():\n        return 4\n    return inner\n"


class ParserTests(unittest.TestCase):
    def test_frames_tests_and_message(self):
        evidence = parse_pytest_output(SAMPLE)
        self.assertEqual(evidence.tests, ("tests/test_core.py::test_core",))
        self.assertEqual(
            [(frame.path, frame.line, frame.func) for frame in evidence.frames],
            [("tests/test_core.py", 12, "test_core"), ("src/core.py", 5, "add")],
        )
        self.assertEqual(evidence.message, "assert 4 == 5")

    def test_empty_output_is_an_error_not_a_success(self):
        evidence = parse_pytest_output("")
        self.assertEqual(evidence.tests, ())
        self.assertEqual(evidence.frames, ())
        self.assertTrue(format_report(evidence, None, None).startswith("runtime error:"))


class PathTests(unittest.TestCase):
    def test_test_paths(self):
        self.assertTrue(is_test_path("tests/test_core.py"))
        self.assertTrue(is_test_path("pkg/testing/helpers.py"))
        self.assertTrue(is_test_path("src/core_test.py"))
        self.assertTrue(is_test_path("conftest.py"))
        self.assertFalse(is_test_path("src/core.py"))

    def test_source_frames_keep_only_workspace_source(self):
        evidence = parse_pytest_output(SAMPLE)
        kept = source_frames(evidence, "/workspace")
        self.assertEqual([(frame.path, frame.line) for frame in kept], [("src/core.py", 5)])

    def test_module_name(self):
        self.assertEqual(module_name("/workspace/src/core.py"), "src.core")


class ResolverTests(unittest.TestCase):
    def test_innermost_definition_contains_line(self):
        definition = resolve_definition(SOURCE, 3)
        self.assertEqual(definition["qualname"], "outer.inner")
        self.assertEqual((definition["start_line"], definition["end_line"]), (2, 3))

    def test_module_level_line_has_no_definition(self):
        self.assertIsNone(resolve_definition("import os\n", 1))


class ReportTests(unittest.TestCase):
    def test_report_names_the_definition(self):
        evidence = parse_pytest_output(SAMPLE)
        frame = Frame("src/core.py", 5, "add")
        definition = {"qualname": "add", "kind": "function", "start_line": 5, "end_line": 6}
        report = format_report(evidence, frame, definition, "/workspace")
        self.assertIn("runtime evidence: tests/test_core.py::test_core failed", report)
        self.assertIn("last source frame: src/core.py:5 in add()", report)
        self.assertIn("definition: src.core.add (src/core.py:5-6)", report)
        self.assertIn("error: assert 4 == 5", report)


class SignalAuditTests(unittest.TestCase):
    def test_every_symbol_task_has_a_failing_test(self):
        from tools.audit_test_signal import audit

        stats = audit()
        self.assertEqual(stats["tasks"], 290)
        self.assertEqual(stats["tasks_with_f2p"], 290)


class CommandTests(unittest.TestCase):
    def test_command_runs_selected_nodes_and_keeps_failure_output(self):
        command = build_test_command(["tests/test_core.py::test_core"])
        self.assertIn("python3 -m pytest", command)
        self.assertIn("tests/test_core.py::test_core", command)
        self.assertIn("--tb=long", command)
        self.assertTrue(command.endswith("echo FAIL_EXIT:$?"))

    def test_quotes_shell_metacharacters(self):
        command = build_test_command(["tests/test_core.py::test_core[a b]"])
        self.assertIn("'tests/test_core.py::test_core[a b]'", command)

    def test_empty_selection_is_rejected(self):
        with self.assertRaises(ValueError):
            build_test_command([])


class CoverageTests(unittest.TestCase):
    def test_parse_coverage_json(self):
        payload = '{"files": {"src/core.py": {"executed_lines": [2, 6, 7]}, "empty.py": {"executed_lines": []}}}'
        self.assertEqual(parse_coverage_json(payload), {"src/core.py": {2, 6, 7}})

    def test_innermost_definition_gets_full_executed_span(self):
        scored = coverage_scores(SOURCE, {2, 3, 4})
        self.assertEqual(scored[0]["qualname"], "outer.inner")
        self.assertEqual(scored[0]["score"], 1.0)
        outer = next(item for item in scored if item["qualname"] == "outer")
        self.assertEqual(outer["score"], 0.75)

    def test_fuse_prefers_a_definition_strong_in_both_families(self):
        fused = fuse_scores({"a": 0.0, "b": 1.0}, {"a": 0.1, "b": 0.9})
        self.assertEqual(list(fused)[0], "b")
        self.assertAlmostEqual(fused["a"], 0.0)
        self.assertAlmostEqual(fused["b"], 1.0)

    def test_fuse_rejects_bad_weight(self):
        with self.assertRaises(ValueError):
            fuse_scores({}, {}, 1.5)

    def test_empty_coverage_is_an_error(self):
        self.assertTrue(format_coverage_report([]).startswith("coverage error:"))

    def test_coverage_command_requests_a_json_report(self):
        command = build_coverage_command(["tests/test_core.py::test_core"])
        self.assertIn("--cov-report=json:/tmp/coverage.json", command)
        self.assertIn("echo COV_EXIT:$?", command)


class RuntimeReportTests(unittest.TestCase):
    def test_merges_traceback_coverage_and_static_scores(self):
        source = "def outer():\n    def inner():\n        return 4\n\ndef add(a, b):\n    return a + b\n"
        report = build_runtime_report(
            SAMPLE,
            coverage={"src/core.py": {2, 3, 5}},
            static={"src.core.add": 0.1, "src.core.outer.inner": 0.9},
            source_reader=lambda path: source if path.endswith("src/core.py") else None,
        )
        self.assertIn("traceback definition: src.core.add", report)
        self.assertIn("coverage: src.core.outer.inner", report)
        self.assertIn("fused shortlist:", report)

    def test_no_evidence_is_an_explicit_error(self):
        report = build_runtime_report("", None, None, lambda path: None)
        self.assertTrue(report.startswith("runtime error:"))

    def test_missing_source_degrades_to_frames_and_static(self):
        report = build_runtime_report(SAMPLE, {"src/core.py": {5}}, {"src.core.add": 1.0},
                                      lambda path: None)
        self.assertIn("traceback frame: src/core.py:5 in add()", report)
        self.assertNotIn("coverage:", report)
        self.assertIn("fused shortlist: src.core.add", report)


class RuntimeHookPureTests(unittest.TestCase):
    def test_report_from_log_reads_the_source(self):
        source = "def outer():\n    def inner():\n        return 4\n\ndef add(a, b):\n    return a + b\n"
        from tools.runtime_prelocalize import report_from_failure_log

        report = report_from_failure_log(
            SAMPLE, lambda path: source if path.endswith("src/core.py") else None)
        self.assertIn("definition: src.core.add", report)

    def test_missing_log_is_an_explicit_error(self):
        from tools.runtime_prelocalize import report_from_failure_log

        self.assertTrue(report_from_failure_log("", lambda path: None).startswith("runtime error:"))


class SuspiciousnessTests(unittest.TestCase):
    SOURCE = "def a():\n    return 1\n\ndef b():\n    return 2\n"

    def test_ochiai_monotonicity(self):
        self.assertAlmostEqual(ochiai_score(1, 0, 2), 1 / 2 ** 0.5)
        self.assertAlmostEqual(ochiai_score(1, 1, 2), 0.5)
        self.assertEqual(ochiai_score(0, 1, 2), 0.0)

    def test_fail_only_definition_beats_shared_definition(self):
        scored = suspiciousness_scores({"src/core.py": {1, 4}}, {"src/core.py": {4}},
                                       lambda path: self.SOURCE)
        self.assertEqual([item["key"] for item in scored], ["src.core.a", "src.core.b"])
        self.assertGreater(scored[0]["score"], scored[1]["score"])

    def test_report_switches_to_suspiciousness_with_pass_coverage(self):
        report = build_runtime_report(
            SAMPLE, coverage={"src/core.py": {1, 4}}, static={}, source_reader=lambda path: self.SOURCE,
            pass_coverage={"src/core.py": {4}})
        self.assertIn("suspiciousness:", report)


class TestNamePriorTests(unittest.TestCase):
    def test_routing_test_prefers_the_matching_definition(self):
        prior = test_name_prior(
            ["tests/test_routing.py::test_include_router[case-1]"],
            {"fastapi.routing.include_router": 0.0,
             "fastapi.applications.FastAPI": 0.0,
             "requests.models.PreparedRequest": 0.0},
        )
        self.assertEqual(list(prior)[0], "fastapi.routing.include_router")
        self.assertNotIn("requests.models.PreparedRequest", prior)

    def test_empty_ids_have_no_prior(self):
        self.assertEqual(test_name_prior([], {"a.b": 0.0}), {})


if __name__ == "__main__":
    unittest.main()
