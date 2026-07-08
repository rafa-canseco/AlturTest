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

Supabase is managed through the Supabase CLI. The local project config lives in
`supabase/config.toml`, and the initial schema migration lives in
`supabase/migrations/20260708232058_initial_call_schema.sql`.

Local setup:

```sh
docker info
supabase start
supabase db reset
```

`supabase start` requires Docker Desktop to be running. The CLI applies pending
migrations when the local stack starts, and `supabase db reset` recreates the
local database from the committed migrations.

Remote setup:

```sh
supabase login
supabase link --project-ref <project-ref>
supabase db push
```

CI should run the same migration command after merge, with
`SUPABASE_ACCESS_TOKEN`, `SUPABASE_DB_PASSWORD`, and the linked project config
available to the job. Do not make schema changes directly in the Supabase
Dashboard once migrations are in use.

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
- Creation: managed by the SQL migration through `storage.buckets`; no manual
  dashboard step is required.
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
