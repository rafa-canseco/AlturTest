# Docs Agent Rules

These rules apply to files under `docs/`.

## Scope

- Documentation must help the reviewer run, evaluate, and discuss the project.
- Prefer concrete decisions and tradeoffs over generic explanations.
- Keep take-home time constraints visible.
- Document what exists, what is mocked, and what would change in production.

## Required Topics

- Local setup with `uv` and `bun`.
- Optional Docker path once services exist.
- Environment variables.
- Architecture and async processing flow.
- Prompt design and tagging schema.
- Holdout evaluation strategy.
- Scaling to 10k calls/day.
- Bottlenecks.
- Production changes.
- PII handling and retention.

## Holdout Boundary

- Hard rule: docs agents must not open, read, search, diff, or modify anything under `holdout/`.
- Docs may explain the evaluation process.
- Docs must not reveal private expected outputs, hidden rubrics, or scoring keys.
- Public examples must be synthetic and safe to expose.
