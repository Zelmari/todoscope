"""AI result cache tests (MS-26)."""

from __future__ import annotations

import json

from todoscope.ai import AnalysisItem, AnalysisResult
from todoscope.cache import (
    CACHE_SCHEMA_VERSION,
    cache_path,
    item_key,
    load_cache,
    run_cached_analysis,
    run_key,
    save_cache,
)
from todoscope.cli import main
from todoscope.keys import KeyInfo
from todoscope.openai_client import AiOutcome, AiOutcomeKind


def keys() -> KeyInfo:
    return KeyInfo(
        primary="sk-x",
        primary_source="shell",
        secondary=None,
        secondary_source="none",
    )


ITEMS = [
    {"id": 1, "marker": "TODO", "text": "fix refresh"},
    {"id": 2, "marker": "TODO", "text": "add empty state"},
]


def result(ids=(1, 2), overview="Summary.") -> AnalysisResult:
    return AnalysisResult(
        items=tuple(
            AnalysisItem(id=i, interpretation=f"About {i}.", priority="Low")
            for i in ids
        ),
        overview=overview,
    )


def test_cache_path_uses_xdg(monkeypatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", "/tmp/cache-root")
    assert cache_path() == __import__("pathlib").Path(
        "/tmp/cache-root/todoscope/ai-cache.json"
    )


def test_cache_path_defaults_to_home_cache(monkeypatch) -> None:
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    path = cache_path()
    assert path.name == "ai-cache.json"
    assert path.parent.name == "todoscope"


def test_item_key_is_stable_and_sensitive_to_inputs() -> None:
    first = item_key("TODO", "fix refresh", "m")
    assert first == item_key("TODO", "fix refresh", "m")
    assert first != item_key("FIXME", "fix refresh", "m")
    assert first != item_key("TODO", "fix refresh!", "m")
    assert first != item_key("TODO", "fix refresh", "m2")


def test_run_key_is_order_independent() -> None:
    keys = ("a", "b", "c")
    assert run_key(keys) == run_key(tuple(reversed(keys)))
    assert run_key(keys) != run_key(keys + ("d",))


def test_load_cache_handles_missing_and_corrupt(tmp_path) -> None:
    assert load_cache(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_cache(bad) == {}
    not_a_dict = tmp_path / "list.json"
    not_a_dict.write_text("[]", encoding="utf-8")
    assert load_cache(not_a_dict) == {}


def test_save_cache_roundtrip(tmp_path) -> None:
    path = tmp_path / "deep" / "ai-cache.json"
    assert save_cache(path, {"schema": CACHE_SCHEMA_VERSION, "items": {}}) is True
    assert load_cache(path) == {"schema": CACHE_SCHEMA_VERSION, "items": {}}


def test_save_cache_failure_is_reported(tmp_path, monkeypatch) -> None:
    path = tmp_path / "ai-cache.json"

    def fail_write(self, *args, **kwargs):
        raise OSError("denied")

    monkeypatch.setattr("todoscope.cache.Path.write_text", fail_write)
    assert save_cache(path, {}) is False


def _fake_run(ids=(1, 2)):
    def fake_run(items, model, keys, **kwargs):
        return AiOutcome(
            AiOutcomeKind.SUCCESS,
            result(ids=tuple(item["id"] for item in items)),
        )

    return fake_run


def test_full_cache_hit_makes_no_request(monkeypatch) -> None:
    cache: dict = {}
    monkeypatch.setattr("todoscope.cache.run_ai_analysis", _fake_run())
    outcome, used = run_cached_analysis(
        ITEMS, "m", keys(), cache=cache, interactive=False
    )
    assert outcome.kind is AiOutcomeKind.SUCCESS
    assert used is False
    primed = outcome.result
    assert primed is not None

    def forbidden(*args, **kwargs):
        raise AssertionError("no request may be made on a full cache hit")

    monkeypatch.setattr("todoscope.cache.run_ai_analysis", forbidden)
    outcome, used = run_cached_analysis(
        ITEMS, "m", keys(), cache=cache, interactive=False
    )
    assert used is True
    assert outcome.kind is AiOutcomeKind.SUCCESS
    assert outcome.result == primed


def test_partial_cache_sends_only_missing(monkeypatch) -> None:
    cache: dict = {}
    monkeypatch.setattr("todoscope.cache.run_ai_analysis", _fake_run())
    run_cached_analysis([ITEMS[0]], "m", keys(), cache=cache, interactive=False)
    sent: list = []

    def recording(items, model, keys, **kwargs):
        sent.append(items)
        return AiOutcome(AiOutcomeKind.SUCCESS, result(ids=(2,)))

    monkeypatch.setattr("todoscope.cache.run_ai_analysis", recording)
    outcome, used = run_cached_analysis(
        ITEMS, "m", keys(), cache=cache, interactive=False
    )
    assert used is False
    assert [item["id"] for item in sent[0]] == [2]
    assert outcome.kind is AiOutcomeKind.SUCCESS
    assert outcome.result is not None
    assert [item.id for item in outcome.result.items] == [1, 2]
    assert outcome.result.items[0].interpretation == "About 1."
    assert outcome.result.items[1].interpretation == "About 2."


def test_no_cache_disables_reads_and_writes(monkeypatch) -> None:
    sent: list = []

    def recording(items, model, keys, **kwargs):
        sent.append(items)
        return AiOutcome(AiOutcomeKind.SUCCESS, result())

    monkeypatch.setattr("todoscope.cache.run_ai_analysis", recording)
    outcome, used = run_cached_analysis(
        ITEMS, "m", keys(), cache=None, interactive=False
    )
    assert used is False
    assert [item["id"] for item in sent[0]] == [1, 2]


def test_failed_request_does_not_poison_cache(monkeypatch) -> None:
    from todoscope.openai_client import AiRequestError

    cache: dict = {}

    def failing(items, model, keys, **kwargs):
        try:
            raise AiRequestError("transport failure")
        except AiRequestError:
            return AiOutcome(AiOutcomeKind.PRIMARY_FAILED)

    monkeypatch.setattr("todoscope.cache.run_ai_analysis", failing)
    outcome, _ = run_cached_analysis(ITEMS, "m", keys(), cache=cache, interactive=False)
    assert outcome.kind is AiOutcomeKind.PRIMARY_FAILED
    assert cache.get("items") == {}


def _write_project(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("# TODO: fix refresh\n", encoding="utf-8")
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')


def _fake_analyze_factory(calls: list):
    def fake_analyze(items, model, api_key, **kwargs):
        calls.append(items)
        ids = [item["id"] for item in items]
        return AnalysisResult(
            items=tuple(
                AnalysisItem(id=i, interpretation="Fix it.", priority="Low")
                for i in ids
            ),
            overview="One comment.",
        )

    return fake_analyze


def test_cli_caches_results_across_runs(tmp_path, monkeypatch, capsys) -> None:
    _write_project(tmp_path)
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-x")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    calls: list = []
    monkeypatch.setattr("todoscope.openai_client.analyze", _fake_analyze_factory(calls))

    result = main([str(tmp_path / "src"), "--ai"])
    captured = capsys.readouterr()
    assert result == 0
    assert "Overall AI summary" in captured.out
    assert len(calls) == 1
    assert "served from the local cache" not in captured.out

    calls.clear()
    monkeypatch.setattr(
        "todoscope.openai_client.analyze",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("cache must make the second run request-free")
        ),
    )
    result = main([str(tmp_path / "src"), "--ai"])
    captured = capsys.readouterr()
    assert result == 0
    assert "Interpretations served from the local cache." in captured.out
    assert calls == []


def test_cli_cache_never_stores_paths(tmp_path, monkeypatch, capsys) -> None:
    _write_project(tmp_path)
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-x")
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))
    calls: list = []
    monkeypatch.setattr("todoscope.openai_client.analyze", _fake_analyze_factory(calls))
    result = main([str(tmp_path / "src"), "--ai", "--format", "json"])
    captured = capsys.readouterr()
    assert result == 0
    cache_text = (cache_dir / "todoscope" / "ai-cache.json").read_text(encoding="utf-8")
    assert "app.py" not in cache_text
    assert "src" not in cache_text
    data = json.loads(captured.out)
    assert data["ai"]["status"] == "completed"


def test_cli_json_marks_cached_run(tmp_path, monkeypatch, capsys) -> None:
    _write_project(tmp_path)
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-x")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    calls: list = []
    monkeypatch.setattr("todoscope.openai_client.analyze", _fake_analyze_factory(calls))
    main([str(tmp_path / "src"), "--ai"])
    capsys.readouterr()
    result = main([str(tmp_path / "src"), "--ai", "--format", "json"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    assert data["ai"]["cached"] is True


def test_cli_no_cache_bypasses_cache(tmp_path, monkeypatch, capsys) -> None:
    _write_project(tmp_path)
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-x")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    calls: list = []
    monkeypatch.setattr("todoscope.openai_client.analyze", _fake_analyze_factory(calls))
    main([str(tmp_path / "src"), "--ai"])
    capsys.readouterr()
    calls.clear()
    result = main([str(tmp_path / "src"), "--ai", "--no-cache"])
    captured = capsys.readouterr()
    assert result == 0
    assert len(calls) == 1
    assert "served from the local cache" not in captured.out
