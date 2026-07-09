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
)
from app.worker.repository import PostgresWorkerRepository
from app.worker.service import WorkerService


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
    assert repository.failed_jobs == []


def test_worker_returns_false_when_no_job_is_available() -> None:
    repository = FakeWorkerRepository(claimed_job=None)
    processor = FakeProcessor()
    service = WorkerService(repository=repository, processor=processor)

    did_work = service.run_once(worker_id="worker-a")

    assert did_work is False
    assert processor.processed_jobs == []
    assert repository.completed_jobs == []
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


def test_postgres_worker_repository_uses_skip_locked_claim_and_clears_retry_fields() -> None:
    names = PostgresWorkerRepository.claim_next_job.__code__.co_names
    constants = "\n".join(
        str(constant).lower()
        for constant in PostgresWorkerRepository.claim_next_job.__code__.co_consts
    )

    assert "connect" in names
    assert "for update of j skip locked" in constants
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


class FakeWorkerRepository:
    def __init__(self, *, claimed_job: ClaimedCallProcessingJob | None) -> None:
        self.claimed_job = claimed_job
        self.claim_worker_ids: list[str] = []
        self.completed_jobs: list[tuple[UUID, UUID]] = []
        self.failed_jobs: list[tuple[UUID, UUID, str, str]] = []

    def claim_next_job(self, *, worker_id: str) -> ClaimedCallProcessingJob | None:
        self.claim_worker_ids.append(worker_id)
        return self.claimed_job

    def complete_job(self, *, job_id: UUID, call_id: UUID) -> None:
        self.completed_jobs.append((job_id, call_id))

    def fail_job(self, *, job_id: UUID, call_id: UUID, error_code: str, error_message: str) -> None:
        self.failed_jobs.append((job_id, call_id, error_code, error_message))

    def requeue_failed_job(self, *, call_id: UUID) -> bool:
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


def _claimed_job() -> ClaimedCallProcessingJob:
    call = _call_record()
    job = _job_record(call_id=call.id)
    return ClaimedCallProcessingJob(job=job, call=call)


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
