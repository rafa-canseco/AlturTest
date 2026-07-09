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

## Evaluating Tag Quality Over Time

A one-off model response is not enough. Tag quality should be measured over time through:

- holdout transcripts with private expected outputs;
- schema-invalid output rate;
- tag precision and recall by category;
- summary factuality sampling;
- human review of representative calls;
- comparison between generated tags and later human overrides;
- drift checks by `prompt_version`, model, language, customer type, and call type.

The evaluator should expose safe aggregate reports, not expected answers. Implementation agents should receive behavioral feedback such as "missing follow-up tag on pricing objection cases", not hidden labels.

## Scaling To 10k Calls Per Day

10k calls/day averages to about 7 calls/minute. The harder problem is burstiness: a user might upload 1,000 recordings in a short window.

The current design scales through:

- lightweight upload API;
- object-storage-compatible audio storage;
- Postgres-backed queue with row locks;
- horizontally scalable STT workers;
- horizontally scalable analysis workers;
- separate STT and analysis stages;
- idempotency keys for safe client retries;
- audit events for operational visibility.

For 10k/day, the first production version could still use Postgres jobs if provider limits and worker counts are controlled. The operational focus should be worker autoscaling, provider rate limits, queue depth monitoring, and retry/dead-letter behavior.

## Bottlenecks

Likely bottlenecks:

- STT provider latency and rate limits.
- OpenAI latency, token cost, and rate limits.
- Audio upload bandwidth and file size.
- Worker concurrency and CPU/memory for large files.
- Postgres queue contention during bursts.
- Frontend polling if many users watch live progress.
- Storage cost and retention for raw audio.
- Long transcripts increasing LLM token cost.

Mitigations:

- Use separate worker pools for STT and analysis.
- Add provider-specific rate limiters.
- Back off retries and cap attempts.
- Move to a dedicated queue when queue depth or lock contention grows.
- Use signed direct-to-object-storage uploads for very large files.
- Add polling backoff or realtime updates.
- Add transcript chunking/summarization if calls approach model limits.
- Track provider latency, error rate, queue depth, and cost per call.

## Production Changes

Before production, I would add:

- authentication and tenant isolation;
- private object storage with signed URLs;
- least-privilege credentials and secret management;
- row-level access controls where appropriate;
- structured logs and tracing;
- metrics for queue depth, provider latency, failures, and cost;
- dead-letter queue or failed-job review workflow;
- provider concurrency controls;
- retention and deletion policies;
- tag override UI and audit trail; currently implemented for the demo, but production would add reviewer identity and approval controls;
- export/download support for call records;
- deployment pipeline and environment separation;
- backup/restore and migration runbooks.

If upload bursts or job volume outgrow Postgres-backed jobs, I would replace `call_processing_jobs` with a managed queue while keeping the worker processor interfaces.

## PII Handling And Storage

Phone calls can contain names, phone numbers, account details, addresses, payment references, and other sensitive data.

Current safeguards:

- Audio files are not stored in Postgres.
- Client-facing errors are safe and do not include provider internals.
- Raw provider attempts are internal and not exposed by `GET /calls/{call_id}`.
- Tests use fake provider data and do not require real customer recordings.

Production requirements:

- Store audio in private buckets only.
- Use signed URLs or server-side download paths.
- Encrypt data at rest through managed database/storage defaults and stronger controls where needed.
- Avoid logging raw audio, transcript text, raw provider payloads, or API keys.
- Restrict access to transcripts and provider attempts.
- Add retention policies for audio, transcripts, and raw provider responses.
- Support deletion and export workflows.
- Consider PII detection/redaction before analytics or external sharing.
- Audit manual overrides and administrative access.
- Separate frontend-safe keys from backend service credentials.

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

Default tests should be deterministic and fast:

- API tests use fake storage/repositories.
- Worker tests use fake STT and LLM clients.
- LLM validation tests cover malformed output.
- Integration tests against local Supabase/Postgres are opt-in.
- Holdout tests are evaluator-owned and should not leak expected answers.

Commands:

```sh
cd backend
uv run pytest
uv run pytest -m integration
```

```sh
cd frontend
bun run typecheck
bun run lint
bun run build
```

Evaluator-owned:

```sh
cd holdout
uv run python -m unittest discover -s tests
uv run holdout-evaluate \
  --public-cases-dir public_cases \
  --actual-dir actual_outputs/baseline \
  --expected-dir expected \
  --report reports/baseline.json
```

## Known Tradeoffs

- Local Docker storage uses disk; the deployed demo uses a Railway volume. Production should use private object storage.
- The deployed preview runs API and workers in one Railway service for shared audio access. Production should split workers into services backed by object storage.
- Uploads are bounded and read in chunks, but the current storage abstraction still receives bytes in memory. Production should stream directly to private object storage or use signed direct uploads.
- No authentication in the current take-home scope.
- Analytics dashboard is planned but not required for the core submission.
- Speaker role detection is deferred until diarization quality is verified.

## Next Improvements

Highest-value next items:

1. Direct-to-object-storage uploads and separated deployed worker services.
2. Provider rate limits, concurrency caps, and dead-letter handling.
3. JSON export.
4. Analytics dashboard.
5. More holdout cases from reviewer-labeled transcripts.
6. Speaker roles if provider metadata supports it cleanly.
7. Auth and multi-user isolation.
