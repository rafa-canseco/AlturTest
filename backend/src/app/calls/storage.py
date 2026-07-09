from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

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


class SupabaseStorage:
    def __init__(self, supabase_url: str, service_role_key: str) -> None:
        self._supabase_url = supabase_url.rstrip("/")
        self._service_role_key = service_role_key

    def upload_audio(
        self,
        *,
        path: str,
        content: bytes,
        content_type: str,
        bucket: str,
    ) -> StoredObject:
        object_path = quote(path, safe="/")
        request = Request(
            f"{self._supabase_url}/storage/v1/object/{bucket}/{object_path}",
            data=content,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._service_role_key}",
                "apikey": self._service_role_key,
                "Content-Type": content_type,
                "x-upsert": "false",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                etag = response.headers.get("etag")
                version = response.headers.get("x-version-id")
                return StoredObject(bucket=bucket, path=path, etag=etag, version=version)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise CallStorageError("Failed to upload call audio") from exc

    def delete_audio(self, *, path: str, bucket: str) -> None:
        payload = json.dumps({"prefixes": [path]}).encode("utf-8")
        request = Request(
            f"{self._supabase_url}/storage/v1/object/{bucket}",
            data=payload,
            method="DELETE",
            headers={
                "Authorization": f"Bearer {self._service_role_key}",
                "apikey": self._service_role_key,
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=30):
                return
        except (HTTPError, URLError, TimeoutError) as exc:
            raise CallStorageError("Failed to delete call audio") from exc

    def download_audio(self, *, path: str, bucket: str) -> bytes:
        object_path = quote(path, safe="/")
        request = Request(
            f"{self._supabase_url}/storage/v1/object/{bucket}/{object_path}",
            method="GET",
            headers={
                "Authorization": f"Bearer {self._service_role_key}",
                "apikey": self._service_role_key,
            },
        )
        try:
            with urlopen(request, timeout=60) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            raise CallStorageError("Failed to download call audio") from exc


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
