# Altur Holdout Evaluator

This package contains evaluator-only tooling for the holdout suite. It is owned
by evaluator/orchestrator workflow and should not be inspected by implementation
agents.

## Boundary

- `public_cases/`: public input cases that may be shared with implementation agents.
- `expected/`: private expected outputs for evaluator/orchestrator use only.
- `actual_outputs/`: candidate outputs produced by the app or deterministic baselines.
- `scoring/`: evaluator-only scoring notes or logic.
- `reports/`: aggregate reports safe to share when they do not expose private answers.

Reports include aggregate pass/fail, field scores, and mismatched field names.
They intentionally do not include expected values or expected summaries.

The current suite includes small synthetic transcript cases for:

- angry customer escalation;
- damaged order refund/replacement.

The committed baseline outputs are deterministic fixtures for verifying the
evaluator. Real model/provider outputs can be written to another directory and
evaluated against the same private expected files.

## Commands

```sh
uv run python -m unittest discover -s tests
uv run holdout-evaluate \
  --public-cases-dir public_cases \
  --actual-dir actual_outputs/baseline \
  --expected-dir expected \
  --report reports/baseline.json
uv run holdout-evaluate --public-case public_cases/damaged_order_refund.json --actual actual_outputs/baseline/damaged_order_refund.json --expected expected/damaged_order_refund.json --report reports/damaged_order_refund.json
```
