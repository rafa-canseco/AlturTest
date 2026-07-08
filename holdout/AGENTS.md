# Holdout Agent Rules

These rules apply to files under `holdout/`.

The holdout suite exists to evaluate AI output quality without leaking the expected answers to the implementation agents or the model being evaluated.

## Hard Access Rule

- Only the evaluator and orchestrator may open, read, search, diff, or modify files under `holdout/`.
- All other AI instances must treat `holdout/` as off limits, even for public-looking files.
- If another instance needs holdout feedback, it must ask the orchestrator for a filtered summary.
- Before editing holdout files, the evaluator must create or switch to a clean branch for the active Linear ticket.
- Evaluator agents must only perform holdout/evaluation-owned work assigned to them.
- Do not edit backend, frontend, or docs files unless the orchestrator explicitly approves it for the active ticket.

## Roles

### Evaluator

The evaluator may create, inspect, and maintain:

- holdout input cases;
- expected outputs;
- scoring logic;
- aggregate reports.

The evaluator must keep expected answers out of implementation prompts, PR summaries, and application code.

### Implementation Agents

Backend, frontend, setup, and architecture agents may not inspect:

- expected output fixtures;
- scoring keys;
- hidden rubrics;
- evaluator-only notes;
- diffs that reveal expected labels or exact expected summaries.

Implementation agents may receive only:

- aggregate scores;
- category-level failures;
- examples of model behavior that do not reveal hidden expected answers verbatim;
- orchestrator-written guidance about what behavior to improve.

## Directory Boundary

Use this intended structure when the holdout suite is implemented:

```text
holdout/
  public_cases/      # inputs that implementation agents may read
  expected/          # evaluator/orchestrator only
  scoring/           # evaluator/orchestrator only
  reports/           # safe aggregate outputs
```

Implementation agents may read `public_cases/` and `reports/`.
Implementation agents must not read `expected/` or `scoring/`.

## Evaluation Flow

1. The evaluator prepares public input cases and private expected outputs.
2. The implementation pipeline receives only the public input case.
3. The pipeline produces transcript analysis output.
4. The evaluator compares actual output to private expected output.
5. The evaluator writes an aggregate report.
6. The orchestrator gives implementation agents only the minimum useful feedback.

Good feedback:

- "Sentiment is over-classifying neutral calls as positive."
- "Next action is missing when the customer asks for a follow-up."
- "Pricing-objection tags are under-detected across three cases."

Bad feedback:

- "For case 004 the expected tag is `pricing_objection`."
- "The expected summary sentence is: ..."
- "Open `expected/case_004.json` and match it."

## Prompt Hygiene

- Never include expected outputs in prompts.
- Never tune prompts against a single leaked expected answer.
- Never copy holdout expected text into application fixtures.
- If a holdout answer leaks, mark that case contaminated and replace it.

## Reporting

Reports should favor aggregate signals:

- tag precision/recall by category;
- invalid schema count;
- missing next-action count;
- summary factuality notes;
- provider errors;
- regressions by prompt version.

Reports should not expose private expected answers unless the orchestrator explicitly opens an evaluator-only review.
