from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ALLOWED_SENTIMENTS = {"positive", "neutral", "negative", "mixed"}
ALLOWED_NEXT_ACTIONS = {
    "send_info",
    "schedule_demo",
    "follow_up",
    "escalate",
    "close_lost",
    "none",
}
DEFAULT_ANALYSIS_PROMPT_VERSION = "altur-analysis-v1"
ANALYSIS_RESPONSE_SCHEMA: dict[str, Any] = {
    "name": "call_analysis",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {
                "type": "string",
                "description": "Concise aggregate summary of the full transcript.",
            },
            "tags": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "topics": {"type": "array", "items": {"type": "string"}},
                    "customer_intents": {"type": "array", "items": {"type": "string"}},
                    "products": {"type": "array", "items": {"type": "string"}},
                    "risks": {"type": "array", "items": {"type": "string"}},
                    "outcomes": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "topics",
                    "customer_intents",
                    "products",
                    "risks",
                    "outcomes",
                ],
                "description": "Operational tags grouped into fixed categories.",
            },
            "intent": {
                "type": ["string", "null"],
                "description": "Single dominant customer intent for the full transcript.",
            },
            "sentiment": {
                "type": ["string", "null"],
                "enum": ["positive", "neutral", "negative", "mixed", None],
            },
            "next_action": {
                "type": ["string", "null"],
                "enum": [
                    "send_info",
                    "schedule_demo",
                    "follow_up",
                    "escalate",
                    "close_lost",
                    "none",
                    None,
                ],
            },
            "risk_flags": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "summary",
            "tags",
            "intent",
            "sentiment",
            "next_action",
            "risk_flags",
        ],
    },
}


@dataclass(frozen=True)
class TranscriptAnalysis:
    summary: str
    tags: dict[str, Any]
    intent: str | None
    sentiment: str | None
    next_action: str | None
    risk_flags: list[str]
    raw_output: dict[str, Any]
    provider: str
    model: str
    prompt_version: str
    raw_provider_response: dict[str, Any] | None = None
    raw_content: str | None = None


class LLMClientError(Exception):
    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
        status: str = "failed",
        raw_provider_response: dict[str, Any] | None = None,
        raw_content: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.prompt_version = prompt_version
        self.status = status
        self.raw_provider_response = raw_provider_response
        self.raw_content = raw_content


class InvalidLLMOutputError(LLMClientError):
    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
        raw_provider_response: dict[str, Any] | None = None,
        raw_content: str | None = None,
        parsed_output: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            status="invalid",
            raw_provider_response=raw_provider_response,
            raw_content=raw_content,
        )
        self.parsed_output = parsed_output


class LLMClient(Protocol):
    def analyze_transcript(self, *, transcript: str) -> TranscriptAnalysis:
        pass


class OpenAIAnalysisClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        prompt_version: str = DEFAULT_ANALYSIS_PROMPT_VERSION,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 120.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._prompt_version = prompt_version
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def analyze_transcript(self, *, transcript: str) -> TranscriptAnalysis:
        request = Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(self._request_payload(transcript)).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        raw_response_body: str | None = None
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw_response_body = response.read().decode("utf-8")
                payload = json.loads(raw_response_body)
        except HTTPError as exc:
            raw_response_body = _read_error_body(exc)
            raise LLMClientError(
                "Transcript analysis failed",
                provider="openai",
                model=self._model,
                prompt_version=self._prompt_version,
                status="failed",
                raw_provider_response=_json_object_or_none(raw_response_body),
                raw_content=raw_response_body,
            ) from exc
        except json.JSONDecodeError as exc:
            raise self._invalid_output_error(
                "Transcript analysis returned invalid provider JSON",
                raw_content=raw_response_body,
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise LLMClientError("Transcript analysis failed") from exc

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise self._invalid_output_error(
                "Transcript analysis returned malformed output",
                raw_provider_response=payload,
            ) from exc
        if not isinstance(content, str):
            raise self._invalid_output_error(
                "Transcript analysis returned malformed output",
                raw_provider_response=payload,
            )

        try:
            raw_output = json.loads(content)
        except json.JSONDecodeError as exc:
            raise self._invalid_output_error(
                "Transcript analysis returned invalid JSON",
                raw_provider_response=payload,
                raw_content=content,
            ) from exc

        try:
            analysis = validate_analysis_output(
                raw_output=raw_output,
                provider="openai",
                model=self._model,
                prompt_version=self._prompt_version,
            )
        except InvalidLLMOutputError as exc:
            raise self._invalid_output_error(
                str(exc),
                raw_provider_response=payload,
                raw_content=content,
                parsed_output=raw_output if isinstance(raw_output, dict) else None,
            ) from exc

        return replace(
            analysis,
            raw_provider_response=payload,
            raw_content=content,
        )

    def _request_payload(self, transcript: str) -> dict[str, Any]:
        return {
            "model": self._model,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": ANALYSIS_RESPONSE_SCHEMA,
            },
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Analyze the full call transcript as one aggregate customer interaction. "
                        "If the transcript contains multiple role-play calls or segments, summarize "
                        "the overall operational outcome and choose one dominant intent and one "
                        "dominant next_action for the full transcript. Do not return per-call objects "
                        "for intent, sentiment, or next_action. Use the fixed tag categories from "
                        "the schema and return empty arrays for categories that do not apply. Return "
                        "only JSON that matches the provided schema."
                    ),
                },
                {"role": "user", "content": transcript},
            ],
        }

    def _invalid_output_error(
        self,
        message: str,
        *,
        raw_provider_response: dict[str, Any] | None = None,
        raw_content: str | None = None,
        parsed_output: dict[str, Any] | None = None,
    ) -> InvalidLLMOutputError:
        return InvalidLLMOutputError(
            message,
            provider="openai",
            model=self._model,
            prompt_version=self._prompt_version,
            raw_provider_response=raw_provider_response,
            raw_content=raw_content,
            parsed_output=parsed_output,
        )


def validate_analysis_output(
    *,
    raw_output: object,
    provider: str,
    model: str,
    prompt_version: str,
) -> TranscriptAnalysis:
    if not isinstance(raw_output, dict):
        raise InvalidLLMOutputError("Transcript analysis must be a JSON object")

    summary = raw_output.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise InvalidLLMOutputError("Transcript analysis summary is required")

    tags = raw_output.get("tags", {})
    if not isinstance(tags, dict):
        raise InvalidLLMOutputError("Transcript analysis tags must be an object")

    sentiment = _optional_enum(
        raw_output.get("sentiment"),
        allowed=ALLOWED_SENTIMENTS,
        field="sentiment",
    )
    next_action = _optional_enum(
        raw_output.get("next_action"),
        allowed=ALLOWED_NEXT_ACTIONS,
        field="next_action",
    )
    intent = raw_output.get("intent")
    if intent is not None and not isinstance(intent, str):
        raise InvalidLLMOutputError("Transcript analysis intent must be a string or null")

    risk_flags = raw_output.get("risk_flags", [])
    if not isinstance(risk_flags, list) or not all(isinstance(flag, str) for flag in risk_flags):
        raise InvalidLLMOutputError("Transcript analysis risk_flags must be an array of strings")

    return TranscriptAnalysis(
        summary=summary.strip(),
        tags=tags,
        intent=intent.strip() if isinstance(intent, str) and intent.strip() else None,
        sentiment=sentiment,
        next_action=next_action,
        risk_flags=risk_flags,
        raw_output=raw_output,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
    )


def _optional_enum(value: object, *, allowed: set[str], field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidLLMOutputError(f"Transcript analysis {field} is invalid")
    normalized = value.strip().lower()
    if normalized not in allowed:
        raise InvalidLLMOutputError(f"Transcript analysis {field} is invalid")
    return normalized


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
