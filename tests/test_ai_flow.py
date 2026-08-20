"""Secondary-key flow and status-indicator tests (MS-9)."""

from __future__ import annotations

from todoscope.ai import AnalysisItem, AnalysisResult
from todoscope.keys import KeyInfo
from todoscope.openai_client import (
    AiOutcomeKind,
    AiRequestError,
    run_ai_analysis,
)
from todoscope.status import StatusContext

ITEMS = [{"id": 1, "marker": "TODO", "text": "fix me"}]


def make_result() -> AnalysisResult:
    return AnalysisResult(
        items=(AnalysisItem(id=1, interpretation="Fix it.", priority="Low"),),
        overview="One task.",
    )


def both_keys() -> KeyInfo:
    return KeyInfo(
        primary="pk", primary_source="shell", secondary="sk", secondary_source="shell"
    )


def test_primary_success_never_touches_secondary(monkeypatch) -> None:
    calls: list[str] = []

    def fake_analyze(items, model, api_key, **kwargs):
        calls.append(api_key)
        return make_result()

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    outcome = run_ai_analysis(ITEMS, "m", both_keys(), interactive=True)
    assert outcome.kind is AiOutcomeKind.SUCCESS
    assert calls == ["pk"]


def test_confirmed_secondary_retry_uses_same_model(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_analyze(items, model, api_key, **kwargs):
        calls.append((model, api_key))
        if api_key == "pk":
            raise AiRequestError("primary down")
        return make_result()

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    answers = iter([True])

    def confirm():
        return next(answers)

    outcome = run_ai_analysis(
        ITEMS, "the-model", both_keys(), interactive=True, confirm_secondary=confirm
    )
    assert outcome.kind is AiOutcomeKind.SUCCESS
    assert outcome.result is not None
    assert calls == [("the-model", "pk"), ("the-model", "sk")]


def test_declined_secondary_is_not_used(monkeypatch) -> None:
    calls: list[str] = []

    def fake_analyze(items, model, api_key, **kwargs):
        calls.append(api_key)
        raise AiRequestError("primary down")

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    outcome = run_ai_analysis(
        ITEMS, "m", both_keys(), interactive=True, confirm_secondary=lambda: False
    )
    assert outcome.kind is AiOutcomeKind.PRIMARY_FAILED
    assert calls == ["pk"]


def test_non_interactive_never_uses_secondary(monkeypatch) -> None:
    calls: list[str] = []
    prompted: list[bool] = []

    def fake_analyze(items, model, api_key, **kwargs):
        calls.append(api_key)
        raise AiRequestError("primary down")

    def confirm():
        prompted.append(True)
        return True

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    outcome = run_ai_analysis(
        ITEMS, "m", both_keys(), interactive=False, confirm_secondary=confirm
    )
    assert outcome.kind is AiOutcomeKind.NONINTERACTIVE
    assert calls == ["pk"]
    assert prompted == []


def test_no_secondary_key_is_plain_failure(monkeypatch) -> None:
    def fake_analyze(items, model, api_key, **kwargs):
        raise AiRequestError("primary down")

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    only_primary = KeyInfo(
        primary="pk", primary_source="shell", secondary=None, secondary_source="none"
    )
    outcome = run_ai_analysis(ITEMS, "m", only_primary, interactive=True)
    assert outcome.kind is AiOutcomeKind.PRIMARY_FAILED


def test_no_primary_key_fails_without_an_attempt(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("analyze must not be called without a primary key")

    monkeypatch.setattr("todoscope.openai_client.analyze", forbidden)
    no_primary = KeyInfo(
        primary=None,
        primary_source="none",
        secondary="sk",
        secondary_source="shell",
    )
    outcome = run_ai_analysis(ITEMS, "m", no_primary, interactive=True)
    assert outcome.kind is AiOutcomeKind.PRIMARY_FAILED


def test_secondary_failure_is_reported(monkeypatch) -> None:
    def fake_analyze(items, model, api_key, **kwargs):
        raise AiRequestError(f"{api_key} down")

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    outcome = run_ai_analysis(
        ITEMS, "m", both_keys(), interactive=True, confirm_secondary=lambda: True
    )
    assert outcome.kind is AiOutcomeKind.SECONDARY_FAILED


def test_status_context_shown_around_attempts(monkeypatch) -> None:
    enters: list[int] = []

    class FakeStatus:
        def __enter__(self):
            enters.append(1)
            return self

        def __exit__(self, *exc):
            pass

    def fake_analyze(items, model, api_key, **kwargs):
        if api_key == "pk":
            raise AiRequestError("down")
        return make_result()

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    outcome = run_ai_analysis(
        ITEMS,
        "m",
        both_keys(),
        interactive=True,
        confirm_secondary=lambda: True,
        status=FakeStatus,
    )
    assert outcome.kind is AiOutcomeKind.SUCCESS
    assert len(enters) == 2


class FakeStream:
    def __init__(self, tty: bool):
        self._tty = tty
        self.written: list[str] = []

    def isatty(self) -> bool:
        return self._tty

    def write(self, text: str) -> int:
        self.written.append(text)
        return len(text)

    def flush(self) -> None:
        pass


def test_status_writes_nothing_when_not_a_tty() -> None:
    stream = FakeStream(tty=False)
    with StatusContext(stream=stream):
        pass
    assert stream.written == []


def test_status_writes_and_clears_on_tty() -> None:
    stream = FakeStream(tty=True)
    with StatusContext(stream=stream):
        pass
    assert any("Analyzing comments" in w for w in stream.written)
    assert any("\r" in w for w in stream.written)
