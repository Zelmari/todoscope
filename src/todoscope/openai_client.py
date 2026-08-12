"""OpenAI request layer (MS-8): one constrained request, validated response.

Kept strictly separate from scanning, parsing, configuration, and output.
No retries are performed: the SDK client is created with ``max_retries=0``
and a fixed timeout applies to the single request (Overarching 25).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openai import OpenAI, OpenAIError

from todoscope.ai import (
    SYSTEM_PROMPT,
    AnalysisResult,
    ResponseValidationError,
    validate_response,
)

REQUEST_TIMEOUT_SECONDS = 30.0

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "interpretation": {"type": "string"},
                    "priority": {
                        "type": "string",
                        "enum": ["High", "Medium", "Low", "Unclear"],
                    },
                },
                "required": ["id", "interpretation", "priority"],
                "additionalProperties": False,
            },
        },
        "overview": {"type": "string"},
    },
    "required": ["items", "overview"],
    "additionalProperties": False,
}

JSON_OBJECT_FORMAT: dict[str, Any] = {"type": "json_object"}


class AiRequestError(Exception):
    """The AI request failed or returned something unusable."""


@dataclass(frozen=True, slots=True)
class AiRequestOptions:
    model: str
    api_key: str
    timeout: float = REQUEST_TIMEOUT_SECONDS
    response_format: dict[str, Any] | None = None


def _default_format() -> dict[str, Any]:
    return dict(JSON_OBJECT_FORMAT)


def analyze(
    items: list[dict[str, Any]],
    model: str,
    api_key: str,
    *,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
    response_format: dict[str, Any] | None = None,
    client: OpenAI | None = None,
) -> AnalysisResult:
    """Send exactly one request and return a validated analysis.

    ``response_format`` may be ``{}`` to skip the structured-output hint
    entirely; the client-side validation below is never weakened.
    """
    if response_format is None:
        response_format = _default_format()
    if client is None:
        client = OpenAI(api_key=api_key, max_retries=0)

    kwargs: dict[str, Any] = {}
    if response_format:
        kwargs["response_format"] = response_format
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(items, ensure_ascii=False)},
            ],
            timeout=timeout,
            **kwargs,
        )
    except OpenAIError as exc:
        raise AiRequestError(f"the AI request failed: {exc}") from exc

    content = response.choices[0].message.content
    if not isinstance(content, str):
        raise AiRequestError("the AI response contained no text")
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AiRequestError("the AI response was not valid JSON") from exc
    try:
        return validate_response(data, [item["id"] for item in items])
    except ResponseValidationError as exc:
        raise AiRequestError(f"the AI response was invalid: {exc}") from exc
