# AGENTS.md

Global rules for every AI instance working in this repository.

## Operating Model

- This session is the orchestrator.
- Every implementation instance must work from exactly one Linear ticket.
- Every change must be small enough to review in one pass.
- Do not combine unrelated tickets in one branch, commit, or PR.
- Do not implement work that is not required by the active ticket.
- Stop and ask the orchestrator when scope, ownership, or requirements are unclear.

## Required Workflow

1. Read this root `AGENTS.md`.
2. Read the scoped `AGENTS.md` for the area being changed, if one exists.
3. Confirm the active Linear ticket and intended file scope.
4. Make the smallest coherent change.
5. Run the relevant checks for the touched area.
6. Commit with a ticket-aware, reviewable message.
7. Produce a PR-ready summary.

## PR-Ready Summary

Every AI instance must report:

- Linear ticket ID.
- Files changed.
- What changed.
- Design decisions and tradeoffs.
- Commands/tests run.
- Known risks, skipped checks, or follow-up work.

## Commit Discipline

- Prefer one logical commit per ticket step.
- Commit messages must be concrete and boring.
- Do not include generated noise, broad formatting churn, or unrelated cleanup.
- Do not rewrite history or reset work unless the orchestrator explicitly approves it.
- Do not modify files outside the ticket scope unless the orchestrator approves it first.

## Review Gate

- All AI-produced work requires orchestrator review before merge.
- A ticket is not done just because tests pass.
- A ticket is done when the orchestrator accepts the implementation, tests, and summary.

## Anti-Slop Rules

- Do not add abstractions before there is real duplication or complexity.
- Do not create speculative infrastructure.
- Do not hide important behavior inside helpers with vague names.
- Do not add dependencies without explaining why they are needed.
- Do not create placeholder product code that looks complete but is not wired or tested.
- Do not claim a provider integration works unless it was tested or explicitly mocked.

## Tooling

- Backend and Python tooling use `uv`.
- Frontend tooling uses `bun`.
- Keep env-driven configuration from the beginning.
- Keep local development compatible with later Dockerization.

## Holdout Boundary

- Implementation agents must not inspect holdout expected outputs, scoring keys, or private evaluator fixtures.
- Only the evaluator/orchestrator may inspect or modify hidden expected outputs and scoring logic.
- Implementation agents may receive aggregate failures and behavioral guidance from the orchestrator.
- Never paste hidden expected outputs into prompts, implementation notes, or PR summaries.

