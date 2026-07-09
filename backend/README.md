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

The default test command runs unit tests only and does not require Supabase.

Opt-in local Supabase integration tests:

```sh
supabase start
supabase db reset

export DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:54322/postgres"
export SUPABASE_URL="http://127.0.0.1:54321"
export SUPABASE_SERVICE_ROLE_KEY="<service_role key from supabase status>"
export SUPABASE_STORAGE_BUCKET="call-audio"

uv run pytest -m integration
```

If the local Supabase env vars are missing or the local services are not
reachable, integration tests skip with a clear reason instead of failing the
normal unit suite.

Configuration is loaded from environment variables. See `.env.example` for local values.

## Worker

Run the async call processing worker with:

```sh
uv run python -m app.worker
```

The default worker claims queued jobs but uses a not-configured processor until
the required Supabase and ElevenLabs env vars are present. A claimed job will
fail safely with `processor_not_configured` instead of being marked completed
without transcript or analysis output.

For local queue plumbing smoke checks only, process at most one queued job with
the dev fake processor:

```sh
uv run python -m app.worker --once --dev-fake-processor
```

With ElevenLabs configured, the worker downloads private audio from Supabase
Storage, sends it to ElevenLabs Speech to Text, stores one transcript in
`call_transcripts`, and leaves the call in `processing` for the later LLM
analysis step. OpenAI/LLM analysis and `call_analysis` writes are intentionally
not implemented yet.

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
- `call_transcripts` stores one validated STT result per call. This lets the
  worker preserve transcript value when STT succeeds but LLM analysis fails.
- `call_analysis` stores one validated LLM result per call, including
  prompt/model metadata and the raw structured LLM payload for debugging.
- `tag_overrides` stores human corrections separately from model output.
- `processing_events` is intentionally lightweight and only for status or
  retry/debug events.

Allowed call statuses are `queued`, `processing`, `completed`, and `failed`.
Allowed job statuses are `queued`, `processing`, `completed`, and `failed`.
When retrying a failed call or job, worker code must clear the corresponding
failure fields (`failed_at`, error code, and error message) before moving it
back to `queued` or `processing`.

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

Required ElevenLabs env vars for real STT:

```sh
ELEVENLABS_API_KEY=
ELEVENLABS_STT_MODEL_ID=scribe_v1
```

`ELEVENLABS_API_KEY` must be provided by the runtime environment. Do not commit
real API keys to source, tests, README files, or local env examples. The default
test suite uses fakes and does not require ElevenLabs credentials or make live
provider calls.

Tests must not require live Supabase. Future repository and storage code should
be written behind interfaces and covered with fakes or mocks by default.

Production improvement: call ingestion does not implement `Idempotency-Key`
semantics yet. A retried upload request can create a new `call_id`; production
retry safety should add an idempotency table or request-key mapping before
clients rely on automatic upload retries.
