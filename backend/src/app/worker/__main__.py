from __future__ import annotations

import argparse
import logging
import socket
import time

from app.config import get_settings
from app.calls.storage import LocalCallStorage
from app.worker.llm import OpenAIAnalysisClient
from app.worker.processor import (
    AnalysisProcessor,
    CallProcessor,
    FakeCallProcessor,
    NotConfiguredCallProcessor,
    TranscriptionProcessor,
)
from app.worker.repository import PostgresWorkerRepository, WorkerRepository
from app.worker.service import WorkerService
from app.worker.stt import ElevenLabsSTTClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Altur call processing worker.")
    parser.add_argument("--worker-id", default=socket.gethostname())
    parser.add_argument("--once", action="store_true", help="Process at most one available job.")
    parser.add_argument("--limit", type=int, default=None, help="Stop after this many claimed jobs.")
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    parser.add_argument(
        "--stage",
        choices=("stt", "analysis"),
        default="stt",
        help="Worker stage to run. STT claims jobs without transcripts; analysis claims jobs with transcripts.",
    )
    parser.add_argument(
        "--dev-fake-processor",
        action="store_true",
        help="DEV ONLY: mark claimed jobs completed without STT/LLM output.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is required to run the worker")

    repository = PostgresWorkerRepository(settings.database_url)
    processor = _build_processor(
        use_dev_fake=args.dev_fake_processor,
        stage=args.stage,
        repository=repository,
        local_storage_root=settings.local_storage_root,
        elevenlabs_api_key=settings.elevenlabs_api_key,
        elevenlabs_stt_model_id=settings.elevenlabs_stt_model_id,
        openai_api_key=settings.openai_api_key,
        openai_analysis_model=settings.openai_analysis_model,
        analysis_prompt_version=settings.analysis_prompt_version,
    )
    service = WorkerService(
        repository=repository,
        processor=processor,
        claim_transcript_exists=_claim_transcript_exists(
            use_dev_fake=args.dev_fake_processor,
            processor=processor,
            stage=args.stage,
        ),
    )
    processed = 0
    while True:
        did_work = service.run_once(worker_id=args.worker_id)
        if did_work:
            processed += 1
        if args.once or (args.limit is not None and processed >= args.limit):
            return
        if not did_work:
            time.sleep(args.poll_interval_seconds)


def _build_processor(
    *,
    use_dev_fake: bool,
    stage: str = "stt",
    repository: WorkerRepository | None = None,
    local_storage_root: str = ".data/storage",
    elevenlabs_api_key: str | None = None,
    elevenlabs_stt_model_id: str = "scribe_v1",
    openai_api_key: str | None = None,
    openai_analysis_model: str = "gpt-4.1-mini",
    analysis_prompt_version: str = "altur-analysis-v1",
) -> CallProcessor:
    if use_dev_fake:
        return FakeCallProcessor()
    if stage == "stt" and repository and elevenlabs_api_key:
        return TranscriptionProcessor(
            repository=repository,
            storage=LocalCallStorage(local_storage_root),
            stt_client=ElevenLabsSTTClient(
                api_key=elevenlabs_api_key,
                model_id=elevenlabs_stt_model_id,
            ),
        )
    if stage == "analysis" and repository and openai_api_key:
        return AnalysisProcessor(
            repository=repository,
            llm_client=OpenAIAnalysisClient(
                api_key=openai_api_key,
                model=openai_analysis_model,
                prompt_version=analysis_prompt_version,
            ),
        )
    return NotConfiguredCallProcessor()


def _claim_transcript_exists(
    *,
    use_dev_fake: bool,
    processor: CallProcessor,
    stage: str = "stt",
) -> bool | None:
    if use_dev_fake:
        return None
    if isinstance(processor, TranscriptionProcessor):
        return False
    if isinstance(processor, AnalysisProcessor):
        return True
    if stage == "stt":
        return False
    if stage == "analysis":
        return True
    return None


if __name__ == "__main__":
    main()
