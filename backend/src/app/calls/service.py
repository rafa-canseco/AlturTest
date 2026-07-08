from __future__ import annotations

import re
import secrets
import logging
from pathlib import Path
from uuid import UUID, uuid4

from app.calls.models import CallCreate, CallRecord
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
    ) -> CallRecord:
        validated_filename, extension = self._validate_upload(
            filename=filename,
            content_type=content_type,
            content=content,
        )
        assert content_type is not None

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
            return self._repository.create_call_with_queued_job(call)
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

    def list_calls(self) -> list[CallRecord]:
        try:
            return self._repository.list_calls()
        except CallRepositoryError as exc:
            raise CallPersistenceError("Could not list calls") from exc

    def get_call(self, call_id: UUID) -> CallRecord | None:
        try:
            return self._repository.get_call(call_id)
        except CallRepositoryError as exc:
            raise CallPersistenceError("Could not load call") from exc

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
