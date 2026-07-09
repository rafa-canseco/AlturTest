from __future__ import annotations

import logging

from app.worker.processor import CallProcessor, CallProcessorError
from app.worker.repository import WorkerRepository, WorkerRepositoryError


logger = logging.getLogger(__name__)


class WorkerService:
    def __init__(self, *, repository: WorkerRepository, processor: CallProcessor) -> None:
        self._repository = repository
        self._processor = processor

    def run_once(self, *, worker_id: str) -> bool:
        claimed_job = self._repository.claim_next_job(worker_id=worker_id)
        if claimed_job is None:
            return False

        try:
            result = self._processor.process(claimed_job)
        except CallProcessorError as exc:
            logger.exception(
                "Call processor failed",
                extra={"job_id": str(claimed_job.job.id), "call_id": str(claimed_job.call.id)},
            )
            self._repository.fail_job(
                job_id=claimed_job.job.id,
                call_id=claimed_job.call.id,
                error_code=exc.code,
                error_message=str(exc),
            )
            return True
        except Exception as exc:
            logger.exception(
                "Unexpected call processor failure",
                extra={"job_id": str(claimed_job.job.id), "call_id": str(claimed_job.call.id)},
            )
            self._repository.fail_job(
                job_id=claimed_job.job.id,
                call_id=claimed_job.call.id,
                error_code="processor_unhandled_error",
                error_message="Unhandled processor error",
            )
            return True

        try:
            if result.call_completed:
                self._repository.complete_job(job_id=claimed_job.job.id, call_id=claimed_job.call.id)
            else:
                self._repository.mark_job_ready_for_analysis(
                    job_id=claimed_job.job.id,
                    call_id=claimed_job.call.id,
                )
        except WorkerRepositoryError:
            logger.exception(
                "Could not persist call processing job result",
                extra={"job_id": str(claimed_job.job.id), "call_id": str(claimed_job.call.id)},
            )
            raise
        return True
