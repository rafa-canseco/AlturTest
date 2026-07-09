from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.calls.models import CallProcessingJobRecord, ClaimedCallProcessingJob
from app.calls.repository import _call_record_from_row, _datetime, _optional_datetime, _optional_str, _uuid


class WorkerRepositoryError(Exception):
    pass


class WorkerRepository(Protocol):
    def claim_next_job(self, *, worker_id: str) -> ClaimedCallProcessingJob | None:
        pass

    def complete_job(self, *, job_id: UUID, call_id: UUID) -> None:
        pass

    def mark_job_pending_analysis(self, *, job_id: UUID, call_id: UUID) -> None:
        pass

    def fail_job(self, *, job_id: UUID, call_id: UUID, error_code: str, error_message: str) -> None:
        pass

    def requeue_failed_job(self, *, call_id: UUID) -> bool:
        pass

    def has_transcript(self, *, call_id: UUID) -> bool:
        pass

    def create_transcript(
        self,
        *,
        call_id: UUID,
        transcript: str,
        stt_provider: str,
        stt_model: str,
        transcript_metadata: dict[str, Any],
    ) -> bool:
        pass


class PostgresWorkerRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def claim_next_job(self, *, worker_id: str) -> ClaimedCallProcessingJob | None:
        try:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            select j.*
                            from call_processing_jobs j
                            join calls c on c.id = j.call_id
                            where j.status = 'queued'
                              and j.available_at <= now()
                              and j.attempt_count < j.max_attempts
                              and c.status <> 'completed'
                            order by j.available_at asc, j.created_at asc
                            for update of j skip locked
                            limit 1
                            """
                        )
                        job_row = cur.fetchone()
                        if job_row is None:
                            return None

                        cur.execute(
                            """
                            update call_processing_jobs
                            set status = 'processing',
                                attempt_count = attempt_count + 1,
                                locked_at = now(),
                                locked_by = %(worker_id)s,
                                started_at = coalesce(started_at, now()),
                                completed_at = null,
                                failed_at = null,
                                last_error_code = null,
                                last_error_message = null
                            where id = %(job_id)s
                              and status = 'queued'
                              and attempt_count < max_attempts
                            returning *
                            """,
                            {"job_id": job_row["id"], "worker_id": worker_id},
                        )
                        claimed_job_row = cur.fetchone()
                        if claimed_job_row is None:
                            return None

                        cur.execute(
                            """
                            update calls
                            set status = 'processing',
                                failed_at = null,
                                error_code = null,
                                error_message = null
                            where id = %(call_id)s
                              and status <> 'completed'
                            returning *
                            """,
                            {"call_id": claimed_job_row["call_id"]},
                        )
                        call_row = cur.fetchone()
                        if call_row is None:
                            raise WorkerRepositoryError(
                                "Call was completed before the job claim could be recorded"
                            )

                        return ClaimedCallProcessingJob(
                            job=_job_record_from_row(claimed_job_row),
                            call=_call_record_from_row(call_row),
                        )
        except Exception as exc:
            raise WorkerRepositoryError("Failed to claim queued call processing job") from exc

    def complete_job(self, *, job_id: UUID, call_id: UUID) -> None:
        try:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            update calls
                            set status = 'completed',
                                failed_at = null,
                                error_code = null,
                                error_message = null
                            where id = %(call_id)s
                              and status = 'processing'
                            """,
                            {"call_id": call_id},
                        )
                        cur.execute(
                            """
                            update call_processing_jobs
                            set status = 'completed',
                                completed_at = now(),
                                failed_at = null,
                                last_error_code = null,
                                last_error_message = null
                            where id = %(job_id)s
                              and call_id = %(call_id)s
                              and status = 'processing'
                            """,
                            {"job_id": job_id, "call_id": call_id},
                        )
        except Exception as exc:
            raise WorkerRepositoryError("Failed to complete call processing job") from exc

    def mark_job_pending_analysis(self, *, job_id: UUID, call_id: UUID) -> None:
        try:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            update calls
                            set status = 'processing',
                                failed_at = null,
                                error_code = null,
                                error_message = null
                            where id = %(call_id)s
                              and status = 'processing'
                            """,
                            {"call_id": call_id},
                        )
                        cur.execute(
                            """
                            update call_processing_jobs
                            set status = 'completed',
                                locked_at = null,
                                locked_by = null,
                                completed_at = now(),
                                failed_at = null,
                                last_error_code = null,
                                last_error_message = null
                            where id = %(job_id)s
                              and call_id = %(call_id)s
                              and status = 'processing'
                            """,
                            {"job_id": job_id, "call_id": call_id},
                        )
        except Exception as exc:
            raise WorkerRepositoryError("Failed to mark call processing job pending analysis") from exc

    def fail_job(self, *, job_id: UUID, call_id: UUID, error_code: str, error_message: str) -> None:
        try:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            update calls
                            set status = 'failed',
                                failed_at = now(),
                                error_code = %(error_code)s,
                                error_message = %(error_message)s
                            where id = %(call_id)s
                              and status <> 'completed'
                            """,
                            {
                                "call_id": call_id,
                                "error_code": error_code,
                                "error_message": error_message,
                            },
                        )
                        cur.execute(
                            """
                            update call_processing_jobs
                            set status = 'failed',
                                failed_at = now(),
                                last_error_code = %(error_code)s,
                                last_error_message = %(error_message)s
                            where id = %(job_id)s
                              and call_id = %(call_id)s
                              and status <> 'completed'
                            """,
                            {
                                "job_id": job_id,
                                "call_id": call_id,
                                "error_code": error_code,
                                "error_message": error_message,
                            },
                        )
        except Exception as exc:
            raise WorkerRepositoryError("Failed to mark call processing job failed") from exc

    def requeue_failed_job(self, *, call_id: UUID) -> bool:
        try:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            update calls
                            set status = 'queued',
                                failed_at = null,
                                error_code = null,
                                error_message = null
                            where id = %(call_id)s
                              and status = 'failed'
                              and exists (
                                  select 1
                                  from call_processing_jobs
                                  where call_id = %(call_id)s
                                    and status = 'failed'
                                    and attempt_count < max_attempts
                              )
                            """,
                            {"call_id": call_id},
                        )
                        cur.execute(
                            """
                            update call_processing_jobs
                            set status = 'queued',
                                available_at = now(),
                                locked_at = null,
                                locked_by = null,
                                completed_at = null,
                                failed_at = null,
                                last_error_code = null,
                                last_error_message = null
                            where call_id = %(call_id)s
                              and status = 'failed'
                              and attempt_count < max_attempts
                            """,
                            {"call_id": call_id},
                        )
                        return cur.rowcount > 0
        except Exception as exc:
            raise WorkerRepositoryError("Failed to requeue failed call processing job") from exc

    def has_transcript(self, *, call_id: UUID) -> bool:
        try:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "select 1 from call_transcripts where call_id = %(call_id)s",
                        {"call_id": call_id},
                    )
                    return cur.fetchone() is not None
        except Exception as exc:
            raise WorkerRepositoryError("Failed to check call transcript") from exc

    def create_transcript(
        self,
        *,
        call_id: UUID,
        transcript: str,
        stt_provider: str,
        stt_model: str,
        transcript_metadata: dict[str, Any],
    ) -> bool:
        try:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        insert into call_transcripts (
                            call_id,
                            transcript,
                            transcript_metadata,
                            stt_provider,
                            stt_model
                        )
                        values (
                            %(call_id)s,
                            %(transcript)s,
                            %(transcript_metadata)s,
                            %(stt_provider)s,
                            %(stt_model)s
                        )
                        on conflict (call_id) do nothing
                        """,
                        {
                            "call_id": call_id,
                            "transcript": transcript,
                            "transcript_metadata": Jsonb(transcript_metadata),
                            "stt_provider": stt_provider,
                            "stt_model": stt_model,
                        },
                    )
                    return cur.rowcount == 1
        except Exception as exc:
            raise WorkerRepositoryError("Failed to create call transcript") from exc


def _job_record_from_row(row: dict[str, object]) -> CallProcessingJobRecord:
    return CallProcessingJobRecord(
        id=_uuid(row["id"]),
        call_id=_uuid(row["call_id"]),
        status=str(row["status"]),
        attempt_count=int(row["attempt_count"]),
        max_attempts=int(row["max_attempts"]),
        available_at=_datetime(row["available_at"]),
        locked_at=_optional_datetime(row.get("locked_at")),
        locked_by=_optional_str(row.get("locked_by")),
        started_at=_optional_datetime(row.get("started_at")),
        completed_at=_optional_datetime(row.get("completed_at")),
        failed_at=_optional_datetime(row.get("failed_at")),
        last_error_code=_optional_str(row.get("last_error_code")),
        last_error_message=_optional_str(row.get("last_error_message")),
        created_at=_datetime(row["created_at"]),
        updated_at=_datetime(row["updated_at"]),
    )
