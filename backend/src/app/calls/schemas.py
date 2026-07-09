from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CallSummaryResponse(BaseModel):
    call_id: UUID
    filename: str
    status: str
    uploaded_at: datetime
    file_size_bytes: int
    content_type: str
    error_code: str | None = None
    error_message: str | None = None


class CallTranscriptResponse(BaseModel):
    text: str
    provider: str
    model: str | None = None
    language_code: str | None = None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class CallAnalysisResponse(BaseModel):
    summary: str
    tags: dict[str, Any]
    intent: str | None = None
    sentiment: str | None = None
    next_action: str | None = None
    risk_flags: list[str]
    provider: str
    model: str
    prompt_version: str
    raw_output: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class ProcessingEventResponse(BaseModel):
    event_id: UUID
    event_type: str
    message: str | None = None
    metadata: dict[str, Any]
    created_at: datetime


class CallDetailResponse(CallSummaryResponse):
    storage_bucket: str
    storage_path: str
    storage_etag: str | None = None
    storage_version: str | None = None
    duration_seconds: float | None = None
    failed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    transcript: CallTranscriptResponse | None = None
    analysis: CallAnalysisResponse | None = None
    events: list[ProcessingEventResponse] = Field(default_factory=list)


class CallListResponse(BaseModel):
    calls: list[CallSummaryResponse]
