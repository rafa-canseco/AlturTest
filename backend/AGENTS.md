# Backend Agent Rules

These rules apply to files under `backend/`.

## Scope

- Before editing backend files, create or switch to a clean branch for the active Linear ticket.
- Backend agents must only perform backend-owned work assigned to them.
- Do not edit frontend, docs, or holdout files unless the orchestrator explicitly approves it for the active ticket.
- Use FastAPI for the HTTP API.
- Use `uv` for dependency management, scripts, and tests.
- Keep API handlers thin; put business logic in services.
- Keep provider integrations behind interfaces that can be mocked in tests.
- Persist state transitions explicitly and make failures visible to callers.

## Architecture

- Upload requests must return quickly.
- Long-running STT and LLM work belongs in the worker path, not inside request handlers.
- Configuration must come from env vars or typed settings.
- Do not hardcode localhost, local paths, API keys, or provider names deep in business logic.
- Design for local storage first, with a clear path to object storage later.

## Testing

- Backend tests must run through `uv`.
- Use mocks for ElevenLabs and LLM providers by default.
- Test success paths, invalid input, provider failure, and malformed model output.
- Do not make live provider calls in normal test runs.

## Holdout Boundary

- Hard rule: backend agents must not open, read, search, diff, or modify anything under `holdout/`.
- Backend agents may run public unit/integration tests.
- Backend agents must not open holdout expected outputs or scoring internals.
- If holdout evaluation fails, wait for orchestrator-provided failure summaries.
