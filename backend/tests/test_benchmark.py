"""The larger benchmark stays reproducible and exposes detector tradeoffs."""
import unittest

from app.evaluation.synthetic import benchmark, run


class SyntheticBenchmarkTests(unittest.TestCase):
    def test_labelled_dataset_and_detection(self):
        transactions, rates, labels = benchmark()
        self.assertEqual(len(transactions), 240)
        self.assertEqual(len(labels), 8)
        self.assertEqual(len(rates), 4)
        metrics = run()
        self.assertEqual(metrics["transactions"], 240)
        self.assertGreaterEqual(metrics["recall"], 0.9)
        self.assertGreaterEqual(metrics["precision"], 0.7)
        self.assertGreaterEqual(metrics["false_positives"], 1)
        self.assertGreaterEqual(metrics["scan_duration_ms"], 0)


if __name__ == "__main__":
    unittest.main()
