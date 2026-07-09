from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from holdout_evaluator.evaluator import evaluate_case, evaluate_suite, write_report


class EvaluatorSmokeTest(unittest.TestCase):
    def test_smoke_report_excludes_expected_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            public_case_path = tmp_path / "public_case.json"
            actual_path = tmp_path / "actual.json"
            expected_path = tmp_path / "expected.json"
            report_path = tmp_path / "report.json"

            public_case_path.write_text(
                json.dumps({"id": "smoke-case", "transcript": "Synthetic input."}),
                encoding="utf-8",
            )
            actual_path.write_text(
                json.dumps({"output": {"summary": "synthetic summary"}}),
                encoding="utf-8",
            )
            expected_path.write_text(
                json.dumps({"expected_output": {"summary": "synthetic summary"}}),
                encoding="utf-8",
            )

            result = evaluate_case(
                public_case_path=public_case_path,
                actual_path=actual_path,
                expected_path=expected_path,
            )
            write_report(result, report_path)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(result.passed)
            self.assertEqual(report["passed_cases"], 1)
            self.assertNotIn("expected_output", report)
            self.assertNotIn("synthetic summary", report_path.read_text(encoding="utf-8"))

    def test_suite_report_is_aggregate_and_hides_expected_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            public_dir = tmp_path / "public"
            actual_dir = tmp_path / "actual"
            expected_dir = tmp_path / "expected"
            report_path = tmp_path / "report.json"
            public_dir.mkdir()
            actual_dir.mkdir()
            expected_dir.mkdir()

            (public_dir / "case-a.json").write_text(
                json.dumps({"id": "case-a", "transcript": "Customer asks for refund."}),
                encoding="utf-8",
            )
            (actual_dir / "case-a.json").write_text(
                json.dumps(
                    {
                        "id": "case-a",
                        "output": {
                            "summary": "Customer asks for a refund after a damaged order.",
                            "sentiment": "negative",
                            "next_action": "follow_up",
                            "tags": {
                                "topics": ["damaged order"],
                                "customer_intents": ["request refund"],
                            },
                            "risk_flags": ["churn risk"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (expected_dir / "case-a.json").write_text(
                json.dumps(
                    {
                        "id": "case-a",
                        "expected_output": {
                            "summary_keywords": ["refund", "damaged order"],
                            "sentiment": "negative",
                            "next_action": "follow_up",
                            "tags": {
                                "topics": ["damaged order"],
                                "customer_intents": ["request refund"],
                            },
                            "risk_flags": ["churn risk"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            results = evaluate_suite(
                public_cases_dir=public_dir,
                actual_dir=actual_dir,
                expected_dir=expected_dir,
            )
            write_report(results, report_path)

            report_text = report_path.read_text(encoding="utf-8")
            report = json.loads(report_text)
            self.assertEqual(report["passed_cases"], 1)
            self.assertEqual(report["field_scores"]["tags.topics"]["score"], 1.0)
            self.assertNotIn("expected_output", report_text)
            self.assertNotIn("request refund", report_text)

    def test_missing_expected_tag_fails_without_revealing_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            public_case_path = tmp_path / "public_case.json"
            actual_path = tmp_path / "actual.json"
            expected_path = tmp_path / "expected.json"

            public_case_path.write_text(
                json.dumps({"id": "case-b", "transcript": "Synthetic input."}),
                encoding="utf-8",
            )
            actual_path.write_text(
                json.dumps({"id": "case-b", "output": {"tags": {"risks": []}}}),
                encoding="utf-8",
            )
            expected_path.write_text(
                json.dumps(
                    {
                        "id": "case-b",
                        "expected_output": {"tags": {"risks": ["escalation risk"]}},
                    }
                ),
                encoding="utf-8",
            )

            result = evaluate_case(
                public_case_path=public_case_path,
                actual_path=actual_path,
                expected_path=expected_path,
            )

            self.assertFalse(result.passed)
            self.assertEqual(result.mismatched_fields, ("tags.risks",))


if __name__ == "__main__":
    unittest.main()
