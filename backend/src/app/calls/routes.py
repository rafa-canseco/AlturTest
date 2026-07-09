from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status

from app.calls.models import (
    CallAnalysisRecord,
    CallDetailRecord,
    CallRecord,
    CallTranscriptRecord,
)
from app.calls.schemas import (
    CallAnalysisResponse,
    CallDetailResponse,
    CallListResponse,
    CallSummaryResponse,
    CallTranscriptResponse,
)
from app.calls.service import (
    CallIngestionError,
    CallPersistenceError,
    CallService,
    InvalidCallUploadError,
)


router = APIRouter(prefix="/calls", tags=["calls"])


@router.post(
    "",
    response_model=CallSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_call(request: Request, file: UploadFile = File(...)) -> CallSummaryResponse:
    service = _call_service(request)
    content = file.file.read()
    try:
        record = service.ingest_call(
            filename=file.filename,
            content_type=file.content_type,
            content=content,
        )
    except InvalidCallUploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
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
        provider=analysis.llm_provider,
        model=analysis.llm_model,
        prompt_version=analysis.prompt_version,
        raw_output=analysis.raw_llm_output,
        created_at=analysis.created_at,
        updated_at=analysis.updated_at,
    )
