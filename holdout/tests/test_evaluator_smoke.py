from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from holdout_evaluator.evaluator import evaluate_case, write_report


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


if __name__ == "__main__":
    unittest.main()
