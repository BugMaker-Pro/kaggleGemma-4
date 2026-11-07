import unittest

from tools.select_graph_intervention import selector_features


class GraphInterventionSelectorTests(unittest.TestCase):
    def test_feature_construction_is_label_free(self):
        context = {"instance_id": "x", "files": ["a", "a", "b", "b", "c", "c"],
                   "edges": [[0, 5]], "orders": {"metadata": list(range(6))}}
        plain, counterfactual, uncertainty, order = selector_features(context, "metadata")
        self.assertTrue(plain)
        self.assertTrue(counterfactual)
        self.assertTrue(uncertainty)
        self.assertEqual(len(order), 6)


if __name__ == "__main__":
    unittest.main()
