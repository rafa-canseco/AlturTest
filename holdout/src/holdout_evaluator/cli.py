from __future__ import annotations

import argparse
from pathlib import Path

from holdout_evaluator.evaluator import evaluate_case, write_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one deterministic holdout evaluation case."
    )
    parser.add_argument("--public-case", required=True, type=Path)
    parser.add_argument("--actual", required=True, type=Path)
    parser.add_argument("--expected", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = evaluate_case(
        public_case_path=args.public_case,
        actual_path=args.actual,
        expected_path=args.expected,
    )
    write_report(result, args.report)
    return 0 if result.passed else 1
