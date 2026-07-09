from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from psycopg import OperationalError, connect
from psycopg.rows import dict_row

from app.calls.models import CallCreate
from app.calls.repository import PostgresCallRepository
from app.calls.storage import CallStorageError, SupabaseStorage
from app.worker.repository import PostgresWorkerRepository


pytestmark = pytest.mark.integration


@pytest.fixture()
def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        pytest.skip("DATABASE_URL is required for Supabase integration tests")

    try:
        with connect(value) as conn:
            with conn.cursor() as cur:
                cur.execute("select 1")
    except OperationalError as exc:
        pytest.skip(f"Local Supabase Postgres is not reachable: {exc}")

    return value


@pytest.fixture()
def storage_config() -> tuple[str, str, str]:
    supabase_url = os.environ.get("SUPABASE_URL")
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    bucket = os.environ.get("SUPABASE_STORAGE_BUCKET", "call-audio")
    missing = [
        name
        for name, value in (
            ("SUPABASE_URL", supabase_url),
            ("SUPABASE_SERVICE_ROLE_KEY", service_role_key),
        )
        if not value
    ]
    if missing:
        pytest.skip(f"{', '.join(missing)} required for Supabase Storage integration tests")

    assert supabase_url is not None
    assert service_role_key is not None
    return supabase_url, service_role_key, bucket


@pytest.fixture()
def db_cleanup(database_url: str) -> Iterator[list[UUID]]:
    call_ids: list[UUID] = []
    yield call_ids
    if call_ids:
        with connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("delete from calls where id = any(%s)", (call_ids,))


def test_postgres_call_repository_creates_lists_and_loads_call_with_queued_job(
    database_url: str,
    db_cleanup: list[UUID],
) -> None:
    repository = PostgresCallRepository(database_url)
    call_id = uuid4()
    db_cleanup.append(call_id)
    call = CallCreate(
        id=call_id,
        original_filename="integration-call.mp3",
        content_type="audio/mpeg",
        file_size_bytes=16,
        storage_bucket="call-audio",
        storage_path=f"calls/{call_id}/integration-call-token.mp3",
        storage_etag="integration-etag",
        storage_version=None,
    )

    created = repository.create_call_with_queued_job(call)
    listed = repository.list_calls(limit=10)
    loaded = repository.get_call(call_id)

    assert created.id == call_id
    assert created.status == "queued"
    assert any(record.id == call_id for record in listed)
    assert loaded is not None
    assert loaded.id == call_id
    assert loaded.storage_path == call.storage_path

    with connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, attempt_count from call_processing_jobs where call_id = %s",
                (call_id,),
            )
            job = cur.fetchone()

    assert job is not None
    assert job["status"] == "queued"
    assert job["attempt_count"] == 0


def test_supabase_storage_uploads_under_call_path_and_deletes_object(
    storage_config: tuple[str, str, str],
) -> None:
    supabase_url, service_role_key, bucket = storage_config
    storage = SupabaseStorage(supabase_url=supabase_url, service_role_key=service_role_key)
    call_id = uuid4()
    path = f"calls/{call_id}/integration-call-token.mp3"

    try:
        stored = storage.upload_audio(
            path=path,
            content=b"integration-audio",
            content_type="audio/mpeg",
            bucket=bucket,
        )
    except CallStorageError as exc:
        pytest.skip(f"Local Supabase Storage is not reachable or bucket is missing: {exc}")

    try:
        assert stored.bucket == bucket
        assert stored.path == path
        assert stored.path.startswith(f"calls/{call_id}/")
    finally:
        storage.delete_audio(path=path, bucket=bucket)


def test_postgres_worker_repository_claims_queued_job_and_skips_completed_calls(
    database_url: str,
    db_cleanup: list[UUID],
) -> None:
    repository = PostgresWorkerRepository(database_url)
    claimable_call_id = uuid4()
    completed_call_id = uuid4()
    db_cleanup.extend([claimable_call_id, completed_call_id])

    _insert_call_with_job(
        database_url=database_url,
        call_id=claimable_call_id,
        call_status="queued",
        job_status="queued",
        call_error_code="stale_call_error",
        call_error_message="stale call error",
        job_error_code="stale_job_error",
        job_error_message="stale job error",
    )
    _insert_call_with_job(
        database_url=database_url,
        call_id=completed_call_id,
        call_status="completed",
        job_status="queued",
    )

    claimed = repository.claim_next_job(worker_id="integration-worker")
    second_claim = repository.claim_next_job(worker_id="integration-worker")

    assert claimed is not None
    assert claimed.call.id == claimable_call_id
    assert claimed.call.status == "processing"
    assert claimed.call.error_code is None
    assert claimed.call.error_message is None
    assert claimed.job.status == "processing"
    assert claimed.job.attempt_count == 1
    assert claimed.job.locked_by == "integration-worker"
    assert claimed.job.failed_at is None
    assert claimed.job.last_error_code is None
    assert claimed.job.last_error_message is None
    assert second_claim is None

    with connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select c.status as call_status, j.status as job_status
                from calls c
                join call_processing_jobs j on j.call_id = c.id
                where c.id = %s
                """,
                (completed_call_id,),
            )
            completed = cur.fetchone()

    assert completed is not None
    assert completed["call_status"] == "completed"
    assert completed["job_status"] == "queued"


def test_postgres_worker_repository_claims_only_jobs_with_transcripts_for_analysis(
    database_url: str,
    db_cleanup: list[UUID],
) -> None:
    repository = PostgresWorkerRepository(database_url)
    transcript_call_id = uuid4()
    no_transcript_call_id = uuid4()
    db_cleanup.extend([transcript_call_id, no_transcript_call_id])

    _insert_call_with_job(
        database_url=database_url,
        call_id=no_transcript_call_id,
        call_status="processing",
        job_status="queued",
    )
    _insert_call_with_job(
        database_url=database_url,
        call_id=transcript_call_id,
        call_status="processing",
        job_status="queued",
    )
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into call_transcripts (
                    call_id,
                    transcript,
                    stt_provider,
                    stt_model
                )
                values (%s, 'Customer wants pricing.', 'elevenlabs', 'scribe_v1')
                """,
                (transcript_call_id,),
            )

    claimed = repository.claim_next_job(
        worker_id="analysis-worker",
        transcript_exists=True,
    )

    assert claimed is not None
    assert claimed.call.id == transcript_call_id
    assert claimed.transcript_exists is True


def _insert_call_with_job(
    *,
    database_url: str,
    call_id: UUID,
    call_status: str,
    job_status: str,
    call_error_code: str | None = None,
    call_error_message: str | None = None,
    job_error_code: str | None = None,
    job_error_message: str | None = None,
) -> None:
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into calls (
                    id,
                    original_filename,
                    content_type,
                    file_size_bytes,
                    storage_bucket,
                    storage_path,
                    status,
                    error_code,
                    error_message
                )
                values (%s, %s, 'audio/mpeg', 16, 'call-audio', %s, %s, %s, %s)
                """,
                (
                    call_id,
                    "integration-call.mp3",
                    f"calls/{call_id}/integration-call-token.mp3",
                    call_status,
                    call_error_code,
                    call_error_message,
                ),
            )
            cur.execute(
                """
                insert into call_processing_jobs (
                    call_id,
                    status,
                    available_at,
                    last_error_code,
                    last_error_message
                )
                values (%s, %s, '2000-01-01T00:00:00Z', %s, %s)
                """,
                (call_id, job_status, job_error_code, job_error_message),
            )
