from __future__ import annotations

import argparse
import logging
import socket
import time

from app.config import get_settings
from app.calls.storage import SupabaseStorage
from app.worker.processor import CallProcessor, FakeCallProcessor, NotConfiguredCallProcessor
from app.worker.processor import TranscriptionProcessor
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
        repository=repository,
        supabase_url=settings.supabase_url,
        supabase_service_role_key=settings.supabase_service_role_key,
        elevenlabs_api_key=settings.elevenlabs_api_key,
        elevenlabs_stt_model_id=settings.elevenlabs_stt_model_id,
    )
    service = WorkerService(
        repository=repository,
        processor=processor,
        claim_transcript_exists=_claim_transcript_exists(
            use_dev_fake=args.dev_fake_processor,
            processor=processor,
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
    repository: WorkerRepository | None = None,
    supabase_url: str | None = None,
    supabase_service_role_key: str | None = None,
    elevenlabs_api_key: str | None = None,
    elevenlabs_stt_model_id: str = "scribe_v1",
) -> CallProcessor:
    if use_dev_fake:
        return FakeCallProcessor()
    if repository and supabase_url and supabase_service_role_key and elevenlabs_api_key:
        return TranscriptionProcessor(
            repository=repository,
            storage=SupabaseStorage(
                supabase_url=supabase_url,
                service_role_key=supabase_service_role_key,
            ),
            stt_client=ElevenLabsSTTClient(
                api_key=elevenlabs_api_key,
                model_id=elevenlabs_stt_model_id,
            ),
        )
    return NotConfiguredCallProcessor()


def _claim_transcript_exists(*, use_dev_fake: bool, processor: CallProcessor) -> bool | None:
    if use_dev_fake:
        return None
    if isinstance(processor, TranscriptionProcessor):
        return False
    return None


if __name__ == "__main__":
    main()
