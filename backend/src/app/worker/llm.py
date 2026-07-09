from __future__ import annotations

import json
from dataclasses import dataclass
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


class LLMClientError(Exception):
    pass


class InvalidLLMOutputError(LLMClientError):
    pass


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

        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMClientError("Transcript analysis failed") from exc

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise InvalidLLMOutputError("Transcript analysis returned malformed output") from exc
        if not isinstance(content, str):
            raise InvalidLLMOutputError("Transcript analysis returned malformed output")

        try:
            raw_output = json.loads(content)
        except json.JSONDecodeError as exc:
            raise InvalidLLMOutputError("Transcript analysis returned invalid JSON") from exc

        return validate_analysis_output(
            raw_output=raw_output,
            provider="openai",
            model=self._model,
            prompt_version=self._prompt_version,
        )

    def _request_payload(self, transcript: str) -> dict[str, Any]:
        return {
            "model": self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Analyze the sales call transcript. Return only JSON with keys: "
                        "summary, tags, intent, sentiment, next_action, risk_flags. "
                        "sentiment must be one of positive, neutral, negative, mixed. "
                        "next_action must be one of send_info, schedule_demo, follow_up, "
                        "escalate, close_lost, none. tags must be an object and "
                        "risk_flags must be an array of strings."
                    ),
                },
                {"role": "user", "content": transcript},
            ],
        }


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
    if not isinstance(value, str) or value not in allowed:
        raise InvalidLLMOutputError(f"Transcript analysis {field} is invalid")
    return value
