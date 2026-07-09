from __future__ import annotations

import argparse
import logging
import socket
import time

from app.config import get_settings
from app.worker.processor import CallProcessor, FakeCallProcessor, NotConfiguredCallProcessor
from app.worker.repository import PostgresWorkerRepository
from app.worker.service import WorkerService


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

    service = WorkerService(
        repository=PostgresWorkerRepository(settings.database_url),
        processor=_build_processor(use_dev_fake=args.dev_fake_processor),
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


def _build_processor(*, use_dev_fake: bool) -> CallProcessor:
    if use_dev_fake:
        return FakeCallProcessor()
    return NotConfiguredCallProcessor()


if __name__ == "__main__":
    main()
