"""GitHub Actions workflow command output tests (MS-29)."""

from __future__ import annotations

from todoscope.ai import AnalysisItem, AnalysisResult
from todoscope.cli import main
from todoscope.extraction import Finding
from todoscope.gha import DEFAULT_COMMAND, gha_report
from todoscope.scan import IndexedFinding


def indexed() -> tuple[IndexedFinding, ...]:
    return (
        IndexedFinding(id=1, finding=Finding("TODO", "fix me", "a.py", 3)),
        IndexedFinding(id=2, finding=Finding("FIXME", "later", "src/b.js", 7)),
    )


def test_default_level_is_warning() -> None:
    out = gha_report(indexed())
    assert out.splitlines()[0].startswith("::warning ")
    assert "file=a.py" in out.splitlines()[0]
    assert "line=3" in out.splitlines()[0]
    assert "endLine=3" in out.splitlines()[0]
    assert "title=TODO" in out.splitlines()[0]
    assert out.splitlines()[0].endswith("::TODO: fix me")


def test_ai_priorities_map_to_commands() -> None:
    ai_result = AnalysisResult(
        items=(
            AnalysisItem(id=1, interpretation="x", priority="High"),
            AnalysisItem(id=2, interpretation="x", priority="Unclear"),
        ),
        overview="s",
    )
    out = gha_report(indexed(), ai_result)
    lines = out.splitlines()
    assert lines[0].startswith("::error ")
    assert lines[1].startswith("::notice ")


def test_escaping_follows_workflow_command_spec() -> None:
    findings = (
        IndexedFinding(
            id=1,
            finding=Finding("TODO", "100% done\r\nnext line", "weird name %x.py", 1),
        ),
    )
    out = gha_report(findings)
    line = out.splitlines()[0]
    assert "%25" in line
    assert "%0D" in line
    assert "%0A" in line
    assert "%25x" in line


def test_output_is_deterministic() -> None:
    assert gha_report(indexed()) == gha_report(indexed())


def test_empty_findings_produce_no_commands() -> None:
    assert gha_report(()) == ""


def test_cli_prints_workflow_commands(tmp_path, capsys) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix me\n")
    result = main([str(tmp_path / "src"), "--format", "github-actions"])
    captured = capsys.readouterr()
    assert result == 0
    assert captured.out.startswith(f"::{DEFAULT_COMMAND} file=a.py,line=1,")
    assert captured.out.rstrip().endswith("::TODO: fix me")


def test_cli_annotations_with_ai_levels(tmp_path, monkeypatch, capsys) -> None:
    from todoscope.ai import AnalysisItem, AnalysisResult

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix me\n")
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-x")

    def fake_analyze(items, model, api_key, **kwargs):
        return AnalysisResult(
            items=(
                AnalysisItem(
                    id=items[0]["id"], interpretation="Fix it.", priority="High"
                ),
            ),
            overview="One comment.",
        )

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    result = main([str(tmp_path / "src"), "--ai", "--format", "github-actions"])
    captured = capsys.readouterr()
    assert result == 0
    assert captured.out.startswith("::error file=src/a.py,line=1,")


def test_annotations_never_contain_keys(tmp_path, monkeypatch, capsys) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix me\n")
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-gha-secret")
    result = main([str(tmp_path / "src"), "--format", "github-actions"])
    captured = capsys.readouterr()
    assert result == 0
    assert "sk-gha-secret" not in captured.out
    assert "TODOSCOPE_API_KEY" not in captured.out
