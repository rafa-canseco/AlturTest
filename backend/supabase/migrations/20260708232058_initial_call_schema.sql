-- ALT-20: Initial Supabase Postgres schema and Storage contract.
--
-- Storage contract:
-- - Bucket: call-audio
-- - Access: private; backend and worker use service-role credentials only.
-- - Path convention: calls/{call_id}/{original_filename_slug}-{upload_token}.{ext}
-- - Metadata persisted in calls: storage_bucket, storage_path, content_type,
--   file_size_bytes, and optional storage_etag/storage_version.
-- - Tests should use repository/storage fakes or mocks and must not require live
--   Supabase Storage or Postgres.

create extension if not exists pgcrypto;

insert into storage.buckets (
    id,
    name,
    public,
    file_size_limit,
    allowed_mime_types
)
values (
    'call-audio',
    'call-audio',
    false,
    524288000,
    array[
        'audio/mpeg',
        'audio/mp3',
        'audio/wav',
        'audio/wave',
        'audio/x-wav'
    ]
)
on conflict (id) do update set
    name = excluded.name,
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

do $$
begin
    create type call_status as enum ('queued', 'processing', 'completed', 'failed');
exception
    when duplicate_object then null;
end $$;

do $$
begin
    create type call_processing_job_status as enum (
        'queued',
        'processing',
        'completed',
        'failed'
    );
exception
    when duplicate_object then null;
end $$;

create or replace function set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create table if not exists calls (
    id uuid primary key default gen_random_uuid(),
    original_filename text not null check (length(trim(original_filename)) > 0),
    content_type text not null check (
        content_type in (
            'audio/mpeg',
            'audio/mp3',
            'audio/wav',
            'audio/wave',
            'audio/x-wav'
        )
    ),
    file_size_bytes bigint not null check (file_size_bytes > 0),
    duration_seconds numeric(10, 3) check (
        duration_seconds is null or duration_seconds >= 0
    ),
    storage_bucket text not null default 'call-audio',
    storage_path text not null unique,
    storage_etag text,
    storage_version text,
    status call_status not null default 'queued',
    error_code text,
    error_message text,
    failed_at timestamptz,
    uploaded_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (
        (
            status = 'failed'
            and error_code is not null
            and error_message is not null
            and failed_at is not null
        )
        or (status <> 'failed' and failed_at is null)
    )
);

drop trigger if exists calls_set_updated_at on calls;
create trigger calls_set_updated_at
before update on calls
for each row
execute function set_updated_at();

create table if not exists call_processing_jobs (
    id uuid primary key default gen_random_uuid(),
    call_id uuid not null references calls(id) on delete cascade,
    status call_processing_job_status not null default 'queued',
    attempt_count integer not null default 0 check (attempt_count >= 0),
    max_attempts integer not null default 3 check (max_attempts > 0),
    available_at timestamptz not null default now(),
    locked_at timestamptz,
    locked_by text,
    started_at timestamptz,
    completed_at timestamptz,
    failed_at timestamptz,
    last_error_code text,
    last_error_message text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (call_id),
    check (attempt_count <= max_attempts),
    check (
        (status = 'processing' and locked_at is not null and locked_by is not null)
        or status <> 'processing'
    ),
    check (
        (
            status = 'failed'
            and last_error_code is not null
            and last_error_message is not null
            and failed_at is not null
        )
        or status <> 'failed'
    )
);

drop trigger if exists call_processing_jobs_set_updated_at on call_processing_jobs;
create trigger call_processing_jobs_set_updated_at
before update on call_processing_jobs
for each row
execute function set_updated_at();

create table if not exists call_analysis (
    id uuid primary key default gen_random_uuid(),
    call_id uuid not null references calls(id) on delete cascade,
    transcript text not null,
    transcript_metadata jsonb not null default '{}'::jsonb,
    summary text not null,
    tags jsonb not null default '{}'::jsonb,
    intent text,
    sentiment text check (
        sentiment is null or sentiment in ('positive', 'neutral', 'negative', 'mixed')
    ),
    next_action text check (
        next_action is null
        or next_action in (
            'send_info',
            'schedule_demo',
            'follow_up',
            'escalate',
            'close_lost',
            'none'
        )
    ),
    risk_flags jsonb not null default '[]'::jsonb,
    stt_provider text not null,
    stt_model text,
    llm_provider text not null,
    llm_model text not null,
    prompt_version text not null,
    raw_llm_output jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (call_id),
    check (jsonb_typeof(transcript_metadata) = 'object'),
    check (jsonb_typeof(tags) = 'object'),
    check (jsonb_typeof(risk_flags) = 'array')
);

drop trigger if exists call_analysis_set_updated_at on call_analysis;
create trigger call_analysis_set_updated_at
before update on call_analysis
for each row
execute function set_updated_at();

create table if not exists tag_overrides (
    id uuid primary key default gen_random_uuid(),
    call_id uuid not null references calls(id) on delete cascade,
    field text not null check (
        field in (
            'call_outcome',
            'customer_intent',
            'sentiment',
            'next_action',
            'risk_flags'
        )
    ),
    original_value jsonb,
    override_value jsonb not null,
    reason text,
    created_by text,
    created_at timestamptz not null default now()
);

create table if not exists processing_events (
    id uuid primary key default gen_random_uuid(),
    call_id uuid references calls(id) on delete cascade,
    job_id uuid references call_processing_jobs(id) on delete cascade,
    event_type text not null,
    message text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    check (jsonb_typeof(metadata) = 'object')
);

-- Listing calls: newest uploads first, with efficient status filtering.
create index if not exists idx_calls_uploaded_at_desc
    on calls (uploaded_at desc, id desc);

create index if not exists idx_calls_status_uploaded_at_desc
    on calls (status, uploaded_at desc, id desc);

-- Claiming queued jobs:
-- begin;
-- select id
-- from call_processing_jobs
-- where status = 'queued' and available_at <= now()
-- order by available_at asc, created_at asc
-- for update skip locked
-- limit 1;
-- update call_processing_jobs set status = 'processing', locked_at = now(), ...
-- commit;
create index if not exists idx_call_processing_jobs_claim
    on call_processing_jobs (available_at asc, created_at asc)
    where status = 'queued';

create index if not exists idx_call_processing_jobs_call_id
    on call_processing_jobs (call_id);

create index if not exists idx_call_analysis_call_id
    on call_analysis (call_id);

create index if not exists idx_tag_overrides_call_id_created_at
    on tag_overrides (call_id, created_at desc);

create index if not exists idx_processing_events_call_id_created_at
    on processing_events (call_id, created_at desc);

create index if not exists idx_processing_events_job_id_created_at
    on processing_events (job_id, created_at desc);
