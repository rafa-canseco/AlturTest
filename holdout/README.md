# Altur Holdout Evaluator

This package contains evaluator-only tooling for the holdout suite. It is scoped
to `ALT-19` and intentionally includes no real hidden cases or private expected
answers.

## Boundary

- `public_cases/`: public input cases that may be shared with implementation agents.
- `expected/`: private expected outputs for evaluator/orchestrator use only.
- `scoring/`: evaluator-only scoring notes or logic.
- `reports/`: aggregate reports safe to share when they do not expose private answers.

The deterministic smoke test builds temporary public, actual, and expected files
at test time. It verifies evaluator behavior without committing hidden expected
answers.

## Commands

```sh
uv run python -m unittest discover -s tests
uv run holdout-evaluate --public-case public_cases/example.json --actual actual.json --expected expected/private.json --report reports/report.json
```
