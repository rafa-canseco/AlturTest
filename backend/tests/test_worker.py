from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.calls.models import CallProcessingJobRecord, CallRecord, ClaimedCallProcessingJob
from app.worker.__main__ import _build_processor
from app.worker.processor import (
    CallProcessorError,
    FakeCallProcessor,
    NotConfiguredCallProcessor,
    ProcessingResult,
    TranscriptionProcessor,
)
from app.worker.repository import PostgresWorkerRepository
from app.worker.service import WorkerService
from app.worker.stt import STTClientError, Transcription


def test_worker_claims_processes_and_completes_job() -> None:
    claimed_job = _claimed_job()
    repository = FakeWorkerRepository(claimed_job=claimed_job)
    processor = FakeProcessor()
    service = WorkerService(repository=repository, processor=processor)

    did_work = service.run_once(worker_id="worker-a")

    assert did_work is True
    assert repository.claim_worker_ids == ["worker-a"]
    assert processor.processed_jobs == [claimed_job]
    assert repository.completed_jobs == [(claimed_job.job.id, claimed_job.call.id)]
    assert repository.analysis_ready_jobs == []
    assert repository.failed_jobs == []


def test_worker_returns_false_when_no_job_is_available() -> None:
    repository = FakeWorkerRepository(claimed_job=None)
    processor = FakeProcessor()
    service = WorkerService(repository=repository, processor=processor)

    did_work = service.run_once(worker_id="worker-a")

    assert did_work is False
    assert processor.processed_jobs == []
    assert repository.completed_jobs == []
    assert repository.analysis_ready_jobs == []
    assert repository.failed_jobs == []


def test_worker_marks_job_failed_when_processor_reports_expected_failure() -> None:
    claimed_job = _claimed_job()
    repository = FakeWorkerRepository(claimed_job=claimed_job)
    processor = FakeProcessor(error=CallProcessorError("fake failed", code="fake_error"))
    service = WorkerService(repository=repository, processor=processor)

    did_work = service.run_once(worker_id="worker-a")

    assert did_work is True
    assert repository.completed_jobs == []
    assert repository.failed_jobs == [
        (claimed_job.job.id, claimed_job.call.id, "fake_error", "fake failed"),
    ]


def test_worker_marks_job_failed_safely_when_processor_raises_unhandled_error() -> None:
    claimed_job = _claimed_job()
    repository = FakeWorkerRepository(claimed_job=claimed_job)
    processor = FakeProcessor(error=RuntimeError("sensitive provider detail"))
    service = WorkerService(repository=repository, processor=processor)

    did_work = service.run_once(worker_id="worker-a")

    assert did_work is True
    assert repository.failed_jobs == [
        (
            claimed_job.job.id,
            claimed_job.call.id,
            "processor_unhandled_error",
            "Unhandled processor error",
        ),
    ]


def test_transcription_processor_success_persists_transcript_and_keeps_call_processing() -> None:
    claimed_job = _claimed_job()
    repository = FakeWorkerRepository(claimed_job=claimed_job)
    storage = FakeCallStorage(audio=b"fake-audio")
    stt_client = FakeSTTClient(
        transcription=Transcription(
            text="Customer wants a demo.",
            provider="elevenlabs",
            model="scribe_v1",
            metadata={"language_code": "en"},
        )
    )
    service = WorkerService(
        repository=repository,
        processor=TranscriptionProcessor(
            repository=repository,
            storage=storage,
            stt_client=stt_client,
        ),
    )

    did_work = service.run_once(worker_id="worker-a")

    assert did_work is True
    assert storage.downloads == [
        {
            "bucket": claimed_job.call.storage_bucket,
            "path": claimed_job.call.storage_path,
        }
    ]
    assert stt_client.requests == [
        {
            "audio": b"fake-audio",
            "filename": claimed_job.call.original_filename,
            "content_type": claimed_job.call.content_type,
        }
    ]
    assert repository.created_transcripts == [
        {
            "call_id": claimed_job.call.id,
            "transcript": "Customer wants a demo.",
            "stt_provider": "elevenlabs",
            "stt_model": "scribe_v1",
            "transcript_metadata": {"language_code": "en"},
        }
    ]
    assert repository.completed_jobs == []
    assert repository.analysis_ready_jobs == [(claimed_job.job.id, claimed_job.call.id)]
    assert repository.failed_jobs == []


