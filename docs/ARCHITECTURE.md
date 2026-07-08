# Architecture

## Goal

Build a small but production-shaped call analyzer for sales recordings. The core workflow is:

```text
audio upload -> queued call -> async STT -> LLM analysis -> persisted result -> review UI
```

The design optimizes for the take-home constraints:

- uploads must return immediately;
- calls can be up to 30 minutes long;
- users may upload many calls in a short period;
- AI output quality must be evaluated over time;
- the system should be easy to run and explain.

## System Components

```text
React/Vite frontend
  -> FastAPI backend
    -> Supabase Storage for audio
    -> Supabase Postgres for records, jobs, analysis, overrides

Python worker
  -> Supabase Postgres for queued jobs
  -> Supabase Storage for audio input
  -> ElevenLabs STT
  -> OpenAI LLM analysis
  -> Supabase Postgres for results

Holdout evaluator
  -> public input cases
  -> private expected outputs
  -> aggregate quality reports
```

### Frontend

- React/Vite managed with `bun`.
- Uploads WAV/MP3 files to the backend.
- Displays call list and detail views.
- Handles `queued`, `processing`, `completed`, and `failed` states.
- Polling is acceptable for the take-home; server-sent events or realtime updates can be added later.

### Backend API

- FastAPI managed with `uv`.
- Owns request validation, auth boundary if added later, storage writes, and database records.
- Does not run STT or LLM work inside upload requests.
- Returns a `call_id` immediately after persisting the audio and queueing work.

### Worker

- Python process managed with `uv`.
- Polls Supabase Postgres for queued jobs.
- Claims work atomically, updates status, calls providers, persists outputs.
- Handles retries and records failure reasons.

### Supabase Postgres

Postgres is the source of truth for:

- call metadata;
- processing state;
- job queue rows;
- transcripts;
- LLM summaries and tags;
- user tag overrides;
- optional processing events for audit/debugging.

### Supabase Storage

Audio files are stored in Supabase Storage from the start. The app does not maintain a separate local filesystem storage mode. Local development uses the same storage abstraction and Supabase env vars.

### ElevenLabs STT

ElevenLabs is used for speech-to-text. The integration should be isolated behind a provider adapter so tests can run without live provider calls.

When available, store:

- transcript text;
- language/model metadata;
- timestamps;
- speaker or diarization metadata.

### OpenAI LLM Analysis

OpenAI is used for offline transcript analysis. The LLM output must be structured and validated before persistence.

The analysis should produce:

- summary;
- sales tags;
- customer intent;
- sentiment or mood;
- next action;
- optional risk flags.

Prompts must be versioned so future prompt changes can be evaluated against holdout results.

## Primary Workflow

1. User uploads a WAV/MP3 file through the frontend.
2. Backend validates file type and metadata.
3. Backend uploads the audio to Supabase Storage.
4. Backend creates a `calls` row with status `queued`.
5. Backend creates a `call_processing_jobs` row.
6. Backend returns immediately with `call_id` and status.
7. Worker atomically claims a queued job.
8. Worker marks the call/job as `processing`.
9. Worker downloads or streams the audio from Supabase Storage.
10. Worker sends audio to ElevenLabs STT.
11. Worker sends transcript to OpenAI for structured analysis.
12. Worker validates LLM output against the expected schema.
13. Worker persists transcript, summary, tags, model metadata, and prompt version.
14. Worker marks the call as `completed`, or `failed` with a client-safe error.
15. Frontend polls and renders the final details.

## API Contracts

Initial endpoints:

```text
POST /calls
GET /calls
GET /calls/{call_id}
```

Later endpoints:

```text
PATCH /calls/{call_id}/tags
GET /calls/{call_id}/export
```

### `POST /calls`

Accepts multipart audio upload.

Responsibilities:

- validate content type and size;
- store audio in Supabase Storage;
- persist call metadata;
- queue a processing job;
- return quickly.

Response shape:

```json
{
  "id": "call_123",
  "status": "queued",
  "filename": "sales-call.mp3",
  "uploaded_at": "2026-07-08T00:00:00Z"
}
```

### `GET /calls`

Returns call summaries for list views.

Include:

- id;
- filename;
- upload timestamp;
- status;
- failure summary when applicable;
- compact summary/tags when completed.

### `GET /calls/{call_id}`

Returns full call detail.

Include:

- metadata;
- processing status;
- transcript;
- summary;
- tags;
- prompt/model metadata;
- tag overrides;
- error information when failed.

## Tentative Data Model

### `calls`

Stores user-visible call records.

Key fields:

- `id`;
- `filename`;
- `content_type`;
- `file_size_bytes`;
- `storage_bucket`;
- `storage_path`;
- `uploaded_at`;
- `status`;
- `error_code`;
- `error_message`;
- `created_at`;
- `updated_at`.

Statuses:

```text
queued
processing
completed
failed
```

### `call_processing_jobs`

Postgres-backed queue.

Key fields:

- `id`;
- `call_id`;
- `status`;
- `attempt_count`;
- `max_attempts`;
- `available_at`;
- `locked_at`;
- `locked_by`;
- `last_error`;
- `created_at`;
- `updated_at`.

Workers claim jobs using a transaction and row locking, for example `FOR UPDATE SKIP LOCKED`.

### `call_analysis`

Stores AI outputs.

Key fields:

- `id`;
- `call_id`;
- `transcript`;
- `transcript_metadata`;
- `summary`;
- `tags`;
- `intent`;
- `sentiment`;
- `next_action`;
- `risk_flags`;
- `stt_provider`;
- `stt_model`;
- `llm_provider`;
- `llm_model`;
- `prompt_version`;
- `raw_llm_output`;
- `created_at`;
- `updated_at`.

### `tag_overrides`

