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


def test_valid_directory_describes_target_and_config(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "src").mkdir()
    result = main([str(tmp_path / "src")])
    captured = capsys.readouterr()
    assert result == 0
    assert "Project root:" in captured.out
    assert "markers: TODO" in captured.out


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
