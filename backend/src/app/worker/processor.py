from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.calls.models import CallAnalysisCreate, ClaimedCallProcessingJob
from app.calls.storage import CallStorage, CallStorageError
from app.worker.llm import LLMClient, LLMClientError
from app.worker.repository import WorkerRepository, WorkerRepositoryError
from app.worker.stt import STTClient, STTClientError


@dataclass(frozen=True)
class ProcessingResult:
    message: str = "Call processing completed"
    call_completed: bool = True


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


class TranscriptionProcessor:
    def __init__(
        self,
        *,
        repository: WorkerRepository,
        storage: CallStorage,
        stt_client: STTClient,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._stt_client = stt_client

    def process(self, claimed_job: ClaimedCallProcessingJob) -> ProcessingResult:
        call = claimed_job.call
        if claimed_job.transcript_exists or self._repository.has_transcript(call_id=call.id):
            return ProcessingResult(
                message="Transcript already exists; pending analysis",
                call_completed=False,
            )

        try:
            audio = self._storage.download_audio(
                path=call.storage_path,
                bucket=call.storage_bucket,
            )
            transcription = self._stt_client.transcribe(
                audio=audio,
                filename=call.original_filename,
                content_type=call.content_type,
            )
            self._repository.create_transcript(
                call_id=call.id,
                transcript=transcription.text,
                stt_provider=transcription.provider,
                stt_model=transcription.model,
                transcript_metadata=transcription.metadata,
            )
        except CallStorageError as exc:
            raise CallProcessorError(
                "Could not load call audio",
                code="audio_download_failed",
            ) from exc
        except STTClientError as exc:
            raise CallProcessorError(
                "Speech transcription failed",
                code="stt_failed",
            ) from exc
        except WorkerRepositoryError:
            raise

        return ProcessingResult(message="Transcript created; pending analysis", call_completed=False)


class AnalysisProcessor:
    def __init__(
        self,
        *,
        repository: WorkerRepository,
        llm_client: LLMClient,
    ) -> None:
        self._repository = repository
        self._llm_client = llm_client

    def process(self, claimed_job: ClaimedCallProcessingJob) -> ProcessingResult:
        call_id = claimed_job.call.id
        if self._repository.has_analysis(call_id=call_id):
            return ProcessingResult(message="Analysis already exists")

        transcript = self._repository.get_transcript(call_id=call_id)
        if transcript is None:
            return ProcessingResult(
                message="Transcript not ready for analysis",
                call_completed=False,
            )

        try:
            analysis = self._llm_client.analyze_transcript(transcript=transcript.transcript)
            self._repository.create_analysis(
                analysis=CallAnalysisCreate(
                    call_id=call_id,
                    summary=analysis.summary,
                    tags=analysis.tags,
                    intent=analysis.intent,
                    sentiment=analysis.sentiment,
                    next_action=analysis.next_action,
                    risk_flags=analysis.risk_flags,
                    llm_provider=analysis.provider,
                    llm_model=analysis.model,
                    prompt_version=analysis.prompt_version,
                    raw_llm_output=analysis.raw_output,
                )
            )
        except LLMClientError as exc:
            raise CallProcessorError("Transcript analysis failed", code="analysis_failed") from exc
        except WorkerRepositoryError:
            raise

        return ProcessingResult(message="Analysis created")
