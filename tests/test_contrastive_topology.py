import unittest

from tools.run_contrastive_topology import edge_features


class ContrastiveTopologyTests(unittest.TestCase):
    def test_edge_features_do_not_require_gold(self):
        context = {
            "ids": ["pkg.A.f", "pkg.B.g"],
            "files": ["pkg/a.py", "pkg/b.py"],
            "orders": {"metadata": [0, 1], "body": [1, 0], "dense": [0, 1]},
        }
        values = edge_features(context, 0, 1)
        self.assertEqual(len(values), 14)
        self.assertTrue(all(isinstance(value, float) for value in values))


if __name__ == "__main__":
    unittest.main()
