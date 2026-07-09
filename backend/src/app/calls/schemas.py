from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CallSummaryResponse(BaseModel):
    call_id: UUID
    filename: str
    status: str
    uploaded_at: datetime
    file_size_bytes: int
    content_type: str
    error_code: str | None = None
    error_message: str | None = None


class CallDetailResponse(CallSummaryResponse):
    storage_bucket: str
    storage_path: str
    storage_etag: str | None = None
    storage_version: str | None = None
    duration_seconds: float | None = None
    failed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CallListResponse(BaseModel):
    calls: list[CallSummaryResponse]
