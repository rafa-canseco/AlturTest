from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.calls.models import ClaimedCallProcessingJob


@dataclass(frozen=True)
class ProcessingResult:
    message: str = "Call processing completed"


class CallProcessorError(Exception):
    def __init__(self, message: str, *, code: str = "processor_error") -> None:
        super().__init__(message)
        self.code = code


class CallProcessor(Protocol):
    def process(self, claimed_job: ClaimedCallProcessingJob) -> ProcessingResult:
        pass


class FakeCallProcessor:
    """Dev-only processor for local queue plumbing checks."""

    def process(self, claimed_job: ClaimedCallProcessingJob) -> ProcessingResult:
        return ProcessingResult(message="Fake processor completed")


class NotConfiguredCallProcessor:
    def process(self, claimed_job: ClaimedCallProcessingJob) -> ProcessingResult:
        raise CallProcessorError(
            "Call processor is not configured; STT and LLM processing are not implemented",
            code="processor_not_configured",
        )
