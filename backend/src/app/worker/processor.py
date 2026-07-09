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
    """Placeholder processor until STT and LLM integrations are added."""

    def process(self, claimed_job: ClaimedCallProcessingJob) -> ProcessingResult:
        return ProcessingResult(message="Fake processor completed")
