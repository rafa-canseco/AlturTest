# Altur Call Analyzer

Take-home web app for uploading a WAV/MP3 sales call, processing it asynchronously, transcribing it with STT, analyzing the transcript with an LLM, and reviewing the result in a browser.

## What Works

- Upload WAV/MP3 audio through the React frontend.
- `POST /calls` stores audio metadata and returns immediately with a queued call.
- Background workers run STT and LLM analysis outside the request path.
- ElevenLabs STT creates a persisted transcript.
- OpenAI analysis creates a validated summary, tags, intent, sentiment, next action, and risk flags.
- Calls, jobs, transcripts, analysis, provider attempts, and audit events persist in Postgres.
- Frontend lists calls and shows detail with transcript, analysis, errors, and audit trail.
- Unit tests cover upload validation, idempotency, worker behavior, provider failures, malformed LLM output, and result APIs.

## Repository Layout

```text
backend/   FastAPI API, Postgres repositories, local audio storage, workers, migrations
frontend/  React/Vite UI managed with bun
docs/      Architecture and production notes
holdout/   Evaluator-owned AI quality harness
```

Non-evaluator agents should not inspect `holdout/`. The evaluator can run it and share only safe aggregate feedback.

## Architecture

```text
Browser
  -> React/Vite frontend
  -> FastAPI backend
  -> local audio storage for the demo
  -> Postgres tables for calls, jobs, transcripts, analysis, events

Worker stage: stt
  -> claims queued jobs without transcripts
  -> downloads audio
  -> calls ElevenLabs
  -> stores call_transcripts
  -> requeues job for analysis

Worker stage: analysis
  -> claims queued jobs with transcripts
  -> calls OpenAI with strict JSON schema
  -> validates output
  -> stores call_analysis
  -> completes the call
```

The upload endpoint returns after the audio is stored and a job is queued. STT and LLM calls can take minutes, so they run in workers.

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Requirements

- Docker Desktop, for the one-command demo path
- Python 3.12+, `uv`, and Bun only if running services manually
- ElevenLabs API key, for real STT
- OpenAI API key, for real analysis

## Docker Quickstart

The easiest local demo path uses Docker Compose with local Postgres and local
filesystem audio storage. It does not require Supabase remote or Supabase API
keys.

```sh
cp .env.docker.example .env.docker.local
```

Edit `.env.docker.local` and add provider credentials:

```text
ELEVENLABS_API_KEY=<runtime secret>
OPENAI_API_KEY=<runtime secret>
```

`.env.docker.local` is intentionally gitignored. Do not commit real API keys.

Start the app:

```sh
docker compose up --build
```

Open:

```text
http://127.0.0.1:5173/
```

Compose services:

- `db`: local Postgres on the internal Compose network
- `migrate`: applies committed SQL migrations from `backend/supabase/migrations`
- `backend`: FastAPI API on `http://127.0.0.1:8000`
- `worker-stt`: ElevenLabs STT worker
- `worker-analysis`: OpenAI analysis worker
- `frontend`: Vite frontend on `http://127.0.0.1:5173`

Useful commands:

```sh
docker compose ps
docker compose logs -f backend worker-stt worker-analysis
docker compose down
docker compose down -v  # also clears local DB/audio volumes
```

Docker uses local Postgres plus the backend's `LocalCallStorage` mounted at
`/data/storage`. Supabase remote is not used for the Docker demo. Supabase
remains a production-compatible option because the schema is plain Postgres and
the storage contract is explicit.

## Manual Environment

Backend:

```sh
cd backend
cp .env.example .env
```

Required local values for the manual Supabase-CLI path:

```text
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres
CALL_STORAGE_BUCKET=call-audio
LOCAL_STORAGE_ROOT=.data/storage
MAX_CALL_UPLOAD_BYTES=524288000
ELEVENLABS_API_KEY=<runtime secret>
ELEVENLABS_STT_MODEL_ID=scribe_v1
OPENAI_API_KEY=<runtime secret>
OPENAI_ANALYSIS_MODEL=gpt-4.1-mini
ANALYSIS_PROMPT_VERSION=altur-analysis-v1
```

Frontend:

```sh
cd frontend
cp .env.example .env
```

```text
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## Local Setup

Skip this section if using Docker Compose.

Install backend dependencies:

```sh
cd backend
uv sync
```

Install frontend dependencies:

```sh
cd frontend
bun install
```

Start local Postgres through Supabase:

```sh
cd backend
supabase start
supabase db reset
```

`supabase start` requires Docker Desktop. The current demo uses Supabase local Postgres and local filesystem audio storage at `backend/.data/storage`.

## Run Locally

Terminal 1, backend API:

```sh
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Health check:

```sh
curl http://127.0.0.1:8000/health
```

Terminal 2, frontend:

