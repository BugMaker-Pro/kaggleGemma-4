import unittest

from tools.rank_with_topology_surplus import topology_columns


class TopologySurplusTests(unittest.TestCase):
    def test_columns_have_real_null_and_surplus(self):
        context = {"instance_id": "x", "files": ["a", "a", "b", "b", "c", "c"],
                   "edges": [[0, 5]], "orders": {"metadata": list(range(6))}}
        rows = topology_columns(context, list(range(6)))
        self.assertEqual(rows[5][0], 1.0)
        self.assertAlmostEqual(rows[5][2], 1.0 - rows[5][1])


if __name__ == "__main__":
    unittest.main()
