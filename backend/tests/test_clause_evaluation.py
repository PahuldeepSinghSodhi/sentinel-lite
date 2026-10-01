"""Check clause-evaluation denominators and small-sample intervals."""
import unittest

from app.evaluation.clause_matching import _score, wilson


class ClauseEvaluationTests(unittest.TestCase):
    def test_wilson_does_not_turn_four_successes_into_certainty(self):
        self.assertEqual(wilson(4, 4), [0.5101, 1])
        self.assertIsNone(wilson(0, 0))

    def test_wrong_displayed_clause_counts_against_precision(self):
        cases = [
            {"suggested": True, "correct": True, "expected_phrase": [{"phrase": "A"}]},
            {"suggested": True, "correct": False, "expected_phrase": []},
            {"suggested": False, "correct": True, "expected_phrase": []},
        ]
        result = _score(cases)
        self.assertEqual(result["wrong_clause"], 1)
        self.assertEqual(result["displayed_precision"], 0.5)
        self.assertEqual(result["applicable_recall"], 1.0)
        self.assertEqual(result["abstention_rate"], 0.3333)


if __name__ == "__main__":
    unittest.main()
