from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.calls.models import StoredObject


class CallStorageError(Exception):
    pass


class CallStorage(Protocol):
    def upload_audio(
        self,
        *,
        path: str,
        content: bytes,
        content_type: str,
        bucket: str,
    ) -> StoredObject:
        pass

    def delete_audio(self, *, path: str, bucket: str) -> None:
        pass

    def download_audio(self, *, path: str, bucket: str) -> bytes:
        pass


class LocalCallStorage:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def upload_audio(
        self,
        *,
        path: str,
        content: bytes,
        content_type: str,
        bucket: str,
    ) -> StoredObject:
        del content_type
        destination = self._resolve(bucket=bucket, path=path)
        if destination.exists():
            raise CallStorageError("Local call audio already exists")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        except OSError as exc:
            raise CallStorageError("Failed to upload local call audio") from exc
        return StoredObject(
            bucket=bucket,
            path=path,
            etag=hashlib.sha256(content).hexdigest(),
            version=None,
        )

    def delete_audio(self, *, path: str, bucket: str) -> None:
        destination = self._resolve(bucket=bucket, path=path)
        try:
            destination.unlink(missing_ok=True)
            _remove_empty_parents(destination.parent, stop_at=self._root.resolve())
        except OSError as exc:
            raise CallStorageError("Failed to delete local call audio") from exc

    def download_audio(self, *, path: str, bucket: str) -> bytes:
        source = self._resolve(bucket=bucket, path=path)
        try:
            return source.read_bytes()
        except OSError as exc:
            raise CallStorageError("Failed to download local call audio") from exc

    def _resolve(self, *, bucket: str, path: str) -> Path:
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise CallStorageError("Invalid local call audio path")
        root = self._root.resolve()
        destination = (root / bucket / path).resolve()
        if not destination.is_relative_to(root):
            raise CallStorageError("Invalid local call audio path")
        return destination


def _remove_empty_parents(path: Path, *, stop_at: Path) -> None:
    while path != stop_at and path.is_relative_to(stop_at):
        try:
            path.rmdir()
        except OSError:
            return
        path = path.parent


class S3CallStorage:
    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        region: str = "auto",
        url_style: str = "path",
    ) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            config=Config(s3={"addressing_style": url_style}),
        )

    def upload_audio(
        self,
        *,
        path: str,
        content: bytes,
        content_type: str,
        bucket: str,
    ) -> StoredObject:
        try:
            response = self._client.put_object(
                Bucket=bucket,
                Key=path,
                Body=content,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as exc:
            raise CallStorageError("Failed to upload call audio") from exc
        return StoredObject(
            bucket=bucket,
            path=path,
            etag=_strip_etag(response.get("ETag")),
            version=response.get("VersionId"),
        )

    def delete_audio(self, *, path: str, bucket: str) -> None:
        try:
            self._client.delete_object(Bucket=bucket, Key=path)
        except (BotoCoreError, ClientError) as exc:
            raise CallStorageError("Failed to delete call audio") from exc

    def download_audio(self, *, path: str, bucket: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=bucket, Key=path)
            body = response["Body"]
            return body.read()
        except (BotoCoreError, ClientError, KeyError, OSError) as exc:
            raise CallStorageError("Failed to download call audio") from exc


def _strip_etag(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip('"')
