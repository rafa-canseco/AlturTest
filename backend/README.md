# Altur Backend

FastAPI backend managed with `uv`.

## Setup

```sh
uv sync
```

## Run locally

```sh
uv run uvicorn app.main:app --reload
```

## Test

```sh
uv run pytest
```

Configuration is loaded from environment variables. See `.env.example` for local values.

## Supabase Contract

The initial Postgres schema lives in
`supabase/migrations/20260708232058_initial_call_schema.sql`.

Schema decisions:

- `calls` is the user-visible source of truth for upload metadata, storage
  location, status, and client-safe failure fields.
- `call_processing_jobs` is a Postgres-backed queue. Workers should claim
  queued jobs in a transaction with `FOR UPDATE SKIP LOCKED`.
- `call_analysis` stores one validated STT/LLM result per call, including
  prompt/model metadata and the raw structured LLM payload for debugging.
- `tag_overrides` stores human corrections separately from model output.
- `processing_events` is intentionally lightweight and only for status or
  retry/debug events.

Allowed call statuses are `queued`, `processing`, `completed`, and `failed`.
Allowed job statuses are `queued`, `processing`, `completed`, and `failed`.

Supabase Storage contract:

- Bucket name: `call-audio`.
- Access: private; only backend and worker service credentials should access
  audio.
- Path convention:
  `calls/{call_id}/{original_filename_slug}-{upload_token}.{ext}`.
- Persisted metadata: `storage_bucket`, `storage_path`, `content_type`,
  `file_size_bytes`, and optional `storage_etag`/`storage_version`.

Required Supabase env vars:

```sh
DATABASE_URL=
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_STORAGE_BUCKET=call-audio
```

Tests must not require live Supabase. Future repository and storage code should
be written behind interfaces and covered with fakes or mocks by default.
