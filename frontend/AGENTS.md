# Frontend Agent Rules

These rules apply to files under `frontend/`.

## Scope

- Use React and Vite.
- Use `bun` for package management and scripts.
- Build the actual application workflow, not a marketing page.
- Keep UI focused on upload, processing status, call list, and call detail.

## UX Rules

- Upload must not imply processing is instant.
- Show queued, processing, completed, and failed states clearly.
- Surface backend errors in client-safe language.
- Keep layouts responsive without decorative complexity.
- Do not add UI copy that explains implementation details to the user.

## API Integration

- Keep API base URL configurable.
- Do not hardcode production URLs.
- Treat backend responses as contracts; type them where practical.

## Testing

- Frontend checks/tests must run through `bun`.
- Prefer focused smoke and component tests over broad brittle snapshots.

## Holdout Boundary

- Hard rule: frontend agents must not open, read, search, diff, or modify anything under `holdout/`.
- Frontend agents should not inspect holdout tests, expected outputs, or scoring internals.
- Frontend work should be validated through UI behavior and API contracts, not holdout answers.
