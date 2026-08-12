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
