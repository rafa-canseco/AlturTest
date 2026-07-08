from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


CallStatus = str


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
