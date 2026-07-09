from __future__ import annotations

import hashlib
import json
import re
import secrets
import logging
from pathlib import Path
from uuid import UUID, uuid4

from app.calls.models import (
    CallAnalysisRecord,
    CallCreate,
    CallDetailRecord,
    CallRecord,
    TagOverrideCreate,
    TagOverrideRecord,
)
from app.calls.repository import CallRepository, CallRepositoryError
from app.calls.storage import CallStorage, CallStorageError


ALLOWED_CONTENT_TYPES = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/x-wav": "wav",
}

ALLOWED_EXTENSIONS = {"mp3", "wav"}

logger = logging.getLogger(__name__)


class InvalidCallUploadError(Exception):
    pass


class CallIngestionError(Exception):
    pass


class CallPersistenceError(Exception):
    def __init__(self, message: str, *, cleanup_failed: bool = False) -> None:
        super().__init__(message)
        self.cleanup_failed = cleanup_failed


class IdempotencyConflictError(Exception):
    pass


class CallNotFoundError(Exception):
    pass


class CallAnalysisRequiredError(Exception):
    pass


class TagOverrideNotFoundError(Exception):
    pass


class CallService:
    def __init__(
        self,
        *,
        repository: CallRepository,
        storage: CallStorage,
        storage_bucket: str,
        max_upload_bytes: int,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._storage_bucket = storage_bucket
        self._max_upload_bytes = max_upload_bytes

    def ingest_call(
        self,
        *,
        filename: str | None,
        content_type: str | None,
        content: bytes,
        idempotency_key: str | None = None,
    ) -> CallRecord:
        validated_filename, extension = self._validate_upload(
            filename=filename,
            content_type=content_type,
            content=content,
        )
        assert content_type is not None
        idempotency_key_hash: str | None = None
        request_fingerprint_hash: str | None = None
        request_fingerprint: dict[str, object] | None = None
        if idempotency_key is not None:
            idempotency_key_hash = _hash_text(_validate_idempotency_key(idempotency_key))
            request_fingerprint = _request_fingerprint(
                filename=validated_filename,
                content_type=content_type,
                content=content,
            )
            request_fingerprint_hash = _fingerprint_hash(request_fingerprint)
            try:
                existing = self._repository.get_call_by_idempotency_key(idempotency_key_hash)
            except CallRepositoryError as exc:
                raise CallPersistenceError("Could not load idempotent call") from exc
            if existing is not None:
                if existing.request_fingerprint_hash != request_fingerprint_hash:
                    raise IdempotencyConflictError(
                        "Idempotency-Key was already used for a different request"
                    )
                return existing.call

        call_id = uuid4()
        slug = _slugify(Path(validated_filename).stem)
        upload_token = secrets.token_urlsafe(12)
        storage_path = f"calls/{call_id}/{slug}-{upload_token}.{extension}"

        try:
            stored_object = self._storage.upload_audio(
                path=storage_path,
                content=content,
                content_type=content_type,
                bucket=self._storage_bucket,
            )
        except CallStorageError as exc:
            logger.exception("Call audio upload failed", extra={"call_id": str(call_id)})
            raise CallIngestionError("Could not store uploaded audio") from exc

        call = CallCreate(
            id=call_id,
            original_filename=validated_filename,
            content_type=content_type,
            file_size_bytes=len(content),
            storage_bucket=stored_object.bucket,
            storage_path=stored_object.path,
            storage_etag=stored_object.etag,
            storage_version=stored_object.version,
        )
        try:
            return self._repository.create_call_with_queued_job(
                call,
                idempotency_key_hash=idempotency_key_hash,
                request_fingerprint_hash=request_fingerprint_hash,
                request_fingerprint=request_fingerprint,
            )
        except CallRepositoryError as exc:
            cleanup_failed = False
            logger.exception(
                "Call persistence failed after audio upload",
                extra={"call_id": str(call_id), "storage_path": stored_object.path},
            )
            try:
                self._storage.delete_audio(
                    path=stored_object.path,
                    bucket=stored_object.bucket,
                )
            except CallStorageError:
                cleanup_failed = True
                logger.exception(
                    "Uploaded call audio cleanup failed",
                    extra={"call_id": str(call_id), "storage_path": stored_object.path},
                )
            raise CallPersistenceError(
                "Could not persist uploaded call",
                cleanup_failed=cleanup_failed,
            ) from exc

    def list_calls(self, *, limit: int = 50) -> list[CallRecord]:
        try:
            return self._repository.list_calls(limit=limit)
        except CallRepositoryError as exc:
            raise CallPersistenceError("Could not list calls") from exc

    def get_call(self, call_id: UUID) -> CallRecord | None:
        try:
            return self._repository.get_call(call_id)
        except CallRepositoryError as exc:
            raise CallPersistenceError("Could not load call") from exc

    def get_call_detail(self, call_id: UUID) -> CallDetailRecord | None:
        try:
            return self._repository.get_call_detail(call_id)
        except CallRepositoryError as exc:
            raise CallPersistenceError("Could not load call") from exc

    def list_tag_overrides(self, call_id: UUID) -> list[TagOverrideRecord]:
        try:
            if self._repository.get_call(call_id) is None:
                raise CallNotFoundError("Call not found")
            return self._repository.list_tag_overrides(call_id)
        except CallNotFoundError:
            raise
        except CallRepositoryError as exc:
            raise CallPersistenceError("Could not list tag overrides") from exc

    def create_tag_override(
        self,
        *,
        call_id: UUID,
        field: str,
        override_value: object,
        reason: str | None,
        created_by: str | None,
    ) -> TagOverrideRecord:
        try:
            detail = self._repository.get_call_detail(call_id)
            if detail is None:
                raise CallNotFoundError("Call not found")
            if detail.analysis is None:
                raise CallAnalysisRequiredError("Call analysis is required before overriding tags")
            return self._repository.create_tag_override(
                TagOverrideCreate(
                    call_id=call_id,
                    field=field,
                    original_value=_analysis_field_value(detail.analysis, field),
                    override_value=override_value,
                    reason=reason,
                    created_by=created_by,
                )
            )
        except (CallNotFoundError, CallAnalysisRequiredError):
            raise
        except CallRepositoryError as exc:
            raise CallPersistenceError("Could not create tag override") from exc

    def delete_tag_override(self, *, call_id: UUID, override_id: UUID) -> None:
        try:
            if self._repository.get_call(call_id) is None:
                raise CallNotFoundError("Call not found")
            if not self._repository.delete_tag_override(call_id=call_id, override_id=override_id):
                raise TagOverrideNotFoundError("Tag override not found")
        except (CallNotFoundError, TagOverrideNotFoundError):
            raise
        except CallRepositoryError as exc:
            raise CallPersistenceError("Could not delete tag override") from exc

    def _validate_upload(
        self,
        *,
        filename: str | None,
        content_type: str | None,
        content: bytes,
    ) -> tuple[str, str]:
        if not filename or not filename.strip():
            raise InvalidCallUploadError("Audio upload must include a filename")
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise InvalidCallUploadError("Audio upload must be a WAV or MP3 file")
        if not content:
            raise InvalidCallUploadError("Audio upload must not be empty")
        if len(content) > self._max_upload_bytes:
            raise InvalidCallUploadError("Audio upload exceeds the maximum size")

        extension = Path(filename).suffix.lower().lstrip(".")
        if extension not in ALLOWED_EXTENSIONS:
            raise InvalidCallUploadError("Audio filename must end in .wav or .mp3")
        expected_extension = ALLOWED_CONTENT_TYPES[content_type]
        if extension != expected_extension:
            raise InvalidCallUploadError("Audio filename extension does not match content type")

        return Path(filename).name, extension


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "call"


def _validate_idempotency_key(value: str) -> str:
    key = value.strip()
    if not key:
        raise InvalidCallUploadError("Idempotency-Key must not be empty")
    if len(key.encode("utf-8")) > 255:
        raise InvalidCallUploadError("Idempotency-Key must be 255 bytes or fewer")
    return key


def _request_fingerprint(
    *,
    filename: str,
    content_type: str,
    content: bytes,
) -> dict[str, object]:
    return {
        "filename": filename,
        "content_type": content_type,
        "file_size_bytes": len(content),
        "content_sha256": hashlib.sha256(content).hexdigest(),
    }


def _fingerprint_hash(fingerprint: dict[str, object]) -> str:
    canonical = json.dumps(fingerprint, sort_keys=True, separators=(",", ":"))
    return _hash_text(canonical)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _analysis_field_value(analysis: CallAnalysisRecord, field: str) -> object:
    if field in {"call_outcome", "customer_intent"}:
        return analysis.tags.get(field)
    if field == "sentiment":
        return analysis.sentiment
    if field == "next_action":
        return analysis.next_action
    if field == "risk_flags":
        return analysis.risk_flags
    return None
