from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, UploadFile, status

from app.calls.analysis_insights import normalize_analysis_insights
from app.calls.models import (
    CallAnalysisRecord,
    CallDetailRecord,
    CallRecord,
    CallTranscriptRecord,
    ProcessingEventRecord,
    TagOverrideRecord,
)
from app.calls.schemas import (
    CallAnalysisResponse,
    CallDetailResponse,
    CallListResponse,
    CallProcessingJobDiagnosticsResponse,
    ProcessingEventResponse,
    CallSummaryResponse,
    CallTranscriptResponse,
    TagOverrideListResponse,
    TagOverrideRequest,
    TagOverrideResponse,
)
from app.calls.service import (
    CallAnalysisRequiredError,
    CallIngestionError,
    IdempotencyConflictError,
    CallPersistenceError,
    CallNotFoundError,
    CallService,
    InvalidCallUploadError,
    TagOverrideNotFoundError,
)


router = APIRouter(prefix="/calls", tags=["calls"])


@router.post(
    "",
    response_model=CallSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_call(
    request: Request,
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CallSummaryResponse:
    service = _call_service(request)
    content = file.file.read()
    try:
        record = service.ingest_call(
            filename=file.filename,
            content_type=file.content_type,
            content=content,
            idempotency_key=idempotency_key,
        )
    except InvalidCallUploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except CallIngestionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not store uploaded audio",
        ) from exc
    except CallPersistenceError as exc:
        detail = "Could not queue uploaded call"
        if exc.cleanup_failed:
            detail = "Could not queue uploaded call; uploaded audio cleanup also failed"
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc

    return _summary_response(record)


@router.get("", response_model=CallListResponse)
def list_calls(request: Request, limit: int = Query(default=50, ge=1, le=100)) -> CallListResponse:
    service = _call_service(request)
    try:
        calls = service.list_calls(limit=limit)
    except CallPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not list calls",
        ) from exc
    return CallListResponse(calls=[_summary_response(call) for call in calls])


@router.get("/{call_id}", response_model=CallDetailResponse)
def get_call(request: Request, call_id: UUID) -> CallDetailResponse:
    service = _call_service(request)
    try:
        detail = service.get_call_detail(call_id)
    except CallPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not load call",
        ) from exc
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    return _detail_response(detail)


@router.get("/{call_id}/tag-overrides", response_model=TagOverrideListResponse)
def list_tag_overrides(request: Request, call_id: UUID) -> TagOverrideListResponse:
    service = _call_service(request)
    try:
        overrides = service.list_tag_overrides(call_id)
    except CallNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found") from exc
    except CallPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not list tag overrides",
        ) from exc
    return TagOverrideListResponse(
        overrides=[_tag_override_response(override) for override in overrides]
    )


@router.post(
    "/{call_id}/tag-overrides",
    response_model=TagOverrideResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_tag_override(
    request: Request,
    call_id: UUID,
    payload: TagOverrideRequest,
) -> TagOverrideResponse:
    service = _call_service(request)
    try:
        override = service.create_tag_override(
            call_id=call_id,
            field=payload.field,
            override_value=payload.override_value,
            reason=payload.reason,
            created_by=payload.created_by,
        )
    except CallNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found") from exc
    except CallAnalysisRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Call analysis is required before overriding tags",
        ) from exc
    except CallPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not create tag override",
        ) from exc
    return _tag_override_response(override)


@router.delete(
    "/{call_id}/tag-overrides/{override_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_tag_override(request: Request, call_id: UUID, override_id: UUID) -> None:
    service = _call_service(request)
    try:
        service.delete_tag_override(call_id=call_id, override_id=override_id)
    except CallNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found") from exc
    except TagOverrideNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag override not found",
        ) from exc
    except CallPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not delete tag override",
        ) from exc


def _call_service(request: Request) -> CallService:
    return request.app.state.call_service


