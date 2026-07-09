from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TAG_CATEGORIES = ("topics", "customer_intents", "products", "risks", "outcomes")
SCALAR_FIELDS = ("sentiment", "next_action")


@dataclass(frozen=True)
class FieldScore:
    passed: bool
    checked: int
    matched: int

    @property
    def score(self) -> float:
        if self.checked == 0:
            return 1.0
        return self.matched / self.checked


@dataclass(frozen=True)
class EvaluationResult:
    case_id: str
    passed: bool
    checked_fields: tuple[str, ...]
    mismatched_fields: tuple[str, ...]
    field_scores: dict[str, FieldScore]

    def to_case_report(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "checked_fields": list(self.checked_fields),
            "mismatched_fields": list(self.mismatched_fields),
            "field_scores": {
                field: {
                    "score": round(score.score, 4),
                    "checked": score.checked,
                    "matched": score.matched,
                }
                for field, score in sorted(self.field_scores.items())
            },
        }

    def to_report(self) -> dict[str, Any]:
        return suite_report([self])


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

    if actual.get("id") not in (None, case_id):
        raise ValueError(f"{actual_path} id does not match public case id")
    if expected.get("id") not in (None, case_id):
        raise ValueError(f"{expected_path} id does not match public case id")

    field_scores: dict[str, FieldScore] = {}
    mismatched_fields: list[str] = []

    for field in SCALAR_FIELDS:
        if field in expected_output:
            expected_value = _normalize_scalar(expected_output.get(field))
            actual_value = _normalize_scalar(actual_output.get(field))
            score = FieldScore(
                passed=actual_value == expected_value,
                checked=1,
                matched=1 if actual_value == expected_value else 0,
            )
            field_scores[field] = score
            if not score.passed:
                mismatched_fields.append(field)

    if "summary_keywords" in expected_output:
        expected_keywords = _normalize_list(expected_output["summary_keywords"])
        actual_summary = _normalize_text(actual_output.get("summary"))
        matched = sum(1 for keyword in expected_keywords if keyword in actual_summary)
        score = FieldScore(
            passed=matched == len(expected_keywords),
            checked=len(expected_keywords),
            matched=matched,
        )
        field_scores["summary_keywords"] = score
        if not score.passed:
            mismatched_fields.append("summary_keywords")

    expected_tags = _optional_mapping(expected_output, "tags", expected_path)
    actual_tags = _optional_mapping(actual_output, "tags", actual_path)
    for category in TAG_CATEGORIES:
        if category not in expected_tags:
            continue
        expected_values = set(_normalize_list(expected_tags[category]))
        actual_values = set(_normalize_list(actual_tags.get(category, [])))
        matched = len(expected_values & actual_values)
        score = FieldScore(
            passed=matched == len(expected_values),
            checked=len(expected_values),
            matched=matched,
        )
        field_name = f"tags.{category}"
        field_scores[field_name] = score
        if not score.passed:
            mismatched_fields.append(field_name)

    if "risk_flags" in expected_output:
        expected_values = set(_normalize_list(expected_output["risk_flags"]))
        actual_values = set(_normalize_list(actual_output.get("risk_flags", [])))
        matched = len(expected_values & actual_values)
        score = FieldScore(
            passed=matched == len(expected_values),
            checked=len(expected_values),
            matched=matched,
        )
        field_scores["risk_flags"] = score
        if not score.passed:
            mismatched_fields.append("risk_flags")

    checked_fields = tuple(sorted(field_scores.keys()))
    return EvaluationResult(
        case_id=case_id,
        passed=not mismatched_fields,
        checked_fields=checked_fields,
        mismatched_fields=tuple(mismatched_fields),
        field_scores=field_scores,
    )


def evaluate_suite(
    *,
    public_cases_dir: Path,
    actual_dir: Path,
    expected_dir: Path,
) -> list[EvaluationResult]:
    public_case_paths = sorted(public_cases_dir.glob("*.json"))
    if not public_case_paths:
        raise ValueError(f"{public_cases_dir} contains no JSON cases")

    results: list[EvaluationResult] = []
    for public_case_path in public_case_paths:
        case_id = _require_string(_read_json(public_case_path), "id", public_case_path)
        results.append(
            evaluate_case(
                public_case_path=public_case_path,
                actual_path=actual_dir / f"{case_id}.json",
                expected_path=expected_dir / f"{case_id}.json",
            )
        )
    return results


def write_report(result: EvaluationResult | list[EvaluationResult], report_path: Path) -> None:
    results = [result] if isinstance(result, EvaluationResult) else result
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(suite_report(results), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def suite_report(results: list[EvaluationResult]) -> dict[str, Any]:
    total_cases = len(results)
    passed_cases = sum(1 for result in results if result.passed)
    field_totals: dict[str, dict[str, int]] = {}
    for result in results:
        for field, score in result.field_scores.items():
            totals = field_totals.setdefault(field, {"checked": 0, "matched": 0})
            totals["checked"] += score.checked
            totals["matched"] += score.matched

    return {
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "failed_cases": total_cases - passed_cases,
        "field_scores": {
            field: {
                "score": round(
                    1.0 if totals["checked"] == 0 else totals["matched"] / totals["checked"],
                    4,
                ),
                "checked": totals["checked"],
                "matched": totals["matched"],
            }
            for field, totals in sorted(field_totals.items())
        },
        "cases": [result.to_case_report() for result in results],
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"{path} does not exist") from error
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


def _optional_mapping(value: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    child = value.get(key, {})
    if not isinstance(child, dict):
        raise ValueError(f"{path} field {key!r} must be an object when present")
    return child


def _require_string(value: dict[str, Any], key: str, path: Path) -> str:
    child = value.get(key)
    if not isinstance(child, str) or not child:
        raise ValueError(f"{path} must contain non-empty string field {key!r}")
    return child


def _normalize_scalar(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return ""
    return _normalize_text(value)


def _normalize_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_normalize_text(item) for item in value if isinstance(item, str) and item.strip()]


def _normalize_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.lower().strip().split())
