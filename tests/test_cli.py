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
