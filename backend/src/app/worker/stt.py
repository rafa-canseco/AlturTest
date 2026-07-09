from __future__ import annotations

import json
import mimetypes
import uuid
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Transcription:
    text: str
    provider: str
    model: str
    metadata: dict[str, Any]
    raw_provider_response: dict[str, Any] | None = None
    raw_content: str | None = None


class STTClientError(Exception):
    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        status: str = "failed",
        raw_provider_response: dict[str, Any] | None = None,
        raw_content: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.status = status
        self.raw_provider_response = raw_provider_response
        self.raw_content = raw_content


class STTClient(Protocol):
    def transcribe(
        self,
        *,
        audio: bytes,
        filename: str,
        content_type: str,
    ) -> Transcription:
        pass


class ElevenLabsSTTClient:
    def __init__(
        self,
        *,
        api_key: str,
        model_id: str,
        base_url: str = "https://api.elevenlabs.io/v1",
        timeout_seconds: float = 120.0,
    ) -> None:
        self._api_key = api_key
        self._model_id = model_id
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def transcribe(
        self,
        *,
        audio: bytes,
        filename: str,
        content_type: str,
    ) -> Transcription:
        boundary = f"altur-{uuid.uuid4().hex}"
        body = _multipart_body(
            boundary=boundary,
            fields={"model_id": self._model_id},
            files={
                "file": {
                    "filename": filename,
                    "content": audio,
                    "content_type": content_type,
                },
            },
        )
        request = Request(
            f"{self._base_url}/speech-to-text",
            data=body,
            method="POST",
            headers={
                "xi-api-key": self._api_key,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
            },
        )

        raw_content: str | None = None
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw_content = response.read().decode("utf-8")
                payload = json.loads(raw_content)
        except HTTPError as exc:
            raw_content = _read_error_body(exc)
            raise STTClientError(
                "Speech transcription failed",
                provider="elevenlabs",
                model=self._model_id,
                raw_provider_response=_json_object_or_none(raw_content),
                raw_content=raw_content,
            ) from exc
        except json.JSONDecodeError as exc:
            raise STTClientError(
                "Speech transcription failed",
                provider="elevenlabs",
                model=self._model_id,
                raw_content=raw_content,
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise STTClientError("Speech transcription failed") from exc

        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise STTClientError(
                "Speech transcription returned no transcript",
                provider="elevenlabs",
                model=self._model_id,
                status="invalid",
                raw_provider_response=payload,
                raw_content=raw_content,
            )

        return Transcription(
            text=text,
            provider="elevenlabs",
            model=self._model_id,
            metadata=_transcript_metadata(payload),
            raw_provider_response=payload,
            raw_content=raw_content,
        )


def _transcript_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("language_code", "language_probability", "words"):
        if key in payload:
            metadata[key] = payload[key]
    return metadata


def _read_error_body(error: HTTPError) -> str | None:
    try:
        return error.read().decode("utf-8")
    except Exception:
        return None


def _json_object_or_none(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _multipart_body(
    *,
    boundary: str,
    fields: dict[str, str],
    files: dict[str, dict[str, object]],
) -> bytes:
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    for name, file_data in files.items():
        filename = str(file_data["filename"])
        content_type = str(
            file_data.get("content_type")
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )
        content = file_data["content"]
        if not isinstance(content, bytes):
            raise TypeError("multipart file content must be bytes")
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{filename}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
                content,
                b"\r\n",
            ]
        )

    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks)
