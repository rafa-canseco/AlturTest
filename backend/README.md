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
