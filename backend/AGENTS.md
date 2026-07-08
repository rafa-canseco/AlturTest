# Backend Agent Rules

These rules apply to files under `backend/`.

## Scope

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
