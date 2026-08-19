import unittest
from app.scoring.confidence import compute_confidence

class TestConfidenceScoring(unittest.TestCase):
    def setUp(self):
        self.high_quality_chunks = [
            {"text": "Project Apollo launched in 1969.", "source": "history.pdf", "chunk_index": 0, "score": 0.95},
            {"text": "Apollo 11 was the first manned mission to land on the Moon.", "source": "history.pdf", "chunk_index": 1, "score": 0.92},
            {"text": "Neil Armstrong and Buzz Aldrin walked on the lunar surface.", "source": "history.pdf", "chunk_index": 2, "score": 0.88}
        ]
        
        self.poor_quality_chunks = [
            {"text": "The quick brown fox jumps over the lazy dog.", "source": "random1.txt", "chunk_index": 0, "score": 0.3},
            {"text": "Python is a popular programming language.", "source": "random2.txt", "chunk_index": 0, "score": 0.25},
            {"text": "The weather today is sunny.", "source": "random3.txt", "chunk_index": 0, "score": 0.15}
        ]

    def test_high_quality_retrieval(self):
        query = "When did Project Apollo launch and who walked on the Moon?"
        answer = "Project Apollo launched in 1969. Neil Armstrong and Buzz Aldrin walked on the lunar surface."
        
        result = compute_confidence(query, self.high_quality_chunks, answer)
        
        self.assertEqual(result["confidence_level"], "high")
        self.assertGreater(result["overall_confidence"], 0.7)
        self.assertEqual(result["source_agreement"], 1.0)
        
        # Check sub-score bounds
        for key in ["retrieval_score", "source_agreement", "coverage_score", "answer_grounding", "overall_confidence"]:
            self.assertTrue(0.0 <= result[key] <= 1.0)

    def test_poor_quality_retrieval(self):
        query = "What is the capital of France?"
        answer = "The capital of France is Paris."
        
        result = compute_confidence(query, self.poor_quality_chunks, answer)
        
        self.assertEqual(result["confidence_level"], "low")
        self.assertLess(result["overall_confidence"], 0.4)
        self.assertLess(result["source_agreement"], 0.5)
        
        # Check sub-score bounds
        for key in ["retrieval_score", "source_agreement", "coverage_score", "answer_grounding", "overall_confidence"]:
            self.assertTrue(0.0 <= result[key] <= 1.0)

    def test_empty_chunks(self):
        result = compute_confidence("test query", [], "test answer")
        self.assertEqual(result["overall_confidence"], 0.0)
        self.assertEqual(result["confidence_level"], "low")

if __name__ == "__main__":
    unittest.main()
