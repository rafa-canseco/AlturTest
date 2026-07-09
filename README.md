# Altur Call Analyzer

Web app for uploading a WAV/MP3 sales call, processing it asynchronously,
transcribing it with ElevenLabs STT, analyzing it with OpenAI, and reviewing the
result in a browser.

## Live Demo

- Frontend: https://altur-call-analyzer.vercel.app
- Backend health: https://api-production-98cf.up.railway.app/health

The deployed demo runs the React frontend on Vercel and the FastAPI API,
Postgres, audio storage volume, STT worker, and analysis worker on Railway.
Provider API keys are configured as runtime secrets, not committed to the repo.

## What It Does

- Uploads WAV/MP3 audio and returns immediately with a queued call.
- Processes calls in background worker stages: STT first, LLM analysis second.
- Persists audio metadata, transcript, summary, tags, intent, sentiment, next
  action, risk flags, human tag overrides, provider attempts, and audit events.
- Shows call list, processing state, transcript, summary, generated tags,
  editable tag overrides, structured insights, and audit trail.
- Handles partial success: if STT succeeds but LLM fails, the transcript remains
  visible.

## Run With Docker

```sh
cp .env.docker.example .env.docker.local
```

Add runtime provider keys:

```text
ELEVENLABS_API_KEY=<runtime secret>
OPENAI_API_KEY=<runtime secret>
```

Start everything:

```sh
docker compose up --build
```

Open:

```text
http://127.0.0.1:5173/
```

Useful commands:

```sh
docker compose logs -f backend worker-stt worker-analysis
docker compose down
docker compose down -v  # clears local DB/audio volumes
```

Docker uses local Postgres plus local filesystem audio storage. Supabase remote
is not required for the demo.

## Sample Audio

Reviewer-ready MP3s are included:

- [English call center phone company](samples/audio/english-call-center-phone-company.mp3)
- [Verbally abusive customer](samples/audio/verbally-abusive-customer.mp3)
- [Order arrived damaged](samples/audio/order-arrived-damaged.mp3)

Upload them in the deployed app or the Docker frontend.

## How It Works

```text
Browser
  -> React/Vite frontend
  -> FastAPI backend
  -> Postgres metadata + private audio storage
  -> STT worker
  -> LLM analysis worker
  -> persisted transcript, summary, tags, insights, audit trail
```

The upload endpoint does only bounded request-path work: validate, store audio,
create metadata, queue the job, and return a `call_id`. Long-running provider
calls happen in workers so 30-minute recordings do not block the browser request.

## Holdouts And Evaluation

The holdout suite is a small evaluator-owned quality gate for AI behavior. It
keeps input transcripts separate from private expected outputs, runs candidate
analysis outputs through scoring, and writes safe aggregate reports.

Why this matters:

- It prevents prompt tuning from leaking expected answers into the app.
- It measures behavior that unit tests cannot: sentiment, next action, summary
  coverage, risk flags, and tag categories.
- It gives useful feedback without exposing the answer key, e.g. "risk tags are
  under-detected" instead of "case X expected tag Y".
- It creates a path to grow from synthetic cases into reviewer-labeled real
  transcripts over time.

Evaluator command:

```sh
cd holdout
uv run holdout-evaluate \
  --public-cases-dir public_cases \
  --actual-dir actual_outputs/baseline \
  --expected-dir expected \
  --report reports/baseline.json
```

## API Surface

```text
POST   /calls
GET    /calls?limit=50
GET    /calls/{call_id}
GET    /calls/{call_id}/tag-overrides
POST   /calls/{call_id}/tag-overrides
DELETE /calls/{call_id}/tag-overrides/{override_id}
GET    /health
```

`POST /calls` accepts multipart form data with a `file` field. Optional
`Idempotency-Key` prevents duplicate completed retries with the same file
fingerprint.

## Repo Map

```text
backend/   FastAPI API, workers, Postgres repositories, storage adapters, migrations
frontend/  React/Vite UI managed with bun
holdout/   Evaluator-owned AI quality harness
docs/      Architecture and interview answers
samples/   Sample MP3s for reviewer testing
```

## More Detail

- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Scale, bottlenecks, production, PII, and "more time" answers:
  [docs/INTERVIEW_ANSWERS.md](docs/INTERVIEW_ANSWERS.md)
