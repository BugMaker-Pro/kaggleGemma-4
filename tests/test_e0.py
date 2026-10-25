"""E0 regression tests: patch parsing, symbol resolution, snapshot access."""

from __future__ import annotations

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from experiments.gold import run
from experiments.patchfile import parse as parse_patch
from experiments.snapshot import Snapshot
from experiments.symbols import python_symbols, resolve

SIMPLE_DIFF = """diff --git a/pkg/mod.py b/pkg/mod.py
index 1111111..2222222 100644
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -10,6 +10,7 @@ def outer():
     a = 1
-    b = 2
+    b = 3
+    c = 4
     return a
"""

MULTI_DIFF = """diff --git a/pkg/mod.py b/pkg/mod.py
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -1,2 +1,2 @@
-x = 1
+x = 2
 y = 2
diff --git a/pkg/new.py b/pkg/new.py
--- /dev/null
+++ b/pkg/new.py
@@ -0,0 +1,2 @@
+a = 1
+b = 2
"""

FIXTURE_SOURCE = """class A:
    def m(self):
        b = 2
        return b


def f():
    return 2
"""

FIXTURE_DIFF = """diff --git a/pkg/mod.py b/pkg/mod.py
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -1,4 +1,5 @@
 class A:
     def m(self):
-        b = 2
+        b = 3
+        c = 4
         return b
"""


class PatchParseTests(unittest.TestCase):
    def test_single_hunk_anchors(self) -> None:
        files = parse_patch(SIMPLE_DIFF)
        self.assertEqual(len(files), 1)
        fp = files[0]
        self.assertEqual(fp.path, "pkg/mod.py")
        self.assertEqual((fp.added, fp.removed), (2, 1))
        self.assertEqual(fp.anchors(), [11])

    def test_multi_file_and_added_file(self) -> None:
        files = parse_patch(MULTI_DIFF)
        self.assertEqual([f.path for f in files], ["pkg/mod.py", "pkg/new.py"])
        self.assertTrue(files[1].is_added)
        self.assertEqual(files[1].added, 2)
        # An insertion at the very top anchors to line 1, never line 0.
        self.assertEqual(files[1].anchors(), [1])

    def test_empty_patch(self) -> None:
        self.assertEqual(parse_patch(""), [])

    def test_no_newline_marker_is_ignored(self) -> None:
        diff = (
            "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n\\ No newline at end of file\n+b\n"
        )
        files = parse_patch(diff)
        self.assertEqual(files[0].anchors(), [1])


class SymbolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = python_symbols(FIXTURE_SOURCE)

    def test_nested_method_wins(self) -> None:
        sym = resolve(self.table, 3)
        assert sym is not None
        self.assertEqual(sym.qualname, "A.m")
        self.assertEqual(sym.kind, "method")

    def test_module_level_function(self) -> None:
        sym = resolve(self.table, 8)
        assert sym is not None
        self.assertEqual(sym.qualname, "f")
        self.assertEqual(sym.kind, "function")

    def test_class_body(self) -> None:
        sym = resolve(self.table, 1)
        assert sym is not None
        self.assertEqual(sym.qualname, "A")

    def test_out_of_range_is_none(self) -> None:
        self.assertIsNone(resolve(self.table, 99))

    def test_syntax_error_yields_empty_table(self) -> None:
        self.assertEqual(python_symbols("def broken(:\n"), [])

    def test_async(self) -> None:
        table = python_symbols("async def g():\n    return 1\n")
        sym = resolve(table, 2)
        assert sym is not None
        self.assertEqual(sym.kind, "async_function")


