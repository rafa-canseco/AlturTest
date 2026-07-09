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
export SUPABASE_STORAGE_BUCKET="call-audio"
export STORAGE_BACKEND="local"

uv run pytest -m integration
```

If the local Supabase Postgres env var is missing or the local services are not
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

With ElevenLabs configured, the STT worker downloads private audio from Supabase
Storage, sends it to ElevenLabs Speech to Text, stores one transcript in
`call_transcripts`, leaves the call in `processing`, and requeues the job for
the LLM analysis step. The STT worker claims only jobs where
`transcript_exists=false`, so queued analysis jobs are not consumed by the STT
processor.

```sh
uv run python -m app.worker --stage stt
```

With OpenAI configured, the analysis worker claims only jobs where
`transcript_exists=true`, reads the persisted transcript, writes one validated
row to `call_analysis`, then marks the job and call completed. If analysis
already exists for the call, the worker completes the job without calling the
LLM again.

```sh
uv run python -m app.worker --stage analysis
```

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

Call audio storage contract:

- Default backend: local filesystem storage at `.data/storage`, configured with
  `STORAGE_BACKEND=local` and `LOCAL_STORAGE_ROOT=.data/storage`.
- Optional backend: Supabase Storage with `STORAGE_BACKEND=supabase`,
  `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY`.
- Bucket name: `call-audio`. For local storage this is a directory below the
  local storage root; for Supabase Storage this is a private bucket managed by
  the SQL migration.
- Path convention:
  `calls/{call_id}/{original_filename_slug}-{upload_token}.{ext}`.
- Persisted metadata: `storage_bucket`, `storage_path`, `content_type`,
  `file_size_bytes`, and optional `storage_etag`/`storage_version`.

Call ingestion idempotency:

- `POST /calls` accepts an optional `Idempotency-Key` header.
- Without the header, uploads keep the legacy behavior: every valid request
  creates a new call, queued job, and storage object.
- With the header, the backend hashes the key before persistence and computes a
  request fingerprint from the sanitized filename, content type, byte length,
  and SHA-256 content hash. Raw audio is never stored in
  `call_idempotency_keys`.
- A retry with the same key and matching fingerprint returns the existing call
  and does not create another queued job or storage object.
- Reusing the same key for a different fingerprint returns `409 Conflict`.
- The service checks the idempotency mapping before storage upload, then writes
  the call, job, events, and idempotency mapping in one Postgres transaction.
  If storage succeeds but DB persistence fails, the uploaded object is deleted
  as part of the existing cleanup path.

Tradeoff: this implementation avoids duplicate storage on normal completed
retries, but it does not hold a database reservation while uploading the audio.
That keeps uploads simple and avoids long DB locks around object storage calls.
Two concurrent first attempts using the same key can both upload before one DB
transaction wins the unique idempotency key insert; the loser rolls back and
deletes its uploaded object. If stricter concurrent de-duplication becomes
necessary, add a reservation state to `call_idempotency_keys` and carefully
expire abandoned reservations.

Required Supabase env vars:

```sh
DATABASE_URL=
SUPABASE_STORAGE_BUCKET=call-audio
STORAGE_BACKEND=local
LOCAL_STORAGE_ROOT=.data/storage
```

`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are only required when
`STORAGE_BACKEND=supabase`. The local demo path uses Supabase Docker for
Postgres and local disk for audio, so it does not need a Supabase API key.

Required ElevenLabs env vars for real STT:

```sh
ELEVENLABS_API_KEY=
ELEVENLABS_STT_MODEL_ID=scribe_v1
```

`ELEVENLABS_API_KEY` must be provided by the runtime environment. Do not commit
real API keys to source, tests, README files, or local env examples. The default
test suite uses fakes and does not require ElevenLabs credentials or make live
provider calls.

Required OpenAI env vars for real LLM analysis:

```sh
OPENAI_API_KEY=
OPENAI_ANALYSIS_MODEL=gpt-4.1-mini
ANALYSIS_PROMPT_VERSION=altur-analysis-v1
```

`OPENAI_API_KEY` must be provided by the runtime environment. Analysis output is
validated against the `call_analysis` schema before persistence; malformed model
output fails the job with `analysis_failed` and preserves the transcript.

Tests must not require live Supabase. Future repository and storage code should
be written behind interfaces and covered with fakes or mocks by default.
