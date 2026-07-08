from __future__ import annotations

import json
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