```sh
cd frontend
bun run dev --host 127.0.0.1 --port 5173
```

Open:

```text
http://127.0.0.1:5173/
```

Terminal 3, STT worker:

```sh
cd backend
uv run python -m app.worker --stage stt
```

Terminal 4, analysis worker:

```sh
cd backend
uv run python -m app.worker --stage analysis
```

For one-shot local debugging, add `--once` to a worker command.

## API

```text
POST /calls
GET /calls?limit=50
GET /calls/{call_id}
GET /calls/{call_id}/tag-overrides
POST /calls/{call_id}/tag-overrides
DELETE /calls/{call_id}/tag-overrides/{override_id}
GET /health
```

`POST /calls` accepts multipart form data with a `file` field. Optional `Idempotency-Key` prevents duplicate calls on completed retries with the same file fingerprint.

Call detail includes:

- audio metadata: filename, upload timestamp, content type, size, storage path
- status and client-safe errors
- transcript, when STT has succeeded
- analysis summary and tags, when LLM analysis has succeeded
- structured conversation insights, when generated
- human tag overrides, stored separately from model output
- audit events for upload, job claim, STT, analysis, completion, and failure

## Analysis Schema

OpenAI analysis is requested with a strict JSON schema and validated before persistence.

```json
{
  "summary": "Concise summary of the full transcript",
  "tags": {
    "topics": ["pricing"],
    "customer_intents": ["request information"],
    "products": ["phone insurance"],
    "risks": [],
    "outcomes": ["information provided"]
  },
  "intent": "request information",
  "sentiment": "positive",
  "next_action": "send_info",
  "risk_flags": [],
  "insights": {
    "objections": [],
    "commitments": [],
    "follow_up_hints": [],
    "customer_questions": [],
    "agent_action_items": [],
    "escalation_notes": []
  }
}
```

Allowed sentiment values:

```text
positive, neutral, negative, mixed
```

Allowed next action values:

```text
send_info, schedule_demo, follow_up, escalate, close_lost, none
```

Tags are grouped this way because sales and operations users need both human-readable review and aggregate reporting:

- `topics`: what the conversation was about
- `customer_intents`: why the customer called or responded
- `products`: product/service areas mentioned
- `risks`: compliance, churn, fraud, anger, or escalation signals
- `outcomes`: what happened by the end of the call

## Testing

Backend unit tests:

```sh
cd backend
uv run pytest
```

The default backend test suite uses fakes and does not require Supabase, ElevenLabs, or OpenAI.

Opt-in local integration tests:

```sh
cd backend
supabase start
supabase db reset
uv run pytest -m integration
```

Frontend checks:

```sh
cd frontend
bun run typecheck
bun run lint
bun run build
```

Holdout evaluator, evaluator-owned only:

```sh
cd holdout
uv run python -m unittest discover -s tests
```

The holdout design keeps private expected outputs and scoring internals away from implementation agents. Implementation work should receive only safe aggregate failures or behavioral notes.

## Prompt And Tag Quality Strategy

Prompt version:

```text
altur-analysis-v1
```

The prompt asks for one aggregate analysis of the full transcript. If an audio file contains multiple segments, the model must still return one dominant intent and one dominant next action instead of per-call objects. The response is constrained by OpenAI JSON schema and validated locally before `call_analysis` is written.

Quality should be evaluated over time through:

- holdout transcripts with private expected outputs
- schema-invalid output rate
- tag precision and recall by category
- sampled human review of summaries and tags
- comparison of generated tags against later human overrides
- monitoring drift by `prompt_version`, model, language, and call type

## Error Handling

- Invalid file type, extension, empty file, and size violations return client-safe `400` errors.
- Storage failures return `502`.
- Database/job queue failures return `503`; uploaded audio is cleaned up when possible.
- Provider failures fail the job with safe error messages and preserve prior successful stages.
- If STT succeeds but LLM analysis fails, the transcript remains available.
- Raw provider attempts are stored internally for debugging and are not exposed in the public call detail API.

## Assumptions

- This is a single-tenant take-home demo. Auth and multi-user isolation are documented as production work.
- Local audio storage is acceptable for the demo. Production should use private object storage with signed access.
- Postgres-backed jobs are sufficient for the take-home and explainable for 10k calls/day with worker scaling. A dedicated queue can replace it later without changing the API contract.
- Workers are separate processes, not FastAPI startup tasks.
- Provider calls are not mocked in the real demo path, but tests remain deterministic with fakes.

## What I Would Improve With More Time

- Hosted preview deployment with managed database/storage.
- JSON export.
- Analytics dashboard for status and tag distribution.
- Speaker role detection if provider diarization is reliable enough.
- Authentication, tenant isolation, and row-level access controls.
- PII redaction, retention policies, and deletion workflows.
- Dedicated queue and dead-letter handling for larger production bursts.
