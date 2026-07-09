from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.calls.models import (
    CallAnalysisRecord,
    CallCreate,
    CallDetailRecord,
    CallIdempotencyRecord,
    CallRecord,
    CallTranscriptRecord,
    ProcessingEventRecord,
)


class CallRepositoryError(Exception):
    pass


class CallRepository(Protocol):
    def create_call_with_queued_job(
        self,
        call: CallCreate,
        *,
        idempotency_key_hash: str | None = None,
        request_fingerprint_hash: str | None = None,
        request_fingerprint: dict[str, object] | None = None,
    ) -> CallRecord:
        pass

    def get_call_by_idempotency_key(
        self,
        idempotency_key_hash: str,
    ) -> CallIdempotencyRecord | None:
        pass

    def list_calls(self, *, limit: int = 50) -> list[CallRecord]:
        pass

    def get_call(self, call_id: UUID) -> CallRecord | None:
        pass

    def get_call_detail(self, call_id: UUID) -> CallDetailRecord | None:
        pass


class PostgresCallRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def create_call_with_queued_job(
        self,
        call: CallCreate,
        *,
        idempotency_key_hash: str | None = None,
        request_fingerprint_hash: str | None = None,
        request_fingerprint: dict[str, object] | None = None,
    ) -> CallRecord:
        if idempotency_key_hash is not None and (
            request_fingerprint_hash is None or request_fingerprint is None
        ):
            raise CallRepositoryError("Idempotent call create requires a request fingerprint")

        try:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.transaction():
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
                                storage_etag,
                                storage_version,
                                status
                            )
                            values (
                                %(id)s,
                                %(original_filename)s,
                                %(content_type)s,
                                %(file_size_bytes)s,
                                %(storage_bucket)s,
                                %(storage_path)s,
                                %(storage_etag)s,
                                %(storage_version)s,
                                %(status)s
                            )
                            returning *
                            """,
                            {
                                "id": call.id,
                                "original_filename": call.original_filename,
                                "content_type": call.content_type,
                                "file_size_bytes": call.file_size_bytes,
                                "storage_bucket": call.storage_bucket,
                                "storage_path": call.storage_path,
                                "storage_etag": call.storage_etag,
                                "storage_version": call.storage_version,
                                "status": call.status,
                            },
                        )
                        row = cur.fetchone()
                        if row is None:
                            raise CallRepositoryError("Call insert returned no row")

                        cur.execute(
                            """
                            insert into call_processing_jobs (call_id, status)
                            values (%(call_id)s, 'queued')
                            returning id
                            """,
                            {"call_id": call.id},
                        )
                        job_row = cur.fetchone()
                        if job_row is None:
                            raise CallRepositoryError("Queued job insert returned no row")

                        if idempotency_key_hash is not None:
                            cur.execute(
                                """
                                insert into call_idempotency_keys (
                                    idempotency_key_hash,
                                    request_fingerprint_hash,
                                    request_fingerprint,
                                    call_id
                                )
                                values (
                                    %(idempotency_key_hash)s,
                                    %(request_fingerprint_hash)s,
                                    %(request_fingerprint)s,
                                    %(call_id)s
                                )
                                """,
                                {
                                    "idempotency_key_hash": idempotency_key_hash,
                                    "request_fingerprint_hash": request_fingerprint_hash,
                                    "request_fingerprint": Jsonb(request_fingerprint),
                                    "call_id": call.id,
                                },
                            )

                        cur.execute(
                            """
                            insert into processing_events (
                                call_id,
                                event_type,
                                message,
                                metadata
                            )
                            values (
                                %(call_id)s,
                                'call.uploaded',
                                'Call audio uploaded',
                                jsonb_build_object(
                                    'content_type', %(content_type)s::text,
                                    'file_size_bytes', %(file_size_bytes)s::bigint
                                )
                            )
                            """,
                            {
                                "call_id": call.id,
                                "content_type": call.content_type,
                                "file_size_bytes": call.file_size_bytes,
                            },
                        )
                        cur.execute(
                            """
                            insert into processing_events (
                                call_id,
                                job_id,
                                event_type,
                                message,
                                metadata
                            )
                            values (
                                %(call_id)s,
                                %(job_id)s,
                                'job.queued',
                                'Call processing job queued',
                                jsonb_build_object('stage', 'transcription')
                            )
                            """,
                            {"call_id": call.id, "job_id": job_row["id"]},
                        )
                        return _call_record_from_row(row)
        except CallRepositoryError:
            raise
        except Exception as exc:
            raise CallRepositoryError("Failed to create call and queued job") from exc

    def get_call_by_idempotency_key(
        self,
        idempotency_key_hash: str,
    ) -> CallIdempotencyRecord | None:
        try:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        select
                            c.*,
                            cik.request_fingerprint_hash as idempotency_request_fingerprint_hash
                        from call_idempotency_keys cik
                        join calls c on c.id = cik.call_id
                        where cik.idempotency_key_hash = %(idempotency_key_hash)s
                        """,
                        {"idempotency_key_hash": idempotency_key_hash},
                    )
                    row = cur.fetchone()
                    if row is None:
                        return None
                    return CallIdempotencyRecord(
                        call=_call_record_from_row(row),
                        request_fingerprint_hash=str(
                            row["idempotency_request_fingerprint_hash"]
                        ),
                    )
        except Exception as exc:
            raise CallRepositoryError("Failed to get idempotent call") from exc

    def list_calls(self, *, limit: int = 50) -> list[CallRecord]:
        try:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        select *
                        from calls
                        order by uploaded_at desc, id desc
                        limit %(limit)s
                        """,
                        {"limit": limit},
                    )
                    return [_call_record_from_row(row) for row in cur.fetchall()]
        except Exception as exc:
            raise CallRepositoryError("Failed to list calls") from exc

    def get_call(self, call_id: UUID) -> CallRecord | None:
        try:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute("select * from calls where id = %(id)s", {"id": call_id})
                    row = cur.fetchone()
                    return _call_record_from_row(row) if row else None
        except Exception as exc:
            raise CallRepositoryError("Failed to get call") from exc

    def get_call_detail(self, call_id: UUID) -> CallDetailRecord | None:
        try:
            with connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute("select * from calls where id = %(id)s", {"id": call_id})
                    call_row = cur.fetchone()
                    if call_row is None:
                        return None

                    cur.execute(
                        "select * from call_transcripts where call_id = %(call_id)s",
                        {"call_id": call_id},
                    )
                    transcript_row = cur.fetchone()

                    cur.execute(
                        "select * from call_analysis where call_id = %(call_id)s",
                        {"call_id": call_id},
                    )
                    analysis_row = cur.fetchone()

                    cur.execute(
                        """
                        select *
                        from processing_events
                        where call_id = %(call_id)s
                        order by created_at asc, id asc
                        """,
                        {"call_id": call_id},
                    )
                    event_rows = cur.fetchall()

                    return CallDetailRecord(
                        call=_call_record_from_row(call_row),
                        transcript=(
                            _transcript_record_from_row(transcript_row)
                            if transcript_row
                            else None
                        ),
                        analysis=_analysis_record_from_row(analysis_row) if analysis_row else None,
                        events=[_processing_event_record_from_row(row) for row in event_rows],
                    )
        except Exception as exc:
            raise CallRepositoryError("Failed to get call detail") from exc


def _call_record_from_row(row: dict[str, object]) -> CallRecord:
    duration = row.get("duration_seconds")
    return CallRecord(
        id=_uuid(row["id"]),
        original_filename=str(row["original_filename"]),
        content_type=str(row["content_type"]),
        file_size_bytes=int(row["file_size_bytes"]),
        storage_bucket=str(row["storage_bucket"]),
        storage_path=str(row["storage_path"]),
        status=str(row["status"]),
        uploaded_at=_datetime(row["uploaded_at"]),
        created_at=_datetime(row["created_at"]),
        updated_at=_datetime(row["updated_at"]),
        storage_etag=_optional_str(row.get("storage_etag")),
        storage_version=_optional_str(row.get("storage_version")),
        duration_seconds=float(duration) if duration is not None else None,
        error_code=_optional_str(row.get("error_code")),
        error_message=_optional_str(row.get("error_message")),
        failed_at=_optional_datetime(row.get("failed_at")),
    )


def _transcript_record_from_row(row: dict[str, object]) -> CallTranscriptRecord:
    metadata = _dict(row.get("transcript_metadata"))
    return CallTranscriptRecord(
        id=_uuid(row["id"]),
        call_id=_uuid(row["call_id"]),
        transcript=str(row["transcript"]),
        transcript_metadata=metadata,
        stt_provider=str(row["stt_provider"]),
        stt_model=_optional_str(row.get("stt_model")),
        created_at=_datetime(row["created_at"]),
        updated_at=_datetime(row["updated_at"]),
    )


def _analysis_record_from_row(row: dict[str, object]) -> CallAnalysisRecord:
    return CallAnalysisRecord(
        id=_uuid(row["id"]),
        call_id=_uuid(row["call_id"]),
        summary=str(row["summary"]),
        tags=_dict(row.get("tags")),
        intent=_optional_str(row.get("intent")),
        sentiment=_optional_str(row.get("sentiment")),
        next_action=_optional_str(row.get("next_action")),
        risk_flags=_str_list(row.get("risk_flags")),
        llm_provider=str(row["llm_provider"]),
        llm_model=str(row["llm_model"]),
        prompt_version=str(row["prompt_version"]),
        raw_llm_output=_optional_dict(row.get("raw_llm_output")),
        created_at=_datetime(row["created_at"]),
        updated_at=_datetime(row["updated_at"]),
    )


def _processing_event_record_from_row(row: dict[str, object]) -> ProcessingEventRecord:
    return ProcessingEventRecord(
        id=_uuid(row["id"]),
        call_id=_optional_uuid(row.get("call_id")),
        job_id=_optional_uuid(row.get("job_id")),
        event_type=str(row["event_type"]),
        message=_optional_str(row.get("message")),
        metadata=_dict(row.get("metadata")),
        created_at=_datetime(row["created_at"]),
    )


def _uuid(value: object) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _optional_uuid(value: object | None) -> UUID | None:
    return _uuid(value) if value is not None else None


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _optional_datetime(value: object | None) -> datetime | None:
    return _datetime(value) if value is not None else None


def _optional_str(value: object | None) -> str | None:
    return str(value) if value is not None else None


def _dict(value: object | None) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _optional_dict(value: object | None) -> dict[str, object] | None:
    return _dict(value) if value is not None else None


def _str_list(value: object | None) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []
