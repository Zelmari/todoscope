"""OpenAI client layer tests: mocked network, contract verification."""

from __future__ import annotations

import json

import pytest
from openai import OpenAIError

from todoscope.openai_client import (
    JSON_OBJECT_FORMAT,
    AiRequestError,
    analyze,
)


class FakeCompletions:
    def __init__(self, content: str | None = None, error: Exception | None = None):
        self.content = content
        self.error = error
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return FakeResponse(self.content)


class FakeResponse:
    def __init__(self, content: str | None):
        self.content = content
        self.choices = [FakeChoice(content)]


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeClient:
    def __init__(self, completions: FakeCompletions):
        self.chat = FakeChat(completions)


class FakeChat:
    def __init__(self, completions: FakeCompletions):
        self.completions = completions


ITEMS = [
    {"id": 1, "marker": "TODO", "text": "Handle expired refresh tokens"},
    {"id": 2, "marker": "TODO", "text": "Add an empty state"},
]

VALID_CONTENT = json.dumps(
    {
        "items": [
            {"id": 1, "interpretation": "Handle token expiry.", "priority": "High"},
            {"id": 2, "interpretation": "Add an empty state.", "priority": "Low"},
        ],
        "overview": "Authentication reliability and UI completeness.",
    }
)


def test_analyze_success_passes_validation() -> None:
    completions = FakeCompletions(VALID_CONTENT)
    client = FakeClient(completions)
    result = analyze(ITEMS, "some-model", "sk-x", client=client)
    assert [item.id for item in result.items] == [1, 2]
    assert result.overview == "Authentication reliability and UI completeness."


def test_analyze_sends_contract_payload() -> None:
    completions = FakeCompletions(VALID_CONTENT)
    client = FakeClient(completions)
    analyze(ITEMS, "some-model", "sk-x", client=client)
    call = completions.calls[0]
    assert call["model"] == "some-model"
    assert call["messages"][0]["role"] == "system"
    assert call["messages"][1]["role"] == "user"
    sent_items = json.loads(call["messages"][1]["content"])
    assert sent_items == ITEMS
    assert call["response_format"] == JSON_OBJECT_FORMAT
    assert call["timeout"] == 30.0


def test_analyze_payload_excludes_environment() -> None:
    completions = FakeCompletions(VALID_CONTENT)
    client = FakeClient(completions)
    analyze(ITEMS, "some-model", "sk-secret-key", client=client)
    serialized = json.dumps(completions.calls[0], default=str)
    assert "sk-secret-key" not in serialized


def test_analyze_rejects_non_json_content() -> None:
    completions = FakeCompletions("not json at all")
    client = FakeClient(completions)
    with pytest.raises(AiRequestError, match="not valid JSON"):
        analyze(ITEMS, "m", "k", client=client)


def test_analyze_rejects_invalid_structure() -> None:
    bad = json.dumps({"items": [{"id": 999, "interpretation": "x", "priority": "Low"}]})
    completions = FakeCompletions(bad)
    client = FakeClient(completions)
    with pytest.raises(AiRequestError, match="invalid"):
        analyze(ITEMS, "m", "k", client=client)


def test_analyze_wraps_transport_errors() -> None:
    completions = FakeCompletions(error=OpenAIError("connection reset"))
    client = FakeClient(completions)
    with pytest.raises(AiRequestError, match="the AI request failed"):
        analyze(ITEMS, "m", "k", client=client)


def test_analyze_rejects_empty_choices() -> None:
    class EmptyChoicesCompletions:
        def create(self, **kwargs):
            return type("EmptyResponse", (), {"choices": []})()

    client = FakeClient(EmptyChoicesCompletions())
    with pytest.raises(AiRequestError, match="no choices"):
        analyze(ITEMS, "m", "k", client=client)


@pytest.mark.parametrize("api_key", [None, "", "   ", 3])
def test_analyze_rejects_invalid_api_keys(api_key) -> None:
    completions = FakeCompletions(VALID_CONTENT)
    client = FakeClient(completions)
    with pytest.raises(AiRequestError, match="non-empty API key"):
        analyze(ITEMS, "m", api_key, client=client)
    assert completions.calls == []


def test_analyze_accepts_explicit_no_format() -> None:
    completions = FakeCompletions(VALID_CONTENT)
    client = FakeClient(completions)
    result = analyze(ITEMS, "m", "k", client=client, response_format={})
    assert "response_format" not in completions.calls[0]
    assert len(result.items) == 2


def test_default_client_has_no_retries(monkeypatch) -> None:
    created: list[dict] = []

    class RecordingOpenAI:
        def __init__(self, **kwargs):
            created.append(kwargs)
            self.chat = FakeChat(FakeCompletions(VALID_CONTENT))

    monkeypatch.setattr("todoscope.openai_client.OpenAI", RecordingOpenAI)
    analyze(ITEMS, "m", "k")
    assert created[0]["max_retries"] == 0


def test_default_client_construction_error_is_wrapped(monkeypatch) -> None:
    def fail(**kwargs):
        raise OpenAIError("bad credentials")

    monkeypatch.setattr("todoscope.openai_client.OpenAI", fail)
    with pytest.raises(AiRequestError, match="AI request failed"):
        analyze(ITEMS, "m", "k")