def test_transcription_processor_failure_marks_job_failed_safely() -> None:
    claimed_job = _claimed_job()
    repository = FakeWorkerRepository(claimed_job=claimed_job)
    storage = FakeCallStorage(audio=b"fake-audio")
    stt_client = FakeSTTClient(error=STTClientError("provider secret detail"))
    service = WorkerService(
        repository=repository,
        processor=TranscriptionProcessor(
            repository=repository,
            storage=storage,
            stt_client=stt_client,
        ),
    )

    did_work = service.run_once(worker_id="worker-a")

    assert did_work is True
    assert repository.created_transcripts == []
    assert repository.completed_jobs == []
    assert repository.analysis_ready_jobs == []
    assert repository.failed_jobs == [
        (
            claimed_job.job.id,
            claimed_job.call.id,
            "stt_failed",
            "Speech transcription failed",
        ),
    ]


def test_transcription_processor_existing_transcript_does_not_duplicate() -> None:
    claimed_job = _claimed_job(transcript_exists=True)
    repository = FakeWorkerRepository(claimed_job=claimed_job, existing_transcript=True)
    storage = FakeCallStorage(audio=b"fake-audio")
    stt_client = FakeSTTClient(
        transcription=Transcription(
            text="Should not be used.",
            provider="elevenlabs",
            model="scribe_v1",
            metadata={},
        )
    )
    service = WorkerService(
        repository=repository,
        processor=TranscriptionProcessor(
            repository=repository,
            storage=storage,
            stt_client=stt_client,
        ),
    )

    did_work = service.run_once(worker_id="worker-a")

    assert did_work is True
    assert storage.downloads == []
    assert stt_client.requests == []
    assert repository.created_transcripts == []
    assert repository.completed_jobs == []
    assert repository.analysis_ready_jobs == [(claimed_job.job.id, claimed_job.call.id)]
    assert repository.failed_jobs == []


def test_default_cli_processor_fails_jobs_instead_of_completing_without_real_processor() -> None:
    claimed_job = _claimed_job()
    repository = FakeWorkerRepository(claimed_job=claimed_job)
    service = WorkerService(
        repository=repository,
        processor=_build_processor(use_dev_fake=False),
    )

    did_work = service.run_once(worker_id="worker-a")

    assert did_work is True
    assert repository.completed_jobs == []
    assert repository.failed_jobs == [
        (
            claimed_job.job.id,
            claimed_job.call.id,
            "processor_not_configured",
            "Call processor is not configured; STT and LLM processing are not implemented",
        ),
    ]


def test_cli_fake_processor_requires_explicit_dev_flag() -> None:
    assert isinstance(_build_processor(use_dev_fake=False), NotConfiguredCallProcessor)
    assert isinstance(_build_processor(use_dev_fake=True), FakeCallProcessor)


def test_cli_builds_transcription_processor_when_required_env_is_present() -> None:
    processor = _build_processor(
        use_dev_fake=False,
        repository=FakeWorkerRepository(claimed_job=None),
        supabase_url="http://supabase.local",
        supabase_service_role_key="fake-service-role",
        elevenlabs_api_key="fake-elevenlabs-key",
        elevenlabs_stt_model_id="scribe_v1",
    )

    assert isinstance(processor, TranscriptionProcessor)


def test_postgres_worker_repository_uses_skip_locked_claim_and_clears_retry_fields() -> None:
    names = PostgresWorkerRepository.claim_next_job.__code__.co_names
    constants = "\n".join(
        str(constant).lower()
        for constant in PostgresWorkerRepository.claim_next_job.__code__.co_consts
    )

    assert "connect" in names
    assert "for update of j skip locked" in constants
    assert "call_transcripts" in constants
    assert "transcript_exists" in constants
    assert "failed_at = null" in constants
    assert "last_error_code = null" in constants
    assert "last_error_message = null" in constants
    assert "error_code = null" in constants
    assert "error_message = null" in constants
    assert "c.status <> 'completed'" in constants


def test_postgres_worker_repository_requeue_clears_failure_fields() -> None:
    constants = "\n".join(
        str(constant).lower()
        for constant in PostgresWorkerRepository.requeue_failed_job.__code__.co_consts
    )

    assert "status = 'queued'" in constants
    assert "failed_at = null" in constants
    assert "last_error_code = null" in constants
    assert "last_error_message = null" in constants
    assert "error_code = null" in constants
    assert "error_message = null" in constants
    assert "attempt_count < max_attempts" in constants


