from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.calls.repository import CallRepository, CallRepositoryError, PostgresCallRepository
from app.calls.routes import router as calls_router
from app.calls.service import CallService
from app.calls.storage import CallStorage, CallStorageError, LocalCallStorage, S3CallStorage
from app.config import Settings, get_settings


def create_app(
    settings: Settings | None = None,
    *,
    call_repository: CallRepository | None = None,
    call_storage: CallStorage | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    app = FastAPI(title=resolved_settings.app_name, debug=resolved_settings.debug)
    cors_origins = _parse_csv(resolved_settings.cors_allow_origins)
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )
    app.state.call_service = CallService(
        repository=call_repository or _build_call_repository(resolved_settings),
        storage=call_storage or _build_call_storage(resolved_settings),
        storage_bucket=resolved_settings.call_storage_bucket,
        max_upload_bytes=resolved_settings.max_call_upload_bytes,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": resolved_settings.app_env}

    app.include_router(calls_router)

    return app


def _build_call_repository(settings: Settings) -> CallRepository:
    if settings.database_url:
        return PostgresCallRepository(settings.database_url)
    return _UnconfiguredCallRepository("DATABASE_URL is not configured")


def _build_call_storage(settings: Settings) -> CallStorage:
    if (
        settings.s3_endpoint_url
        and settings.s3_access_key_id
        and settings.s3_secret_access_key
    ):
        return S3CallStorage(
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            region=settings.s3_region,
            url_style=settings.s3_url_style,
        )
    return LocalCallStorage(settings.local_storage_root)


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class _UnconfiguredCallRepository:
    def __init__(self, message: str) -> None:
        self._message = message

    def create_call_with_queued_job(self, call: object, **kwargs: object) -> object:
        raise CallRepositoryError(self._message)

    def get_call_by_idempotency_key(self, idempotency_key_hash: str) -> None:
        raise CallRepositoryError(self._message)

    def list_calls(self, *, limit: int = 50) -> list[object]:
        raise CallRepositoryError(self._message)

    def get_call(self, call_id: object) -> None:
        raise CallRepositoryError(self._message)

    def get_call_detail(self, call_id: object) -> None:
        raise CallRepositoryError(self._message)

    def list_tag_overrides(self, call_id: object) -> None:
        raise CallRepositoryError(self._message)

    def create_tag_override(self, override: object) -> None:
        raise CallRepositoryError(self._message)

    def delete_tag_override(self, **kwargs: object) -> None:
        raise CallRepositoryError(self._message)


class _UnconfiguredCallStorage:
    def __init__(self, message: str) -> None:
        self._message = message

    def upload_audio(self, **kwargs: object) -> object:
        raise CallStorageError(self._message)

    def delete_audio(self, **kwargs: object) -> None:
        raise CallStorageError(self._message)

    def download_audio(self, **kwargs: object) -> bytes:
        raise CallStorageError(self._message)


app = create_app()
