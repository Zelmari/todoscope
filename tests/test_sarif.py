"""SARIF output mode tests (MS-23)."""

from __future__ import annotations

import json

from todoscope.ai import AnalysisItem, AnalysisResult
from todoscope.cli import main
from todoscope.config import load_config
from todoscope.extraction import Finding
from todoscope.sarif import DEFAULT_LEVEL, SARIF_SCHEMA, SARIF_VERSION, sarif_report
from todoscope.scan import IndexedFinding


def indexed() -> tuple[IndexedFinding, ...]:
    return (
        IndexedFinding(id=1, finding=Finding("TODO", "one", "a.py", 3)),
        IndexedFinding(id=2, finding=Finding("FIXME", "two", "src/b.js", 7)),
    )


def report(tmp_path, **kwargs):
    return sarif_report(indexed(), load_config(tmp_path), files_scanned=5, **kwargs)


def test_sarif_version_and_tool(tmp_path) -> None:
    data = report(tmp_path)
    assert data["version"] == SARIF_VERSION
    assert data["$schema"] == SARIF_SCHEMA
    driver = data["runs"][0]["tool"]["driver"]
    assert driver["name"] == "todoscope"
    assert driver["informationUri"] == "https://github.com/Zelmari/todoscope"


def test_one_rule_per_marker(tmp_path) -> None:
    (tmp_path / ".todoscope.json").write_text('{"markers": ["TODO", "FIXME"]}')
    data = report(tmp_path)
    rules = data["runs"][0]["tool"]["driver"]["rules"]
    assert [rule["id"] for rule in rules] == ["TODO", "FIXME"]
    assert rules[0]["name"] == "TODO comment"


def test_results_carry_location_and_message(tmp_path) -> None:
    data = report(tmp_path)
    results = data["runs"][0]["results"]
    assert results[0]["ruleId"] == "TODO"
    assert results[0]["message"] == {"text": "TODO: one"}
    location = results[0]["locations"][0]["physicalLocation"]
    assert location["artifactLocation"] == {"uri": "a.py"}
    assert location["region"] == {"startLine": 3}
    assert results[1]["ruleId"] == "FIXME"


def test_levels_follow_ai_priorities(tmp_path) -> None:
    ai_result = AnalysisResult(
        items=(
            AnalysisItem(id=1, interpretation="One.", priority="High"),
            AnalysisItem(id=2, interpretation="Two.", priority="Unclear"),
        ),
        overview="Summary.",
    )
    data = report(tmp_path, ai_result=ai_result)
    results = data["runs"][0]["results"]
    assert results[0]["level"] == "error"
    assert results[1]["level"] == "note"
    assert results[0]["properties"]["priority"] == "High"


def test_default_level_without_ai(tmp_path) -> None:
    data = report(tmp_path)
    for result in data["runs"][0]["results"]:
        assert result["level"] == DEFAULT_LEVEL


def test_run_properties_are_deterministic(tmp_path) -> None:
    assert report(tmp_path) == report(tmp_path)


def test_output_never_contains_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-sarif-secret")
    monkeypatch.setenv("TODOSCOPE_SECONDARY_API_KEY", "sk-sarif-secret-2")
    text = json.dumps(report(tmp_path))
    assert "sk-sarif-secret" not in text
    assert "TODOSCOPE_API_KEY" not in text


def test_cli_prints_valid_sarif(tmp_path, capsys) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix me\n")
    result = main([str(tmp_path / "src"), "--format", "sarif"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    assert data["version"] == SARIF_VERSION
    assert data["runs"][0]["results"][0]["message"] == {"text": "TODO: fix me"}
    assert data["runs"][0]["properties"]["files_scanned"] == 1


def test_cli_sarif_with_ai_levels(tmp_path, monkeypatch, capsys) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix me\n")
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-sarif")

    def fake_analyze(items, model, api_key, **kwargs):
        return AnalysisResult(
            items=(
                AnalysisItem(
                    id=items[0]["id"], interpretation="Fix it.", priority="Medium"
                ),
            ),
            overview="One comment.",
        )

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    result = main([str(tmp_path / "src"), "--ai", "--format", "sarif"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    result_entry = data["runs"][0]["results"][0]
    assert result_entry["level"] == "warning"
    assert result_entry["properties"]["priority"] == "Medium"
