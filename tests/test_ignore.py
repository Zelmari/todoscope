"""@ignore directive tests (MS-36)."""

from __future__ import annotations

import json

from todoscope.cli import main
from todoscope.extraction import suppressed_by_directive


def _write_project(tmp_path, lines: list[str]) -> None:
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "a.py").write_text("".join(lines), encoding="utf-8")


def test_directive_token_boundaries() -> None:
    assert suppressed_by_directive("fix this @ignore")
    assert suppressed_by_directive("@ignore")
    assert not suppressed_by_directive("fix this @ignore,")
    assert not suppressed_by_directive("fix x@ignore now")


def test_suppressed_findings_disappear_from_text(tmp_path, capsys) -> None:
    _write_project(tmp_path, ["# TODO: keep\n", "# TODO: drop @ignore\n"])
    result = main([str(tmp_path / "src")])
    captured = capsys.readouterr()
    assert result == 0
    assert "1. a.py:1: TODO: keep" in captured.out
    assert "drop" not in captured.out
    assert "found 1 TODO comment" in captured.out


def test_json_counts_and_omits_suppressed(tmp_path, capsys) -> None:
    _write_project(tmp_path, ["# TODO: keep\n", "# TODO: drop @ignore\n"])
    result = main([str(tmp_path / "src"), "--format", "json"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    assert data["findings_count"] == 1
    assert data["findings"][0]["text"] == "keep"
    assert data["skipped"]["ignored_by_directive"] == 1


def test_suppressed_findings_absent_from_sarif_and_gha(tmp_path, capsys) -> None:
    _write_project(tmp_path, ["# TODO: drop @ignore\n"])
    result = main([str(tmp_path / "src"), "--format", "sarif"])
    captured = capsys.readouterr()
    assert result == 0
    assert json.loads(captured.out)["runs"][0]["results"] == []
    result = main([str(tmp_path / "src"), "--format", "github-actions"])
    captured = capsys.readouterr()
    assert result == 0
    assert captured.out.strip() == ""


def test_suppressed_findings_never_reach_ai(tmp_path, monkeypatch, capsys) -> None:
    from todoscope.ai import AnalysisResult

    _write_project(tmp_path, ["# TODO: drop @ignore\n"])
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-x")
    captured_items: list = []

    def fake_analyze(items, model, api_key, **kwargs):
        captured_items.append(items)
        return AnalysisResult(items=(), overview="none.")

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    result = main([str(tmp_path / "src"), "--ai"])
    capsys.readouterr()
    assert result == 0
    assert captured_items == []


def test_gate_ignores_suppressed_findings(tmp_path, capsys) -> None:
    _write_project(tmp_path, ["# TODO: drop @ignore\n"])
    result = main([str(tmp_path / "src"), "--fail"])
    captured = capsys.readouterr()
    assert result == 0
    assert "No TODO comments were found" in captured.out


def test_secret_screening_still_flags_suppressed_comments(tmp_path, capsys) -> None:
    _write_project(
        tmp_path,
        ["# TODO: rotate the sk-abcdefghijklmnopqrstuvwxyz01234567 @ignore\n"],
    )
    result = main([str(tmp_path / "src"), "--check-secrets"])
    captured = capsys.readouterr()
    assert result == 0
    assert "Possible credentials in comments" in captured.out
    assert "openai-style-api-key" in captured.out


def test_verbose_counts_ignored(tmp_path, capsys) -> None:
    _write_project(tmp_path, ["# TODO: drop @ignore\n"])
    result = main([str(tmp_path / "src"), "--verbose"])
    captured = capsys.readouterr()
    assert result == 0
    assert "Ignored via @ignore: 1" in captured.err


def test_diff_baseline_excludes_suppressed(tmp_path, capsys) -> None:
    _write_project(tmp_path, ["# TODO: one @ignore\n"])
    main([str(tmp_path / "src"), "--diff"])
    capsys.readouterr()
    result = main([str(tmp_path / "src"), "--diff"])
    captured = capsys.readouterr()
    assert result == 0
    assert "No new findings." in captured.out
