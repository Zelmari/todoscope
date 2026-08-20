"""CLI smoke tests for the Milestone 1 foundation."""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import version

import pytest

from todoscope.cli import PROG, _is_interactive, build_parser, main


def test_help_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert PROG in captured.out
    assert "Find maintenance comments in source code." in captured.out


def test_version_uses_package_metadata(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert f"{PROG} {version('todoscope')}" in captured.out


def test_build_parser_returns_argparse_parser() -> None:
    parser = build_parser()
    assert parser.prog == PROG
    assert parser.description == "Find maintenance comments in source code."


def test_is_interactive_handles_missing_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("todoscope.cli.sys.stdin", None)
    monkeypatch.setattr("todoscope.cli.sys.stdout", None)
    assert not _is_interactive()


@pytest.mark.parametrize("error", [OSError("closed"), ValueError("closed")])
def test_is_interactive_handles_unusable_streams(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    class UnusableStream:
        def isatty(self) -> bool:
            raise error

    stream = UnusableStream()
    monkeypatch.setattr("todoscope.cli.sys.stdin", stream)
    monkeypatch.setattr("todoscope.cli.sys.stdout", stream)
    assert not _is_interactive()


def test_module_entry_point_succeeds() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "todoscope", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Find maintenance comments in source code." in result.stdout


def test_missing_path_argument_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_nonexistent_path_fails_with_exit_code_2(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = main([str(tmp_path / "missing-folder")])
    captured = capsys.readouterr()
    assert result == 2
    assert "does not exist" in captured.err


def test_valid_directory_produces_local_report(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix me\n")
    result = main([str(tmp_path / "src")])
    captured = capsys.readouterr()
    assert result == 0
    assert "Scanned 1 file in '" in captured.out
    assert "and found 1 TODO comment." in captured.out
    assert "1. a.py:1: TODO: fix me" in captured.out
    assert "AI analysis skipped" not in captured.out


def test_relative_subdirectory_uses_parent_project_root(
    tmp_path, monkeypatch, capsys
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".todoscope.json").write_text('{"markers": ["FIXME"]}')
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "a.py").write_text("# FIXME: from parent config\n")
    monkeypatch.chdir(sub)
    result = main(["."])
    captured = capsys.readouterr()
    assert result == 0
    assert "1. sub/a.py:1: FIXME: from parent config" in captured.out


def test_no_findings_report(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print(1)\n")
    result = main([str(tmp_path / "src")])
    captured = capsys.readouterr()
    assert result == 0
    assert "No TODO comments were found." in captured.out


def test_quiet_mode_prints_one_line_per_finding(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.py").write_text("# TODO: one\n")
    (tmp_path / "b.py").write_text("# TODO: two\n")
    result = main([str(tmp_path), "--quiet"])
    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == "1. a.py:1: TODO: one\n2. b.py:1: TODO: two\n"


def test_quiet_ai_conflict_prints_quiet_lines_without_ai_request(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    (tmp_path / "a.py").write_text("# TODO: one\n")
    (tmp_path / "b.py").write_text("# TODO: two\n")
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-shell-secret")
    calls: list[tuple[str, str]] = []

    def fake_analyze(items, model, api_key, **kwargs):
        calls.append((model, api_key))

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    result = main([str(tmp_path), "--quiet", "--ai"])
    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == "--quiet and --ai cannot be used together.\n"
    assert captured.out == "1. a.py:1: TODO: one\n2. b.py:1: TODO: two\n"
    assert calls == []


def test_default_run_keeps_report_without_ai_lines(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.py").write_text("# TODO: one\n")
    result = main([str(tmp_path)])
    captured = capsys.readouterr()
    assert result == 0
    assert "1. a.py:1: TODO: one" in captured.out
    assert "AI analysis skipped" not in captured.out
    assert "AI:" not in captured.out


def test_default_run_with_configured_ai_makes_no_ai_request(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    (tmp_path / "a.py").write_text("# TODO: one\n")
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-shell-secret")
    calls: list[tuple[str, str]] = []

    def fake_analyze(items, model, api_key, **kwargs):
        calls.append((model, api_key))

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    result = main([str(tmp_path)])
    captured = capsys.readouterr()
    assert result == 0
    assert calls == []
    assert "1. a.py:1: TODO: one" in captured.out
    assert "AI analysis skipped" not in captured.out
    assert "sk-shell-secret" not in captured.out
    assert "sk-shell-secret" not in captured.err


def test_default_skip_line_names_missing_model(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.py").write_text("# TODO: one\n")
    result = main([str(tmp_path), "--ai"])
    captured = capsys.readouterr()
    assert result == 0
    assert "AI analysis skipped: no model was configured." in captured.out


def test_verbose_details_go_to_stderr(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".gitignore").write_text("gen/\n")
    (tmp_path / "a.py").write_text("# TODO: one\n")
    (tmp_path / "gen").mkdir()
    (tmp_path / "gen" / "x.py").write_text("# TODO: gen\n")
    result = main([str(tmp_path), "--verbose"])
    captured = capsys.readouterr()
    assert result == 0
    assert "Configuration file: (defaults)" in captured.err
    assert "Project root:" in captured.err
    assert ".gitignore:" in captured.err
    assert "Excluded by .gitignore: 1" in captured.err
    assert "Scan duration:" in captured.err
    assert "TODO: one" in captured.out
    assert "gen" not in captured.out


def test_config_error_exits_with_code_3(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".todoscope.json").write_text("{not json")
    result = main([str(tmp_path)])
    captured = capsys.readouterr()
    assert result == 3
    assert "invalid JSON" in captured.err


def test_invalid_utf8_config_exits_with_code_3(tmp_path, capsys) -> None:
    (tmp_path / ".todoscope.json").write_bytes(b"\xff")
    (tmp_path / "a.py").write_text("# TODO\n")
    result = main([str(tmp_path)])
    captured = capsys.readouterr()
    assert result == 3
    assert "Cannot read" in captured.err
    assert captured.out == ""


def test_explicit_symlink_directory_never_scans_outside_project(
    tmp_path, monkeypatch, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("# TODO: outside\n")
    link = project / "linked"
    link.symlink_to(outside, target_is_directory=True)

    def forbidden(*args, **kwargs):
        raise AssertionError("AI must not be called for a symlink target")

    monkeypatch.setattr("todoscope.openai_client.analyze", forbidden)
    result = main([str(link), "--ai", "--verbose"])
    captured = capsys.readouterr()
    assert result == 0
    assert "TODO: outside" not in captured.out
    assert "No TODO comments were found." in captured.out
    assert "Symlinks skipped: 1" in captured.err


def test_explicit_ignored_target_interactive_confirm(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".gitignore").write_text("generated/\n")
    gen = tmp_path / "generated"
    gen.mkdir()
    (gen / "x.py").write_text("# TODO\n")
    confirmations: list[tuple[str, str, bool]] = []

    def confirm(relative: str, source: str, ai_enabled: bool) -> bool:
        confirmations.append((relative, source, ai_enabled))
        return True

    result = main([str(gen)], interactive=True, confirm=confirm)
    captured = capsys.readouterr()
    assert result == 0
    assert confirmations == [("generated", "gitignore", False)]
    assert "x.py" in captured.out


def test_ignored_target_confirmation_receives_ai_disclosure_flag(
    tmp_path, capsys
) -> None:
    (tmp_path / ".gitignore").write_text("generated/\n")
    gen = tmp_path / "generated"
    gen.mkdir()
    (gen / "x.py").write_text("# TODO\n")
    confirmations: list[bool] = []

    def confirm(relative: str, source: str, ai_enabled: bool) -> bool:
        confirmations.append(ai_enabled)
        return False

    result = main([str(gen), "--ai"], interactive=True, confirm=confirm)
    captured = capsys.readouterr()
    assert result == 0
    assert confirmations == [True]
    assert captured.out == ""


def test_explicit_ignored_target_interactive_decline(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".gitignore").write_text("generated/\n")
    gen = tmp_path / "generated"
    gen.mkdir()
    (gen / "x.py").write_text("# TODO\n")

    def confirm(relative: str, source: str, ai_enabled: bool) -> bool:
        return False

    result = main([str(gen)], interactive=True, confirm=confirm)
    captured = capsys.readouterr()
    assert result == 0
    assert "x.py" not in captured.out


def test_explicit_ignored_target_non_interactive_refuses(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".gitignore").write_text("generated/\n")
    gen = tmp_path / "generated"
    gen.mkdir()
    (gen / "x.py").write_text("# TODO\n")
    result = main([str(gen)], interactive=False)
    captured = capsys.readouterr()
    assert result == 2
    assert "ignored by .gitignore" in captured.err
    assert "x.py" not in captured.out


def test_explicit_config_excluded_target_confirmation(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".todoscope.json").write_text('{"exclude": ["fixtures/"]}')
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "a.py").write_text("# TODO\n")

    def confirm(relative: str, source: str, ai_enabled: bool) -> bool:
        return True

    result = main([str(fixtures)], interactive=True, confirm=confirm)
    captured = capsys.readouterr()
    assert result == 0
    assert "a.py" in captured.out


def test_unignored_env_file_refuses_ai_but_prints_report(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    (tmp_path / ".env").write_text("TODOSCOPE_API_KEY=sk-env-secret\n")
    (tmp_path / "a.py").write_text("# TODO: one\n")
    monkeypatch.delenv("TODOSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("TODOSCOPE_SECONDARY_API_KEY", raising=False)
    result = main([str(tmp_path), "--ai"])
    captured = capsys.readouterr()
    assert result == 0
    assert "TODO: one" in captured.out
    assert (
        "AI analysis skipped: the API key would be loaded from a .env file that "
        "is not ignored by .gitignore." in captured.out
    )
    assert "sk-env-secret" not in captured.out
    assert "sk-env-secret" not in captured.err


def test_shell_key_with_ignored_env_file_is_eligible(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from todoscope.ai import AnalysisItem, AnalysisResult

    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    (tmp_path / "a.py").write_text("# TODO: one\n")
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-shell-secret")

    def fake_analyze(items, model, api_key, **kwargs):
        return AnalysisResult(
            items=(AnalysisItem(id=1, interpretation="One.", priority="Low"),),
            overview="Summary.",
        )

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    result = main([str(tmp_path), "--ai"])
    captured = capsys.readouterr()
    assert result == 0
    assert "TODO: one" in captured.out
    assert "   AI: One. (Low)" in captured.out
    assert "Overall AI summary" in captured.out
    assert "AI analysis skipped" not in captured.out
    assert "sk-shell-secret" not in captured.out
    assert "sk-shell-secret" not in captured.err


def test_oversized_payload_skips_ai_and_keeps_findings(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".todoscope.json").write_text('{"model": "m", "max_ai_characters": 10}')
    (tmp_path / "a.py").write_text("# TODO: this comment is far too long\n")
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-shell-secret")
    result = main([str(tmp_path), "--ai"])
    captured = capsys.readouterr()
    assert result == 0
    assert "TODO: this comment is far too long" in captured.out
    assert "AI analysis skipped." in captured.out
    assert "exceed the maximum AI payload size" in captured.out
    assert "Scan a narrower file or directory." in captured.out
    assert "sk-shell-secret" not in captured.out


def test_ai_success_merges_into_report(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from todoscope.ai import AnalysisItem, AnalysisResult

    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    (tmp_path / "a.py").write_text("# TODO: fix the thing\n")
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-shell-secret")

    def fake_analyze(items, model, api_key, **kwargs):
        return AnalysisResult(
            items=(
                AnalysisItem(id=1, interpretation="Fix the thing.", priority="Medium"),
            ),
            overview="One maintenance task.",
        )

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    result = main([str(tmp_path), "--ai"])
    captured = capsys.readouterr()
    assert result == 0
    assert "1. a.py:1: TODO: fix the thing" in captured.out
    assert "   AI: Fix the thing. (Medium)" in captured.out
    assert "Overall AI summary" in captured.out
    assert "One maintenance task." in captured.out
    assert "Priorities are estimated from comment text only." in captured.out
    assert "No source code was provided to the AI." in captured.out
    assert "sk-shell-secret" not in captured.out


def test_ai_failure_keeps_local_report(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from todoscope.openai_client import AiRequestError

    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    (tmp_path / "a.py").write_text("# TODO: fix the thing\n")
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-shell-secret")

    def failing_analyze(items, model, api_key, **kwargs):
        raise AiRequestError("boom")

    monkeypatch.setattr("todoscope.openai_client.analyze", failing_analyze)
    result = main([str(tmp_path), "--ai"])
    captured = capsys.readouterr()
    assert result == 0
    assert "TODO: fix the thing" in captured.out
    assert "AI analysis skipped: the AI request failed." in captured.out
    assert "Overall AI summary" not in captured.out
    assert "sk-shell-secret" not in captured.out
    assert "boom" not in captured.out


def test_confirmed_secondary_retry_merges_results(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from todoscope.ai import AnalysisItem, AnalysisResult
    from todoscope.openai_client import AiRequestError

    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    (tmp_path / "a.py").write_text("# TODO: fix the thing\n")
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-primary")
    monkeypatch.setenv("TODOSCOPE_SECONDARY_API_KEY", "sk-secondary")
    calls: list[tuple[str, str]] = []

    def fake_analyze(items, model, api_key, **kwargs):
        calls.append((model, api_key))
        if api_key == "sk-primary":
            raise AiRequestError("primary down")
        return AnalysisResult(
            items=(
                AnalysisItem(id=1, interpretation="Via secondary.", priority="High"),
            ),
            overview="Summary from secondary.",
        )

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    result = main(
        [str(tmp_path), "--ai"],
        interactive=True,
        confirm_secondary=lambda: True,
        status=None,
    )
    captured = capsys.readouterr()
    assert result == 0
    assert calls == [("m", "sk-primary"), ("m", "sk-secondary")]
    assert "   AI: Via secondary. (High)" in captured.out
    assert "Summary from secondary." in captured.out
    assert "AI analysis skipped" not in captured.out


def test_declined_secondary_keeps_local_report(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from todoscope.openai_client import AiRequestError

    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    (tmp_path / "a.py").write_text("# TODO: fix the thing\n")
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-primary")
    monkeypatch.setenv("TODOSCOPE_SECONDARY_API_KEY", "sk-secondary")
    calls: list[str] = []

    def fake_analyze(items, model, api_key, **kwargs):
        calls.append(api_key)
        raise AiRequestError("down")

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    result = main(
        [str(tmp_path), "--ai"],
        interactive=True,
        confirm_secondary=lambda: False,
        status=None,
    )
    captured = capsys.readouterr()
    assert result == 0
    assert calls == ["sk-primary"]
    assert "TODO: fix the thing" in captured.out
    assert "AI analysis skipped: the AI request failed." in captured.out


def test_non_interactive_secondary_explanation(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from todoscope.openai_client import AiRequestError

    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    (tmp_path / "a.py").write_text("# TODO: fix the thing\n")
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-primary")
    monkeypatch.setenv("TODOSCOPE_SECONDARY_API_KEY", "sk-secondary")
    calls: list[str] = []

    def fake_analyze(items, model, api_key, **kwargs):
        calls.append(api_key)
        raise AiRequestError("down")

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    result = main([str(tmp_path), "--ai"], interactive=False, status=None)
    captured = capsys.readouterr()
    assert result == 0
    assert calls == ["sk-primary"]
    assert "TODO: fix the thing" in captured.out
    assert (
        "Secondary-key confirmation was skipped in non-interactive mode."
        in captured.out
    )


def test_secondary_failure_keeps_local_report(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from todoscope.openai_client import AiRequestError

    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    (tmp_path / "a.py").write_text("# TODO: fix the thing\n")
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-primary")
    monkeypatch.setenv("TODOSCOPE_SECONDARY_API_KEY", "sk-secondary")

    def fake_analyze(items, model, api_key, **kwargs):
        raise AiRequestError("down")

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    result = main(
        [str(tmp_path), "--ai"],
        interactive=True,
        confirm_secondary=lambda: True,
        status=None,
    )
    captured = capsys.readouterr()
    assert result == 0
    assert "TODO: fix the thing" in captured.out
    assert "AI analysis skipped: the secondary AI request failed." in captured.out
