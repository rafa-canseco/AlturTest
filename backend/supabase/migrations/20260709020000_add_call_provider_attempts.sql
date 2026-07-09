-- Internal provider observability for STT/LLM attempts.
--
-- processing_events remains the client-safe timeline. This table stores raw
-- provider payloads for backend/operator debugging and must not be exposed by
-- the public call detail API.

create table if not exists call_provider_attempts (
    id uuid primary key default gen_random_uuid(),
    call_id uuid not null references calls(id) on delete cascade,
    job_id uuid references call_processing_jobs(id) on delete set null,
    stage text not null check (stage in ('stt', 'analysis')),
    provider text not null,
    model text,
    status text not null check (status in ('valid', 'invalid', 'failed')),
    metadata jsonb not null default '{}'::jsonb,
    raw_provider_response jsonb,
    raw_content text,
    parsed_output jsonb,
    error_message text,
    created_at timestamptz not null default now(),
    check (jsonb_typeof(metadata) = 'object'),
    check (
        raw_provider_response is null
        or jsonb_typeof(raw_provider_response) = 'object'
    ),
    check (
        parsed_output is null
        or jsonb_typeof(parsed_output) = 'object'
    ),
    check (
        (status = 'valid' and error_message is null)
        or (status <> 'valid' and error_message is not null)
    )
);

create index if not exists idx_call_provider_attempts_call_id_created_at
    on call_provider_attempts (call_id, created_at desc);

create index if not exists idx_call_provider_attempts_job_id_created_at
    on call_provider_attempts (job_id, created_at desc);

create index if not exists idx_call_provider_attempts_stage_status_created_at
    on call_provider_attempts (stage, status, created_at desc);
