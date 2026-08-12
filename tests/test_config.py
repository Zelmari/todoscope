"""Project-root discovery and configuration tests."""

from __future__ import annotations

import pytest

from todoscope.config import (
    DEFAULT_EXTENSIONS,
    DEFAULT_MARKERS,
    ConfigError,
    discover_project_root,
    load_config,
    parse_config_text,
)


def write(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_git_root_wins_inside_repository(tmp_path) -> None:
    write(tmp_path / ".git" / "HEAD", "")
    target = tmp_path / "src" / "deep" / "nested"
    write(target / "file.py", "")
    assert discover_project_root(target) == tmp_path


def test_git_root_wins_over_closer_config_marker(tmp_path) -> None:
    write(tmp_path / ".git" / "HEAD", "")
    write(tmp_path / "sub" / ".todoscope.json", "{}")
    target = tmp_path / "sub" / "deeper"
    write(target / "file.py", "")
    assert discover_project_root(target) == tmp_path


def test_non_git_root_from_todoscope_json(tmp_path) -> None:
    write(tmp_path / "sub" / ".todoscope.json", "{}")
    target = tmp_path / "sub" / "deeper"
    write(target / "file.py", "")
    assert discover_project_root(target) == tmp_path / "sub"


def test_non_git_root_from_gitignore(tmp_path) -> None:
    write(tmp_path / "sub" / ".gitignore", "")
    target = tmp_path / "sub" / "deeper"
    write(target / "file.py", "")
    assert discover_project_root(target) == tmp_path / "sub"


def test_fallback_to_requested_directory(tmp_path) -> None:
    target = tmp_path / "plain"
    target.mkdir()
    assert discover_project_root(target) == target


def test_fallback_to_file_parent(tmp_path) -> None:
    target = tmp_path / "plain" / "file.py"
    write(target, "")
    assert discover_project_root(target) == tmp_path / "plain"


def test_absent_config_returns_defaults(tmp_path) -> None:
    config = load_config(tmp_path)
    assert config.path is None
    assert config.markers == DEFAULT_MARKERS
    assert config.extensions == DEFAULT_EXTENSIONS
    assert config.exclude == ()
    assert config.model is None
    assert config.max_ai_characters is None


def test_valid_full_config(tmp_path) -> None:
    write(
        tmp_path / ".todoscope.json",
        """
{
  "markers": ["TODO", "FIXME", "HELP", "LATER"],
  "extensions": [".py", ".ts"],
  "exclude": ["tests/fixtures/", "generated/"],
  "model": "some-model",
  "max_ai_characters": 20000
}
""",
    )
    config = load_config(tmp_path)
    assert config.markers == ("TODO", "FIXME", "HELP", "LATER")
    assert config.extensions == (".py", ".ts")
    assert config.exclude == ("tests/fixtures/", "generated/")
    assert config.model == "some-model"
    assert config.max_ai_characters == 20000


def test_malformed_json_is_an_error(tmp_path) -> None:
    write(tmp_path / ".todoscope.json", "{not json")
    with pytest.raises(ConfigError, match="invalid JSON"):
        load_config(tmp_path)


def test_markers_not_a_list_is_an_error(tmp_path) -> None:
    write(tmp_path / ".todoscope.json", '{"markers": "TODO"}')
    with pytest.raises(ConfigError, match="'markers' must be a list"):
        load_config(tmp_path)


def test_empty_marker_is_an_error(tmp_path) -> None:
    write(tmp_path / ".todoscope.json", '{"markers": [""]}')
    with pytest.raises(ConfigError, match="empty marker"):
        load_config(tmp_path)


@pytest.mark.parametrize("marker", ["TO DO", "todo$", "TÖDO", "#TODO"])
def test_invalid_marker_characters_are_errors(tmp_path, marker: str) -> None:
    write(tmp_path / ".todoscope.json", f'{{"markers": ["{marker}"]}}')
    with pytest.raises(ConfigError, match="letters, numbers, underscores"):
        load_config(tmp_path)


def test_marker_with_hyphen_is_allowed(tmp_path) -> None:
    write(tmp_path / ".todoscope.json", '{"markers": ["TODO-NOW"]}')
    assert load_config(tmp_path).markers == ("TODO-NOW",)


def test_extensions_not_a_list_is_an_error(tmp_path) -> None:
    write(tmp_path / ".todoscope.json", '{"extensions": ".py"}')
    with pytest.raises(ConfigError, match="'extensions' must be a list"):
        load_config(tmp_path)


def test_unsupported_extension_is_an_error(tmp_path) -> None:
    write(tmp_path / ".todoscope.json", '{"extensions": [".java"]}')
    with pytest.raises(ConfigError, match="no supported parser"):
        load_config(tmp_path)


def test_exclude_not_a_list_is_an_error(tmp_path) -> None:
    write(tmp_path / ".todoscope.json", '{"exclude": "generated/"}')
    with pytest.raises(ConfigError, match="'exclude' must be a list"):
        load_config(tmp_path)


def test_empty_model_is_an_error(tmp_path) -> None:
    write(tmp_path / ".todoscope.json", '{"model": ""}')
    with pytest.raises(ConfigError, match="'model' must be a non-empty string"):
        load_config(tmp_path)


def test_non_string_model_is_an_error(tmp_path) -> None:
    write(tmp_path / ".todoscope.json", '{"model": 42}')
    with pytest.raises(ConfigError, match="'model' must be a non-empty string"):
        load_config(tmp_path)


def test_max_ai_characters_above_hard_ceiling_is_an_error(tmp_path) -> None:
    from todoscope.config import HARD_MAX_AI_CHARACTERS

    limit = HARD_MAX_AI_CHARACTERS + 1
    write(tmp_path / ".todoscope.json", f'{{"max_ai_characters": {limit}}}')
    with pytest.raises(ConfigError, match="hard ceiling"):
        load_config(tmp_path)


def test_max_ai_characters_must_be_positive_int(tmp_path) -> None:
    for bad in ('"big"', "0", "-5", "1.5", "true"):
        write(tmp_path / ".todoscope.json", f'{{"max_ai_characters": {bad}}}')
        with pytest.raises(ConfigError, match="positive integer"):
            load_config(tmp_path)


def test_unknown_key_is_an_error(tmp_path) -> None:
    write(tmp_path / ".todoscope.json", '{"marker": ["TODO"]}')
    with pytest.raises(ConfigError, match="Unknown configuration key"):
        load_config(tmp_path)


def test_parse_config_text_reports_filename(tmp_path) -> None:
    with pytest.raises(ConfigError, match=r"\.todoscope\.json contains invalid JSON"):
        parse_config_text("{", tmp_path / ".todoscope.json")
