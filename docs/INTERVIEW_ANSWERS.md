# Interview Answers

This file answers the four scale and production questions from the take-home
prompt. It is intentionally concise so it can be used during the follow-up
interview.

## How Does This Scale To 10k Calls/Day?

10k calls/day is about 7 calls/minute on average, but the real problem is burst
load: one customer may upload 1,000 recordings in a short window. The current
design is built around that constraint by keeping upload fast and moving slow
work to workers.

The upload API does only bounded synchronous work:

1. Validate file type, extension, and size.
2. Store the audio.
3. Persist call metadata.
4. Queue processing work.
5. Return a `call_id` immediately.

STT and LLM processing happen asynchronously. The worker stages are separated:

- STT workers claim calls without transcripts.
- Analysis workers claim calls that already have transcripts.
- STT success is persisted before LLM analysis starts, so a failed LLM call does
  not lose transcript value.

The current Postgres queue uses `FOR UPDATE SKIP LOCKED`, which is reasonable for
the take-home and early production because it is inspectable, transactional, and
easy to scale horizontally with more workers. At 10k/day I would start by scaling
worker replicas and enforcing provider concurrency limits. If queue depth or lock
contention became material, I would replace the job table with SQS, Pub/Sub,
RabbitMQ, or Celery while keeping the API contract and processor interfaces.

The pieces that make the design scalable enough for this scope are:

- async processing outside request handlers;
- idempotency keys for safe upload retries;
- independent STT and analysis stages;
- persisted job state and attempt counts;
- audit events for operational visibility;
- object-storage-compatible audio paths;
- deterministic tests and holdouts to protect behavior while changing internals.

## Where Are The Bottlenecks?

The biggest bottlenecks are not FastAPI route handlers. They are provider,
storage, and queue-pressure bottlenecks.

Primary bottlenecks:

- STT latency, rate limits, and cost for 30-minute audio.
- LLM latency, token limits, token cost, and model rate limits.
- Burst uploads saturating bandwidth or storage writes.
- Large files held by the API process before storage.
- Postgres queue lock contention if many workers claim jobs at high volume.
- Frontend polling if many users watch processing in real time.
- Raw audio retention costs.
- Long transcripts increasing analysis prompt size.

What I did in this version:

- moved provider work to workers;
- split STT and LLM stages;
- preserved partial success;
- bounded upload size;
- added provider attempt records and processing events;
- added safe client-facing errors;
- documented direct-to-object-storage uploads as production work.

What I would add next:

- direct signed uploads to private object storage;
- provider-specific rate limiters and concurrency caps;
- dead-letter queue for exhausted retries;
- queue-depth, provider-latency, failure-rate, and cost metrics;
- polling backoff or realtime events;
- transcript chunking/summarization for long calls near model limits.

## What Would You Change For Production?

I would keep the product contract but harden the infrastructure and security
boundaries.

Production changes:

- Move audio to private object storage with signed uploads/downloads.
- Split API, STT workers, and analysis workers into separate services.
- Replace the demo Railway volume with S3-compatible storage or Supabase Storage.
- Add auth, tenant isolation, and row-level access controls.
- Add provider rate limits, concurrency caps, and backoff policies.
- Add a dead-letter queue and failed-job review workflow.
- Add structured logs, traces, metrics, and alerting.
- Add migration and rollback runbooks.
- Add backup/restore testing for Postgres.
- Add explicit retention and deletion workflows.
- Add JSON export for call records.
- Add analytics dashboard for tag/status distribution.
- Expand holdouts from synthetic cases to reviewer-labeled real transcripts.

I would not immediately add a vector database. The current task is classification,
summarization, and operational review, not semantic retrieval over a large corpus.
A vector store would make sense later for cross-call search, similar-case lookup,
agent coaching retrieval, or RAG over internal playbooks. It is not needed for the
core call analyzer.

## How Would You Ensure Correct PII Handling And Storage?

The core rule is to treat audio, transcripts, raw provider payloads, and analysis
as sensitive data. Phone calls can contain names, phone numbers, account numbers,
addresses, payment details, and free-form sensitive statements.

Current safeguards in the demo:

- Audio is stored outside Postgres.
- API errors are client-safe and do not expose provider internals.
- Raw provider attempts are internal and not returned by public call detail.
- Secrets are runtime environment variables, not committed to the repo.
- Tests use fake provider data and sample/demo recordings.
- The README documents the production PII gap instead of pretending it is solved.

Production PII controls:

- Private buckets only, no public audio URLs.
- Signed URLs with short TTLs or server-mediated downloads.
- Encryption at rest through managed DB/storage plus strict key access.
- Least-privilege service credentials.
- Tenant isolation and authorization checks on every call record.
- Redaction pipeline for common PII before analytics or external sharing.
- No raw audio, transcript text, provider payloads, or secrets in logs.
- Restricted access to `call_provider_attempts`.
- Retention windows by data type: audio, transcript, raw provider response,
  analysis, audit events.
- Deletion workflow that removes DB rows and storage objects together.
- Audit trail for human overrides and administrative access.
- Separate policies for production data, demo data, and evaluation fixtures.

The important tradeoff is that PII handling is not a single feature. It is a
system property: storage, logs, access control, retention, provider payloads,
evaluation data, and support workflows all need to agree.

## If I Had More Time

My next work would be:

1. Direct-to-object-storage uploads so the API never buffers large files.
2. Split deployed workers into separate services backed by object storage.
3. Provider concurrency controls, cost metrics, and dead-letter handling.
4. PII redaction plus retention/deletion workflows.
5. More holdout cases from reviewer-labeled transcripts and regular regression
   runs by prompt version.
6. JSON export and analytics dashboard.
7. Speaker role detection only after validating diarization quality.

This is the path I would choose because it improves correctness, operability, and
privacy before adding speculative features.
