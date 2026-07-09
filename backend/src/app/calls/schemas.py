from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


TagOverrideField = Literal[
    "call_outcome",
    "customer_intent",
    "sentiment",
    "next_action",
    "risk_flags",
]


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


class TagOverrideRequest(BaseModel):
    field: TagOverrideField
    override_value: Any
    reason: str | None = Field(default=None, max_length=1000)
    created_by: str | None = Field(default=None, max_length=255)

    @field_validator("override_value")
    @classmethod
    def override_value_must_not_be_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("override_value must not be null")
        return value


class TagOverrideResponse(BaseModel):
    override_id: UUID
    call_id: UUID
    field: str
    original_value: Any = None
    override_value: Any
    reason: str | None = None
    created_by: str | None = None
    created_at: datetime


class TagOverrideListResponse(BaseModel):
    overrides: list[TagOverrideResponse]


class ProcessingEventResponse(BaseModel):
    event_id: UUID
    event_type: str
    message: str | None = None
    metadata: dict[str, Any]
    created_at: datetime


class CallProcessingJobDiagnosticsResponse(BaseModel):
    status: str
    stage: str
    attempt_count: int
    max_attempts: int
    available_at: datetime
    locked_at: datetime | None = None
    locked_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None


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
    processing_job: CallProcessingJobDiagnosticsResponse | None = None
    events: list[ProcessingEventResponse] = Field(default_factory=list)


class CallListResponse(BaseModel):
    calls: list[CallSummaryResponse]
