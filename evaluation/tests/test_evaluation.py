import json
import tempfile
import unittest
from pathlib import Path

from evaluation.run_evaluation import align, evaluate_dataset, normalize_text


class EvaluationTests(unittest.TestCase):
    def test_persian_normalization(self):
        self.assertEqual(normalize_text("كیفیت ۱۲۳"), "کیفیت 123")

    def test_alignment_counts_insertions_and_deletions(self):
        distance, operations = align(["الف", "ب", "ج"], ["الف", "ج", "د"])
        self.assertEqual(distance, 2)
        self.assertEqual(sum(item["operation"] != "equal" for item in operations), 2)

    def test_synthetic_dataset_is_not_a_real_accuracy_claim(self):
        fixture = {
            "name": "fixture",
            "version": "1",
            "contains_real_calls": False,
            "samples": [
                {"id": "one", "reference_text": "سلام ۱۲", "hypothesis_text": "سلام 12"}
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "dataset.json"
            path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
            report = evaluate_dataset(fixture, path, 0.75)
        self.assertEqual(report["aggregate"]["wer"], 0)
        self.assertEqual(
            report["quality_claim"]["status"], "NOT_MEASURED_ON_REAL_CALLS"
        )


if __name__ == "__main__":
    unittest.main()