class SnapshotTests(unittest.TestCase):
    def _make_tar(self, prefix: str, files: dict[str, str]) -> Path:
        tmp = Path(tempfile.mkdtemp())
        target = tmp / "snap.tgz"
        with tarfile.open(target, "w:gz") as tar:
            for name, content in files.items():
                data = content.encode("utf-8")
                info = tarfile.TarInfo(f"{prefix}{name}")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return target

    def test_reads_with_common_prefix(self) -> None:
        tar_path = self._make_tar("repo-abc/", {"pkg/mod.py": "x = 1\n"})
        with Snapshot(tar_path) as snap:
            self.assertEqual(snap.read_text("pkg/mod.py"), "x = 1\n")
            self.assertTrue(snap.exists("pkg/mod.py"))
            self.assertFalse(snap.exists("nope.py"))
            self.assertEqual(snap.names(), ["pkg/mod.py"])

    def test_reads_directory(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "pkg").mkdir()
        (root / "pkg" / "mod.py").write_text("y = 2\n", encoding="utf-8")
        with Snapshot(root) as snap:
            self.assertEqual(snap.read_text("pkg/mod.py"), "y = 2\n")

    def test_binary_returns_none(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "blob.py").write_bytes(b"\x00\x01\x02")
        with Snapshot(root) as snap:
            self.assertIsNone(snap.read_text("blob.py"))

    def test_read_all_text_one_pass(self) -> None:
        tar_path = self._make_tar(
            "repo-abc/",
            {"pkg/a.py": "a = 1\n", "pkg/b.py": "b = 2\n", "notes.md": "# hi\n"},
        )
        with Snapshot(tar_path) as snap:
            everything = snap.read_all_text()
            self.assertEqual(
                everything, {"pkg/a.py": "a = 1\n", "pkg/b.py": "b = 2\n", "notes.md": "# hi\n"}
            )
            only_py = snap.read_all_text(lambda name: name.endswith(".py"))
            self.assertEqual(set(only_py), {"pkg/a.py", "pkg/b.py"})

    def test_read_all_text_from_directory_matches_names(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "pkg").mkdir()
        (root / "pkg" / "mod.py").write_text("z = 3\n", encoding="utf-8")
        with Snapshot(root) as snap:
            self.assertEqual(snap.read_all_text(), {"pkg/mod.py": "z = 3\n"})

    def test_subset_text_strips_the_archive_prefix(self) -> None:
        tar_path = self._make_tar(
            "repo-abc/",
            {"pkg/a.py": "a = 1\n", "pkg/b.py": "b = 2\n"},
        )
        with Snapshot(tar_path) as snap:
            self.assertEqual(snap.subset_text(["pkg/b.py"]), {"pkg/b.py": "b = 2\n"})
            self.assertEqual(snap.subset_text(["pkg/nope.py"]), {})

    def test_construction_does_not_decompress(self) -> None:
        """A caller that only needs `read_all_text` must not pay for an index."""
        tar_path = self._make_tar("repo-abc/", {"pkg/a.py": "a = 1\n"})
        with Snapshot(tar_path) as snap:
            self.assertIsNone(snap._members)
            snap.read_all_text()
            self.assertIsNone(snap._members)


class EndToEndTests(unittest.TestCase):
    def test_gold_record_from_fixture(self) -> None:
        root = Path(tempfile.mkdtemp())
        snap = root / "snapshots" / "repo__repo-1"
        (snap / "pkg").mkdir(parents=True)
        (snap / "pkg" / "mod.py").write_text(FIXTURE_SOURCE, encoding="utf-8")

        tasks = root / "tasks.jsonl"
        tasks.write_text(
            json.dumps(
                {
                    "instance_id": "repo__repo-1",
                    "repo": "repo/repo",
                    "base_commit": "deadbeef",
                    "patch": FIXTURE_DIFF,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        out = root / "gold.jsonl"
        stats = run(tasks, out, root / "snapshots", quiet=True)
        self.assertEqual(stats["tasks"], 1)
        self.assertEqual(stats["tasks_with_symbols"], 1)

        record = json.loads(out.read_text(encoding="utf-8").strip())
        entry = record["files"][0]
        self.assertEqual(entry["path"], "pkg/mod.py")
        self.assertEqual(entry["language"], "python")
        self.assertEqual(entry["anchors"], [3])
        self.assertEqual(len(entry["symbols"]), 1)
        self.assertEqual(entry["symbols"][0]["qualname"], "A.m")
        self.assertEqual(entry["unresolved_anchors"], 0)

    def test_missing_snapshot_is_reported_not_dropped(self) -> None:
        root = Path(tempfile.mkdtemp())
        tasks = root / "tasks.jsonl"
        tasks.write_text(
            json.dumps(
                {
                    "instance_id": "repo__ghost-1",
                    "repo": "repo/repo",
                    "base_commit": "deadbeef",
                    "patch": FIXTURE_DIFF,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        out = root / "gold.jsonl"
        stats = run(tasks, out, root / "snapshots", quiet=True)
        self.assertEqual(stats["tasks"], 1)
        self.assertEqual(stats["tasks_with_symbols"], 0)


if __name__ == "__main__":
    unittest.main()