Stores user corrections separately from model output.

Key fields:

- `id`;
- `call_id`;
- `field`;
- `original_value`;
- `override_value`;
- `reason`;
- `created_at`;
- `created_by`.

### `processing_events`

Optional audit/debug table.

Useful for:

- tracking status transitions;
- provider latency;
- retry reasons;
- debugging failed jobs.

## Queue Decision

Use Postgres-backed jobs for this take-home.

Rationale:

- Supabase Postgres is already required.
- It avoids adding Redis, RabbitMQ, RQ, or Celery before there is real operational need.
- `FOR UPDATE SKIP LOCKED` supports multiple workers safely.
- The design still scales horizontally by running more worker containers.
- Failed jobs can be retried and inspected from the database.

What would change later:

- move to SQS, Pub/Sub, RabbitMQ, or a managed workflow system if queue throughput or scheduling requirements outgrow Postgres;
- add dead-letter queues;
- add per-provider rate limit coordination;
- add priority queues for enterprise workloads.

## Tagging Schema

Initial controlled schema:

```json
{
  "call_outcome": "demo_booked | follow_up | interested | not_interested | wrong_person | no_decision",
  "customer_intent": ["pricing_question", "product_fit", "implementation_question", "competitor_comparison", "support_need"],
  "sentiment": "positive | neutral | negative | mixed",
  "next_action": "send_info | schedule_demo | follow_up | escalate | close_lost | none",
  "risk_flags": ["pii_shared", "compliance_issue", "angry_customer", "cancellation_risk"]
}
```

Why these tags:

- sales teams care about outcome and next action;
- managers care about objections and conversion patterns;
- QA teams care about risk and sentiment;
- controlled enums make analytics and holdout scoring possible.

## Prompt Design

Prompts should live outside request handlers and be versioned.

Requirements:

- include the transcript and any available speaker/timestamp metadata;
- define the tagging schema explicitly;
- require JSON output;
- prohibit unsupported claims;
- ask the model to use `none` or empty arrays when evidence is missing;
- include `prompt_version` in persisted analysis.

LLM responses must be parsed and validated before writing to `call_analysis`. Invalid JSON or schema violations should fail the job with a useful error instead of storing partial output as if it were valid.

## Holdout Evaluation

The holdout evaluator measures AI output quality without leaking expected answers.

Rules:

- non-evaluator agents do not read `holdout/`;
- implementation agents do not see expected outputs or scoring internals;
- the evaluator compares actual output against private expected data;
- reports expose aggregate metrics and safe failure categories;
- orchestrator passes only filtered feedback back to implementation agents.

Useful metrics:

- tag precision/recall by category;
- invalid schema count;
- missing next-action count;
- summary factuality notes;
- provider error rate;
- regressions by prompt version.

This supports prompt changes over time without silently degrading tagging quality.

## Docker And Local Development

Docker should package:

- backend API;
- worker;
- frontend.

Supabase remains the managed DB/storage dependency. Local setup requires Supabase env vars rather than a separate local storage path.

Expected env vars:

```text
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
SUPABASE_STORAGE_BUCKET
DATABASE_URL
ELEVENLABS_API_KEY
OPENAI_API_KEY
```

For tests, provider and storage/database integrations should use fakes or mocks by default. Normal tests must not require live Supabase, ElevenLabs, or OpenAI access.

## Scaling To 10k Calls Per Day

10k calls/day averages to about 7 calls/minute, but burstiness matters more than the average. A sales team may upload hundreds or thousands of recordings in a short window.

Scaling levers:

- API remains lightweight because uploads only persist and queue work;
- workers scale horizontally;
- jobs are claimed with row locks;
- provider calls use rate limiters and retries;
- audio lives in object storage, not the API filesystem;
- long-running work does not block web requests.

## Bottlenecks

Likely bottlenecks:

- ElevenLabs STT latency and rate limits;
- OpenAI LLM latency and rate limits;
- large audio upload bandwidth;
- worker concurrency;
- Postgres queue contention under large bursts;
- cost per audio minute and per transcript token;
- frontend polling load if many users watch processing in real time.

Mitigations:

- provider-specific concurrency limits;
- exponential backoff;
- job batching where safe;
- separate read/write database concerns if needed;
- CDN/object storage for audio;
- polling intervals with backoff;
- observability around provider latency and failure rates.

## Production Changes

For production, add:

- authentication and authorization;
- Supabase RLS policies where appropriate;
- signed upload/download URLs;
- audit logs for tag overrides;
- dead-letter handling for failed jobs;
- metrics and tracing;
- structured logs;
- secret management;
- rate limit management per provider;
- retention and deletion workflows;
- human review flows for low-confidence analysis.

If queue pressure grows, replace Postgres-backed jobs with a dedicated queue while preserving the worker interface.

## PII Handling

Call recordings and transcripts may contain sensitive personal data.

Baseline requirements:

- do not log raw audio, transcripts, or full LLM payloads in application logs;
- store audio in private Supabase Storage buckets;
- use least-privilege credentials where possible;
- separate service-role credentials from frontend credentials;
- expose client-safe error messages only;
- define retention policy for audio and transcripts;
- support deletion/export paths;
- track tag overrides and manual edits;
- consider redaction before sending transcripts to downstream analytics.

Future improvements:

- automatic PII detection/redaction;
- customer-specific retention settings;
- encrypted fields for especially sensitive transcript data;
- access auditing;
- role-based access control.

## Open Questions

- Exact file size limit for uploads.
- Whether users need auth in the take-home scope.
- Whether the worker should process one job type or separate STT and analysis job stages.
- Which OpenAI model to use for cost/quality balance.
- Whether diarization from ElevenLabs is reliable enough to expose as speaker roles in v1.

