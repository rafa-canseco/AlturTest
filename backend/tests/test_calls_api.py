from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.calls.models import CallCreate, CallRecord, StoredObject
from app.calls.repository import CallRepositoryError
from app.calls.storage import CallStorageError
from app.config import Settings
from app.main import create_app


def test_create_call_uploads_audio_and_queues_job() -> None:
    repository = FakeCallRepository()
    storage = FakeCallStorage()
    client = _client(repository=repository, storage=storage)

    response = client.post(
        "/calls",
        files={"file": ("Sales Call.mp3", b"audio-bytes", "audio/mpeg")},
    )

    assert response.status_code == 201
    body = response.json()
    call_id = UUID(body["call_id"])
    assert body["filename"] == "Sales Call.mp3"
    assert body["status"] == "queued"
    assert body["file_size_bytes"] == len(b"audio-bytes")
    assert body["content_type"] == "audio/mpeg"

    assert len(storage.uploads) == 1
    upload = storage.uploads[0]
    assert upload["bucket"] == "call-audio"
    assert upload["path"].startswith(f"calls/{call_id}/sales-call-")
    assert upload["path"].endswith(".mp3")
    assert upload["content"] == b"audio-bytes"

    assert repository.created_calls[0].id == call_id
    assert repository.created_calls[0].storage_path == upload["path"]
    assert repository.created_calls[0].status == "queued"
    assert repository.created_jobs == [call_id]


