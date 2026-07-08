from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvaluationResult:
    case_id: str
    passed: bool
    checked_fields: tuple[str, ...]
    mismatched_fields: tuple[str, ...]

    def to_report(self) -> dict[str, Any]:
        return {
            "total_cases": 1,
            "passed_cases": 1 if self.passed else 0,
            "failed_cases": 0 if self.passed else 1,
            "cases": [
                {
                    "case_id": self.case_id,
                    "passed": self.passed,
                    "checked_fields": list(self.checked_fields),
                    "mismatched_fields": list(self.mismatched_fields),
                }
            ],
        }


def evaluate_case(
    *,
    public_case_path: Path,
    actual_path: Path,
    expected_path: Path,
) -> EvaluationResult:
    public_case = _read_json(public_case_path)
    actual = _read_json(actual_path)
    expected = _read_json(expected_path)

    case_id = _require_string(public_case, "id", public_case_path)
    expected_output = _require_mapping(expected, "expected_output", expected_path)
    actual_output = _require_mapping(actual, "output", actual_path)

    checked_fields = tuple(sorted(expected_output.keys()))
    mismatched_fields = tuple(
        field
        for field in checked_fields
        if actual_output.get(field) != expected_output[field]
    )

    return EvaluationResult(
        case_id=case_id,
        passed=not mismatched_fields,
        checked_fields=checked_fields,
        mismatched_fields=mismatched_fields,
    )


def write_report(result: EvaluationResult, report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(result.to_report(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} is not valid JSON") from error

    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _require_mapping(value: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    child = value.get(key)
    if not isinstance(child, dict):
        raise ValueError(f"{path} must contain object field {key!r}")
    return child


def _require_string(value: dict[str, Any], key: str, path: Path) -> str:
    child = value.get(key)
    if not isinstance(child, str) or not child:
        raise ValueError(f"{path} must contain non-empty string field {key!r}")
    return child
