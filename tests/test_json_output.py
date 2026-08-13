"""JSON output mode tests (MS-12)."""

from __future__ import annotations

import json

from todoscope.ai import AnalysisItem, AnalysisResult
from todoscope.cli import main
from todoscope.discovery import ScanStats
from todoscope.extraction import Finding
from todoscope.report import json_report
from todoscope.scan import IndexedFinding


def indexed() -> tuple[IndexedFinding, ...]:
    return (
        IndexedFinding(id=1, finding=Finding("TODO", "one", "a.py", 3)),
        IndexedFinding(id=2, finding=Finding("FIXME", "two", "src/b.js", 7)),
    )


def test_json_report_shape(tmp_path) -> None:
    config = tmp_path / ".todoscope.json"
    config.write_text('{"markers": ["TODO", "FIXME"]}')
    from todoscope.config import load_config

    data = json_report(
        indexed(),
        5,
        "src/",
        tmp_path,
        load_config(tmp_path),
        ScanStats(scanned=5, unsupported=2, ignored_by_gitignore=1),
    )
    assert data["tool"] == "todoscope"
    assert data["findings_count"] == 2
    assert data["findings"][0] == {
        "id": 1,
        "marker": "TODO",
        "text": "one",
        "path": "a.py",
        "line": 3,
    }
    assert data["skipped"]["unsupported"] == 2
    assert data["ai"] is None


def test_json_report_ai_completed(tmp_path) -> None:
    from todoscope.config import load_config

    ai_result = AnalysisResult(
        items=(AnalysisItem(id=1, interpretation="One.", priority="High"),),
        overview="Summary.",
    )
    data = json_report(
        (indexed()[0],),
        1,
        ".",
        tmp_path,
        load_config(tmp_path),
        ScanStats(scanned=1),
        ai_result=ai_result,
    )
    assert data["ai"]["status"] == "completed"
    assert data["ai"]["items"][0]["priority"] == "High"
    assert "No source code was provided to the AI." in data["ai"]["disclaimer"]


def test_json_report_ai_skipped(tmp_path) -> None:
    from todoscope.config import load_config

    data = json_report(
        indexed(),
        2,
        ".",
        tmp_path,
        load_config(tmp_path),
        ScanStats(scanned=2),
        ai_status="skipped",
        ai_reason="no-key",
    )
    assert data["ai"] == {"status": "skipped", "reason": "no-key"}


def test_json_contains_no_keys(tmp_path, monkeypatch, capsys) -> None:
    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    (tmp_path / "a.py").write_text("# TODO: one\n")
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-json-secret")
    monkeypatch.setenv("TODOSCOPE_SECONDARY_API_KEY", "sk-json-secret-2")

    def fake_analyze(items, model, api_key, **kwargs):
        return AnalysisResult(
            items=(AnalysisItem(id=1, interpretation="One.", priority="Low"),),
            overview="S.",
        )

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    result = main([str(tmp_path), "--format", "json"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    assert data["ai"]["status"] == "completed"
    assert "sk-json-secret" not in captured.out


def test_json_ai_failed_reason_mapping(tmp_path, monkeypatch, capsys) -> None:
    from todoscope.openai_client import AiRequestError

    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    (tmp_path / "a.py").write_text("# TODO: one\n")
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-a")
    monkeypatch.setenv("TODOSCOPE_SECONDARY_API_KEY", "sk-b")

    def fake_analyze(items, model, api_key, **kwargs):
        raise AiRequestError("down")

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    result = main(
        [str(tmp_path), "--format", "json"],
        interactive=True,
        confirm_secondary=lambda: False,
        status=None,
    )
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    assert data["ai"]["status"] == "failed"
    assert data["ai"]["reason"] == "primary-failed"
    assert data["findings_count"] == 1


def test_json_quiet_combination_uses_json(tmp_path, capsys) -> None:
    (tmp_path / "a.py").write_text("# TODO: one\n")
    result = main([str(tmp_path), "--quiet", "--format", "json"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    assert data["findings_count"] == 1
    assert data["ai"]["status"] == "skipped"
