import unittest

from tools.run_null_calibrated_graph import calibrated_order, residual_order


class NullCalibratedGraphTests(unittest.TestCase):
    def test_calibrated_excludes_null_certain_neighbour(self):
        order = list(range(10))
        null = [0.0] * 10
        null[7] = 1.0
        self.assertEqual(calibrated_order(order, {6, 7, 8}, null),
                         [0, 1, 2, 3, 4, 6, 8, 5, 7, 9])

    def test_residual_order_prefers_larger_surplus(self):
        order = list(range(10))
        null = [0.0] * 10
        null[7], null[8] = 0.4, 0.2
        self.assertEqual(residual_order(order, {7, 8}, null),
                         [0, 1, 2, 3, 4, 8, 7, 5, 6, 9])


if __name__ == "__main__":
    unittest.main()