def _summary_response(call: CallRecord) -> CallSummaryResponse:
    return CallSummaryResponse(
        call_id=call.id,
        filename=call.original_filename,
        status=call.status,
        uploaded_at=call.uploaded_at,
        file_size_bytes=call.file_size_bytes,
        content_type=call.content_type,
        error_code=call.error_code,
        error_message=call.error_message,
    )


def _detail_response(detail: CallDetailRecord) -> CallDetailResponse:
    call = detail.call
    return CallDetailResponse(
        **_summary_response(call).model_dump(),
        storage_bucket=call.storage_bucket,
        storage_path=call.storage_path,
        storage_etag=call.storage_etag,
        storage_version=call.storage_version,
        duration_seconds=call.duration_seconds,
        failed_at=call.failed_at,
        created_at=call.created_at,
        updated_at=call.updated_at,
        transcript=(
            _transcript_response(detail.transcript) if detail.transcript is not None else None
        ),
        analysis=_analysis_response(detail.analysis) if detail.analysis is not None else None,
        processing_job=_processing_job_response(detail),
        events=[_processing_event_response(event) for event in detail.events or []],
    )


def _transcript_response(transcript: CallTranscriptRecord) -> CallTranscriptResponse:
    language_code = transcript.transcript_metadata.get("language_code")
    return CallTranscriptResponse(
        text=transcript.transcript,
        provider=transcript.stt_provider,
        model=transcript.stt_model,
        language_code=str(language_code) if language_code is not None else None,
        metadata=transcript.transcript_metadata,
        created_at=transcript.created_at,
        updated_at=transcript.updated_at,
    )


def _analysis_response(analysis: CallAnalysisRecord) -> CallAnalysisResponse:
    return CallAnalysisResponse(
        summary=analysis.summary,
        tags=analysis.tags,
        intent=analysis.intent,
        sentiment=analysis.sentiment,
        next_action=analysis.next_action,
        risk_flags=analysis.risk_flags,
        insights=normalize_analysis_insights(
            analysis.raw_llm_output.get("insights") if analysis.raw_llm_output else None
        ),
        provider=analysis.llm_provider,
        model=analysis.llm_model,
        prompt_version=analysis.prompt_version,
        raw_output=analysis.raw_llm_output,
        created_at=analysis.created_at,
        updated_at=analysis.updated_at,
    )


def _tag_override_response(override: TagOverrideRecord) -> TagOverrideResponse:
    return TagOverrideResponse(
        override_id=override.id,
        call_id=override.call_id,
        field=override.field,
        original_value=override.original_value,
        override_value=override.override_value,
        reason=override.reason,
        created_by=override.created_by,
        created_at=override.created_at,
    )


def _processing_event_response(event: ProcessingEventRecord) -> ProcessingEventResponse:
    return ProcessingEventResponse(
        event_id=event.id,
        event_type=event.event_type,
        message=event.message,
        metadata=event.metadata,
        created_at=event.created_at,
    )


def _processing_job_response(
    detail: CallDetailRecord,
) -> CallProcessingJobDiagnosticsResponse | None:
    job = detail.job
    if job is None:
        return None
    return CallProcessingJobDiagnosticsResponse(
        status=job.status,
        stage=_processing_stage(detail),
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        available_at=job.available_at,
        locked_at=job.locked_at,
        locked_by=_safe_locked_by(job.locked_by),
        started_at=job.started_at,
        completed_at=job.completed_at,
        failed_at=job.failed_at,
        last_error_code=job.last_error_code,
        last_error_message=job.last_error_message,
    )


def _processing_stage(detail: CallDetailRecord) -> str:
    call = detail.call
    job = detail.job
    if call.status == "completed" or job is not None and job.status == "completed":
        return "completed"
    if call.status == "failed" or job is not None and job.status == "failed":
        return "failed"
    if detail.analysis is not None:
        return "completed"
    if detail.transcript is not None:
        return "analysis"
    return "transcription"


def _safe_locked_by(locked_by: str | None) -> str | None:
    if locked_by is None:
        return None
    digest = sha256(locked_by.encode("utf-8")).hexdigest()[:12]
    return f"worker-{digest}"
