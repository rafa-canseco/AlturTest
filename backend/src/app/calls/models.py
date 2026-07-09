from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


CallStatus = str
CallProcessingJobStatus = str


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    path: str
    etag: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class CallCreate:
    id: UUID
    original_filename: str
    content_type: str
    file_size_bytes: int
    storage_bucket: str
    storage_path: str
    storage_etag: str | None
    storage_version: str | None
    status: CallStatus = "queued"


@dataclass(frozen=True)
class CallRecord:
    id: UUID
    original_filename: str
    content_type: str
    file_size_bytes: int
    storage_bucket: str
    storage_path: str
    status: CallStatus
    uploaded_at: datetime
    created_at: datetime
    updated_at: datetime
    storage_etag: str | None = None
    storage_version: str | None = None
    duration_seconds: float | None = None
    error_code: str | None = None
    error_message: str | None = None
    failed_at: datetime | None = None


@dataclass(frozen=True)
class CallProcessingJobRecord:
    id: UUID
    call_id: UUID
    status: CallProcessingJobStatus
    attempt_count: int
    max_attempts: int
    available_at: datetime
    created_at: datetime
    updated_at: datetime
    locked_at: datetime | None = None
    locked_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None


@dataclass(frozen=True)
class ClaimedCallProcessingJob:
    job: CallProcessingJobRecord
    call: CallRecord
    transcript_exists: bool = False


@dataclass(frozen=True)
class CallTranscriptRecord:
    id: UUID
    call_id: UUID
    transcript: str
    transcript_metadata: dict[str, Any]
    stt_provider: str
    stt_model: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CallAnalysisRecord:
    id: UUID
    call_id: UUID
    summary: str
    tags: dict[str, Any]
    intent: str | None
    sentiment: str | None
    next_action: str | None
    risk_flags: list[str]
    llm_provider: str
    llm_model: str
    prompt_version: str
    raw_llm_output: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CallDetailRecord:
    call: CallRecord
    transcript: CallTranscriptRecord | None = None
    analysis: CallAnalysisRecord | None = None


@dataclass(frozen=True)
class CallAnalysisCreate:
    call_id: UUID
    summary: str
    tags: dict[str, Any]
    intent: str | None
    sentiment: str | None
    next_action: str | None
    risk_flags: list[str]
    llm_provider: str
    llm_model: str
    prompt_version: str
    raw_llm_output: dict[str, Any]
