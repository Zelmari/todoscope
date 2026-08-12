"""CLI smoke tests for the Milestone 1 foundation."""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import version

import pytest

from todoscope.cli import PROG, build_parser, main


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
    assert "1. a.py:1" in captured.out
    assert "TODO: fix me" in captured.out


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
    assert captured.out == "a.py:1: TODO: one\nb.py:1: TODO: two\n"


def test_no_ai_flag_keeps_report_and_names_reason(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.py").write_text("# TODO: one\n")
    result = main([str(tmp_path), "--no-ai"])
    captured = capsys.readouterr()
    assert result == 0
    assert "AI analysis skipped: --no-ai was used." in captured.out


def test_default_skip_line_names_missing_model(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.py").write_text("# TODO: one\n")
    result = main([str(tmp_path)])
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


def test_explicit_ignored_target_interactive_confirm(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".gitignore").write_text("generated/\n")
    gen = tmp_path / "generated"
    gen.mkdir()
    (gen / "x.py").write_text("# TODO\n")
    confirmations: list[tuple[str, str]] = []

    def confirm(relative: str, source: str, ai_enabled: bool) -> bool:
        confirmations.append((relative, source))
        return True

    result = main([str(gen)], interactive=True, confirm=confirm)
    captured = capsys.readouterr()
    assert result == 0
    assert confirmations == [("generated", "gitignore")]
    assert "x.py" in captured.out


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
    result = main([str(tmp_path)])
    captured = capsys.readouterr()
    assert result == 0
    assert "TODO: one" in captured.out
    assert "not ignored by .gitignore" in captured.out
    assert "sk-env-secret" not in captured.out
    assert "sk-env-secret" not in captured.err


def test_shell_key_with_ignored_env_file_is_eligible(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    (tmp_path / "a.py").write_text("# TODO: one\n")
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-shell-secret")
    result = main([str(tmp_path)])
    captured = capsys.readouterr()
    assert result == 0
    assert "TODO: one" in captured.out
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
    result = main([str(tmp_path)])
    captured = capsys.readouterr()
    assert result == 0
    assert "TODO: this comment is far too long" in captured.out
    assert "exceed the maximum AI payload size" in captured.out
    assert "sk-shell-secret" not in captured.out
