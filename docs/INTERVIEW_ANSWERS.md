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

- Add business entities around the call: campaign, account/contact, channel,
  promised payment, next follow-up date, and agent/version metadata.
- Turn analysis output into operational outcomes: payment promise, discount
  requested, escalation, objection, compliance risk, and follow-up task.
- Add QA scorecards for protocol adherence, negotiation quality, customer mood,
  and whether the call moved the account forward.
- Add dashboards for contact rate, conversion, promise-to-pay rate, broken
  promises, escalation rate, and tag drift by campaign.
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

My next work would be business-first, not model-first:

1. Campaign and account context. Store which campaign, segment, balance range,
   channel, and strategy version produced each call. That makes summaries useful
   for operations, not just interesting per-call notes.
2. Promise-to-pay and follow-up extraction. Detect promised dates, payment
   amounts, broken promises, discount requests, and next follow-up tasks so the
   system can drive collections/sales workflows after the call.
3. QA and compliance scorecards. Score whether the conversation followed the
   intended script, handled objections correctly, avoided risky language, and
   escalated when needed.
4. Strategy analytics. Show contact rate, conversion, promise-to-pay rate,
   escalation rate, common objections, sentiment by segment, and outcomes by
   prompt/agent version.
5. Human override feedback loop. Use reviewer corrections to measure tag quality,
   tune prompts, and detect drift by campaign, language, and call type.
6. A/B testing support. Compare call scripts, tone, timing, and offer strategies
   against business outcomes instead of only model-level accuracy.
7. Production hardening behind those workflows: direct-to-object-storage uploads,
   separated workers, provider concurrency controls, DLQ, PII redaction,
   retention/deletion, and audit trails.

I would avoid adding isolated AI features unless they connect to an operational
metric. For Altur's domain, the valuable product is not "a prettier transcript";
it is better contact strategy, better negotiation outcomes, safer compliance,
and clearer visibility into why calls succeed or fail.
