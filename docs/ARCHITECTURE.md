# Architecture And Production Notes

This document explains the current implementation and the production reasoning behind it. It is written for the follow-up interview: what was built, why those tradeoffs are reasonable for the take-home, and what would change in production.

## Goals

The challenge asks for a web app that can:

1. Upload WAV/MP3 sales call recordings.
2. Transcribe each recording with STT.
3. Analyze the transcript with an LLM.
4. Persist audio metadata, transcript, summary, and tags.
5. Show a call list and call detail UI.
6. Handle long processing asynchronously.
7. Include tests, error handling, and clear documentation.

The built system follows this workflow:

```text
audio upload -> queued call -> STT worker -> analysis worker -> persisted result -> review UI
```

## Components

### Frontend

- React/Vite app managed with `bun`.
- Uploads WAV/MP3 files.
- Lists calls and processing status.
- Shows call detail with transcript, analysis, and audit trail.
- Uses `VITE_API_BASE_URL` so local and deployed backends can differ.

### Backend API

- FastAPI app managed with `uv`.
- Validates upload inputs.
- Stores audio through a storage abstraction.
- Creates `calls` and `call_processing_jobs` records in Postgres.
- Returns quickly after queueing work.
- Exposes:

```text
POST /calls
GET /calls
GET /calls/{call_id}
GET /health
```

### Workers

Workers are separate Python processes, not request handlers.

STT worker:

```text
claim queued job without transcript
download audio
call ElevenLabs STT
store call_transcripts
requeue same job for analysis
```

Analysis worker:

```text
claim queued job with transcript
read transcript
call OpenAI
validate strict schema
store call_analysis
complete job and call
```

This split is intentionally simple. It lets STT success be preserved even if LLM analysis fails.

### Database

Postgres is the source of truth.

Key tables:

- `calls`: user-visible call metadata, status, storage path, client-safe errors.
- `call_processing_jobs`: Postgres-backed job queue.
- `call_transcripts`: one STT transcript per call.
- `call_analysis`: one validated LLM analysis per call.
- `call_provider_attempts`: internal raw STT/LLM provider attempts for debugging.
- `processing_events`: safe audit timeline shown in the UI.
- `call_idempotency_keys`: optional upload retry protection.
- `tag_overrides`: schema exists for future human corrections.

### Storage

The local demo stores audio on disk through `LocalCallStorage` under `backend/.data/storage`. The database still records `storage_bucket` and `storage_path`, so replacing local disk with private object storage is straightforward.

Production should use private object storage, for example Supabase Storage or S3-compatible storage, with signed access and explicit retention policies.

## Why Upload Returns Immediately

Calls can be up to 30 minutes long, and STT plus LLM processing can take several minutes. Running providers inside `POST /calls` would create a slow, fragile request path and would fail under browser timeouts or provider latency.

Instead, `POST /calls` does only the minimum synchronous work:

1. Validate file type, extension, size, and content.
2. Store audio.
3. Persist call metadata.
4. Queue a job.
5. Return `call_id` and `queued` status.

The UI then shows queued/processing/completed/failed states and can poll for updates.

## Queue Design

The current queue is Postgres-backed via `call_processing_jobs`.

Workers claim jobs with row locking:

```text
FOR UPDATE SKIP LOCKED
```

Why this is reasonable here:

- Postgres is already required.
- It avoids adding Redis, RabbitMQ, Celery, or a cloud queue too early.
- It is easy to inspect during review.
- Multiple workers can safely claim different jobs.
- Retry state and failure state live next to the call records.

What would change later:

- Move to SQS, Pub/Sub, RabbitMQ, Celery, or a workflow system if queue pressure grows.
- Add dead-letter queues.
- Add provider-specific concurrency controls.
- Add priority queues for enterprise customers or retry classes.

## LLM Prompt Design

OpenAI is called with a versioned prompt:

```text
altur-analysis-v1
```

The prompt asks for one aggregate analysis of the full transcript. This matters because real uploads can contain multiple segments or role-play examples; the API contract still expects one `summary`, one `intent`, one `sentiment`, and one `next_action`.

The response is constrained with OpenAI JSON schema:

```json
{
  "summary": "string",
  "tags": {
    "topics": ["string"],
    "customer_intents": ["string"],
    "products": ["string"],
    "risks": ["string"],
    "outcomes": ["string"]
  },
  "intent": "string or null",
  "sentiment": "positive | neutral | negative | mixed | null",
  "next_action": "send_info | schedule_demo | follow_up | escalate | close_lost | none | null",
  "risk_flags": ["string"]
}
```

The backend validates this output before persistence. Invalid JSON, wrong types, or unsupported enum values fail the job with `analysis_failed` and preserve the transcript.

Raw provider attempts are stored internally in `call_provider_attempts`. They are useful for debugging prompt or provider failures, but they are not exposed to the public call detail API.

## Tagging Schema

The current tagging schema is deliberately operational rather than decorative:

- `topics`: what subjects were discussed.
- `customer_intents`: what the customer was trying to accomplish.
- `products`: product or service areas mentioned.
- `risks`: compliance, churn, anger, fraud, or escalation signals.
- `outcomes`: what happened by the end of the call.

The schema is useful for both individual review and aggregate analytics:

- Sales managers can see common objections and outcomes.
- Operations teams can track follow-up actions.
- QA teams can scan for risk patterns.
- Future dashboards can group tags consistently.

The separate scalar fields remain useful:

- `intent`: one dominant intent for the full call.
- `sentiment`: overall emotional tone.
- `next_action`: the operational action the team should take.
- `risk_flags`: explicit warnings that need review.

## Scale And Production Notes

This document describes the current design. The interview-focused answers for
scale, bottlenecks, production changes, and PII handling live in
[INTERVIEW_ANSWERS.md](INTERVIEW_ANSWERS.md). Keeping those answers separate
avoids duplicating reasoning across README, architecture notes, and the interview
prep document.

The short version:

- upload returns quickly and workers handle provider latency;
- Postgres jobs are acceptable for the take-home and early production;
- object storage, separated workers, provider rate limits, DLQ, auth, PII
  retention/deletion, and observability are the next production hardening steps;
- holdouts should grow from synthetic cases into reviewer-labeled real
  transcripts.

## Failure Handling

Failure behavior is staged:

- If upload validation fails, the API returns `400`.
- If storage fails, the API returns `502`.
- If DB queueing fails after upload, the API returns `503` and attempts audio cleanup.
- If STT fails, the job/call fail with `stt_failed`.
- If STT succeeds but LLM fails, transcript remains available.
- If analysis output is invalid, the job/call fail with `analysis_failed`.
- Failed jobs can be requeued if attempts remain.

The UI should show partial value. A call with a failed analysis but a successful transcript should not hide the transcript.

## Testing Strategy

Default tests are deterministic and fast: API tests use fake storage/repos,
worker tests use fake STT/LLM clients, malformed LLM outputs are validated, and
provider-backed checks are kept out of the default path. Commands are listed in
the README.
