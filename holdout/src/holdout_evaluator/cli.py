from __future__ import annotations

import argparse
from pathlib import Path

from holdout_evaluator.evaluator import evaluate_case, evaluate_suite, write_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic holdout evaluation.")
    parser.add_argument("--public-case", type=Path)
    parser.add_argument("--actual", type=Path)
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--public-cases-dir", type=Path)
    parser.add_argument("--actual-dir", type=Path)
    parser.add_argument("--expected-dir", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.public_cases_dir or args.actual_dir or args.expected_dir:
        if not (args.public_cases_dir and args.actual_dir and args.expected_dir):
            raise SystemExit("suite mode requires --public-cases-dir, --actual-dir, and --expected-dir")
        result = evaluate_suite(
            public_cases_dir=args.public_cases_dir,
            actual_dir=args.actual_dir,
            expected_dir=args.expected_dir,
        )
    else:
        if not (args.public_case and args.actual and args.expected):
            raise SystemExit("case mode requires --public-case, --actual, and --expected")
        result = evaluate_case(
            public_case_path=args.public_case,
            actual_path=args.actual,
            expected_path=args.expected,
        )
    write_report(result, args.report)
    results = result if isinstance(result, list) else [result]
    return 0 if all(item.passed for item in results) else 1