def test_postgres_worker_repository_requeues_stt_job_for_analysis_without_completing_call() -> None:
    constants = "\n".join(
        str(constant).lower()
        for constant in PostgresWorkerRepository.mark_job_ready_for_analysis.__code__.co_consts
    )

    assert "update calls" in constants
    assert "status = 'processing'" in constants
    assert "update call_processing_jobs" in constants
    assert "status = 'queued'" in constants
    assert "available_at = now()" in constants
    assert "completed_at = null" in constants


class FakeWorkerRepository:
    def __init__(
        self,
        *,
        claimed_job: ClaimedCallProcessingJob | None,
        existing_transcript: bool = False,
    ) -> None:
        self.claimed_job = claimed_job
        self.existing_transcript = existing_transcript
        self.claim_worker_ids: list[str] = []
        self.completed_jobs: list[tuple[UUID, UUID]] = []
        self.analysis_ready_jobs: list[tuple[UUID, UUID]] = []
        self.failed_jobs: list[tuple[UUID, UUID, str, str]] = []
        self.created_transcripts: list[dict[str, object]] = []

    def claim_next_job(self, *, worker_id: str) -> ClaimedCallProcessingJob | None:
        self.claim_worker_ids.append(worker_id)
        return self.claimed_job

    def complete_job(self, *, job_id: UUID, call_id: UUID) -> None:
        self.completed_jobs.append((job_id, call_id))

    def mark_job_ready_for_analysis(self, *, job_id: UUID, call_id: UUID) -> None:
        self.analysis_ready_jobs.append((job_id, call_id))

    def fail_job(self, *, job_id: UUID, call_id: UUID, error_code: str, error_message: str) -> None:
        self.failed_jobs.append((job_id, call_id, error_code, error_message))

    def requeue_failed_job(self, *, call_id: UUID) -> bool:
        return True

    def has_transcript(self, *, call_id: UUID) -> bool:
        return self.existing_transcript

    def create_transcript(
        self,
        *,
        call_id: UUID,
        transcript: str,
        stt_provider: str,
        stt_model: str,
        transcript_metadata: dict[str, object],
    ) -> bool:
        self.created_transcripts.append(
            {
                "call_id": call_id,
                "transcript": transcript,
                "stt_provider": stt_provider,
                "stt_model": stt_model,
                "transcript_metadata": transcript_metadata,
            }
        )
        self.existing_transcript = True
        return True


class FakeProcessor:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.processed_jobs: list[ClaimedCallProcessingJob] = []

    def process(self, claimed_job: ClaimedCallProcessingJob) -> ProcessingResult:
        self.processed_jobs.append(claimed_job)
        if self.error:
            raise self.error
        return ProcessingResult()


class FakeCallStorage:
    def __init__(self, *, audio: bytes) -> None:
        self.audio = audio
        self.downloads: list[dict[str, str]] = []

    def download_audio(self, *, path: str, bucket: str) -> bytes:
        self.downloads.append({"path": path, "bucket": bucket})
        return self.audio


class FakeSTTClient:
    def __init__(
        self,
        *,
        transcription: Transcription | None = None,
        error: Exception | None = None,
    ) -> None:
        self.transcription = transcription
        self.error = error
        self.requests: list[dict[str, object]] = []

    def transcribe(
        self,
        *,
        audio: bytes,
        filename: str,
        content_type: str,
    ) -> Transcription:
        self.requests.append(
            {
                "audio": audio,
                "filename": filename,
                "content_type": content_type,
            }
        )
        if self.error:
            raise self.error
        assert self.transcription is not None
        return self.transcription


def _claimed_job(*, transcript_exists: bool = False) -> ClaimedCallProcessingJob:
    call = _call_record()
    job = _job_record(call_id=call.id)
    return ClaimedCallProcessingJob(job=job, call=call, transcript_exists=transcript_exists)


def _call_record() -> CallRecord:
    now = _dt("2026-07-08T12:00:00+00:00")
    call_id = uuid4()
    return CallRecord(
        id=call_id,
        original_filename="sales-call.mp3",
        content_type="audio/mpeg",
        file_size_bytes=11,
        storage_bucket="call-audio",
        storage_path=f"calls/{call_id}/sales-call-token.mp3",
        status="processing",
        uploaded_at=now,
        created_at=now,
        updated_at=now,
    )


def _job_record(*, call_id: UUID) -> CallProcessingJobRecord:
    now = _dt("2026-07-08T12:00:00+00:00")
    return CallProcessingJobRecord(
        id=uuid4(),
        call_id=call_id,
        status="processing",
        attempt_count=1,
        max_attempts=3,
        available_at=now,
        locked_at=now,
        locked_by="worker-a",
        started_at=now,
        created_at=now,
        updated_at=now,
    )


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)