def test_create_call_rejects_invalid_file_type() -> None:
    repository = FakeCallRepository()
    storage = FakeCallStorage()
    client = _client(repository=repository, storage=storage)

    response = client.post(
        "/calls",
        files={"file": ("notes.txt", b"not audio", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Audio upload must be a WAV or MP3 file"
    assert storage.uploads == []
    assert repository.created_calls == []


def test_create_call_returns_safe_error_when_storage_fails() -> None:
    repository = FakeCallRepository()
    storage = FakeCallStorage(fail_upload=True)
    client = _client(repository=repository, storage=storage)

    response = client.post(
        "/calls",
        files={"file": ("sales.wav", b"audio-bytes", "audio/wav")},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not store uploaded audio"
    assert repository.created_calls == []


def test_create_call_deletes_uploaded_audio_when_repository_fails() -> None:
    repository = FakeCallRepository(fail_create=True)
    storage = FakeCallStorage()
    client = _client(repository=repository, storage=storage)

    response = client.post(
        "/calls",
        files={"file": ("sales.wav", b"audio-bytes", "audio/wav")},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Could not queue uploaded call"
    assert len(storage.uploads) == 1
    assert storage.deletes == [
        {"bucket": "call-audio", "path": storage.uploads[0]["path"]},
    ]
    assert repository.created_jobs == []


def test_create_call_reports_cleanup_failure_safely() -> None:
    repository = FakeCallRepository(fail_create=True)
    storage = FakeCallStorage(fail_delete=True)
    client = _client(repository=repository, storage=storage)

    response = client.post(
        "/calls",
        files={"file": ("sales.wav", b"audio-bytes", "audio/wav")},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Could not queue uploaded call; uploaded audio cleanup also failed"
    )
    assert storage.delete_attempts == 1


def test_list_calls_returns_call_summaries() -> None:
    first = _record(original_filename="first.mp3", uploaded_at=_dt("2026-07-08T10:00:00+00:00"))
    second = _record(original_filename="second.wav", uploaded_at=_dt("2026-07-08T11:00:00+00:00"))
    repository = FakeCallRepository(records=[second, first])
    client = _client(repository=repository, storage=FakeCallStorage())

    response = client.get("/calls")

    assert response.status_code == 200
    body = response.json()
    assert [call["filename"] for call in body["calls"]] == ["second.wav", "first.mp3"]
    assert body["calls"][0]["status"] == "queued"
    assert repository.list_limits == [50]


def test_list_calls_honors_limit_query_param() -> None:
    records = [_record(original_filename=f"call-{index}.mp3") for index in range(3)]
    repository = FakeCallRepository(records=records)
    client = _client(repository=repository, storage=FakeCallStorage())

    response = client.get("/calls?limit=2")

    assert response.status_code == 200
    assert repository.list_limits == [2]


def test_get_call_returns_call_detail() -> None:
    call = _record(original_filename="sales.mp3")
    repository = FakeCallRepository(records=[call])
    client = _client(repository=repository, storage=FakeCallStorage())

    response = client.get(f"/calls/{call.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["call_id"] == str(call.id)
    assert body["filename"] == "sales.mp3"
    assert body["storage_bucket"] == "call-audio"
    assert body["storage_path"] == call.storage_path
    assert body["created_at"] is not None
    assert body["updated_at"] is not None


def test_get_call_returns_404_when_missing() -> None:
    client = _client(repository=FakeCallRepository(), storage=FakeCallStorage())

    response = client.get(f"/calls/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Call not found"


class FakeCallRepository:
    def __init__(
        self,
        *,
        records: list[CallRecord] | None = None,
        fail_create: bool = False,
    ) -> None:
        self.records = {record.id: record for record in records or []}
        self.created_calls: list[CallCreate] = []
        self.created_jobs: list[UUID] = []
        self.list_limits: list[int] = []
        self.fail_create = fail_create

    def create_call_with_queued_job(self, call: CallCreate) -> CallRecord:
        self.created_calls.append(call)
        if self.fail_create:
            raise CallRepositoryError("fake create failure")
        self.created_jobs.append(call.id)
        record = _record(
            id=call.id,
            original_filename=call.original_filename,
            content_type=call.content_type,
            file_size_bytes=call.file_size_bytes,
            storage_bucket=call.storage_bucket,
            storage_path=call.storage_path,
            storage_etag=call.storage_etag,
            storage_version=call.storage_version,
            status=call.status,
        )
        self.records[record.id] = record
        return record

    def list_calls(self, *, limit: int = 50) -> list[CallRecord]:
        self.list_limits.append(limit)
        return list(self.records.values())[:limit]

    def get_call(self, call_id: UUID) -> CallRecord | None:
        return self.records.get(call_id)


class FakeCallStorage:
    def __init__(self, *, fail_upload: bool = False, fail_delete: bool = False) -> None:
        self.fail_upload = fail_upload
        self.fail_delete = fail_delete
        self.uploads: list[dict[str, object]] = []
        self.deletes: list[dict[str, str]] = []
        self.delete_attempts = 0

    def upload_audio(
        self,
        *,
        path: str,
        content: bytes,
        content_type: str,
        bucket: str,
    ) -> StoredObject:
        if self.fail_upload:
            raise CallStorageError("fake upload failure")
        self.uploads.append(
            {
                "path": path,
                "content": content,
                "content_type": content_type,
                "bucket": bucket,
            }
        )
        return StoredObject(bucket=bucket, path=path, etag="fake-etag", version="fake-version")

    def delete_audio(self, *, path: str, bucket: str) -> None:
        self.delete_attempts += 1
        if self.fail_delete:
            raise CallStorageError("fake delete failure")
        self.deletes.append({"path": path, "bucket": bucket})


def _client(*, repository: FakeCallRepository, storage: FakeCallStorage) -> TestClient:
    app = create_app(
        Settings(app_env="test"),
        call_repository=repository,
        call_storage=storage,
    )
    return TestClient(app)


def _record(
    *,
    id: UUID | None = None,
    original_filename: str = "sales-call.mp3",
    content_type: str = "audio/mpeg",
    file_size_bytes: int = 11,
    storage_bucket: str = "call-audio",
    storage_path: str | None = None,
    storage_etag: str | None = None,
    storage_version: str | None = None,
    status: str = "queued",
    uploaded_at: datetime | None = None,
) -> CallRecord:
    call_id = id or uuid4()
    now = uploaded_at or _dt("2026-07-08T12:00:00+00:00")
    return CallRecord(
        id=call_id,
        original_filename=original_filename,
        content_type=content_type,
        file_size_bytes=file_size_bytes,
        storage_bucket=storage_bucket,
        storage_path=storage_path or f"calls/{call_id}/sales-call-token.mp3",
        storage_etag=storage_etag,
        storage_version=storage_version,
        status=status,
        uploaded_at=now,
        created_at=now,
        updated_at=now,
    )


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)
