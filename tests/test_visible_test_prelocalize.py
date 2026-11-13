"""The visible-test hook must import without the Kaggle harness present."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ImportTests(unittest.TestCase):
    def test_install_is_callable_without_swegemma(self):
        import tools.visible_test_prelocalize as hook

        self.assertTrue(callable(hook.install))


if __name__ == "__main__":
    unittest.main()
