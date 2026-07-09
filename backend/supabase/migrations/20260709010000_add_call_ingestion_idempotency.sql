-- ALT-23: Persist call ingestion Idempotency-Key mappings.
--
-- The client-provided key is stored only as a sha256 hash. The request
-- fingerprint stores safe metadata plus a content hash, never raw audio.

create table if not exists call_idempotency_keys (
    idempotency_key_hash text primary key check (
        length(idempotency_key_hash) = 64
    ),
    request_fingerprint_hash text not null check (
        length(request_fingerprint_hash) = 64
    ),
    request_fingerprint jsonb not null,
    call_id uuid not null unique references calls(id) on delete cascade,
    created_at timestamptz not null default now(),
    check (jsonb_typeof(request_fingerprint) = 'object'),
    check (
        request_fingerprint ? 'filename'
        and request_fingerprint ? 'content_type'
        and request_fingerprint ? 'file_size_bytes'
        and request_fingerprint ? 'content_sha256'
    )
);

create index if not exists idx_call_idempotency_keys_call_id
    on call_idempotency_keys (call_id);
