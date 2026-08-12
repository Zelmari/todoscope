"""Key loading and .env safety tests."""

from __future__ import annotations

import pathspec

from todoscope.keys import (
    ENV_FILENAME,
    PRIMARY_ENV_VAR,
    SECONDARY_ENV_VAR,
    env_file_is_ignored,
    load_keys,
    parse_dotenv,
)


def write_env(tmp_path, content: str) -> None:
    (tmp_path / ENV_FILENAME).write_text(content)


def test_parse_dotenv_basics() -> None:
    values = parse_dotenv(
        "# comment\n"
        "A=1\n"
        "B = 2\n"
        'C="three"\n'
        "D='four'\n"
        "export E=five\n"
        "no_equals_line\n"
        "F=\n"
    )
    assert values == {
        "A": "1",
        "B": "2",
        "C": "three",
        "D": "four",
        "E": "five",
        "F": "",
    }


def test_shell_environment_wins_over_env_file(tmp_path) -> None:
    write_env(tmp_path, f"{PRIMARY_ENV_VAR}=env-primary\n")
    keys = load_keys(tmp_path, None, environ={PRIMARY_ENV_VAR: "shell-primary"})
    assert keys.primary == "shell-primary"
    assert keys.primary_source == "shell"


def test_env_file_fills_missing_values_only(tmp_path) -> None:
    write_env(
        tmp_path,
        f"{PRIMARY_ENV_VAR}=env-primary\n{SECONDARY_ENV_VAR}=env-secondary\n",
    )
    keys = load_keys(tmp_path, None, environ={PRIMARY_ENV_VAR: "shell-primary"})
    assert keys.primary == "shell-primary"
    assert keys.secondary == "env-secondary"
    assert keys.secondary_source == "env_file"


def test_no_keys_without_env_or_shell(tmp_path) -> None:
    keys = load_keys(tmp_path, None, environ={})
    assert keys.primary is None
    assert keys.secondary is None
    assert keys.uses_env_file is False


def test_env_file_only_loads_keys(tmp_path) -> None:
    write_env(tmp_path, f"{PRIMARY_ENV_VAR}=p\n")
    keys = load_keys(tmp_path, None, environ={})
    assert keys.primary == "p"
    assert keys.primary_source == "env_file"
    assert keys.uses_env_file is True


def test_env_file_is_ignored_detection(tmp_path) -> None:
    spec = pathspec.GitIgnoreSpec.from_lines([".env\n"])
    assert env_file_is_ignored(tmp_path, spec) is True
    assert env_file_is_ignored(tmp_path, None) is False
    other = pathspec.GitIgnoreSpec.from_lines(["*.json\n"])
    assert env_file_is_ignored(tmp_path, other) is False


def test_missing_env_file_yields_no_keys(tmp_path) -> None:
    keys = load_keys(tmp_path, None, environ={})
    assert keys.primary is None
    assert keys.primary_source == "none"
