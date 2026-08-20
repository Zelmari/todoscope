"""File discovery and exclusion engine tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from todoscope.config import ConfigError, load_config
from todoscope.discovery import (
    CONFIG_SOURCE,
    GITIGNORE_SOURCE,
    build_override,
    check_ignored,
    discover_files,
    load_gitignore_spec,
    relative_posix,
)


def write(path, content: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def names(result, root) -> list[str]:
    return [relative_posix(p, root) for p in result.files]


def test_single_file_input(tmp_path) -> None:
    target = write(tmp_path / "main.py")
    result = discover_files(target, tmp_path, load_config(tmp_path))
    assert names(result, tmp_path) == ["main.py"]
    assert result.stats.scanned == 1


def test_single_unsupported_file_is_skipped(tmp_path) -> None:
    target = write(tmp_path / "notes.md")
    result = discover_files(target, tmp_path, load_config(tmp_path))
    assert result.files == ()
    assert result.stats.unsupported == 1


def test_recursive_directory_scan(tmp_path) -> None:
    write(tmp_path / "main.py")
    write(tmp_path / "src" / "app.py")
    write(tmp_path / "src" / "deep" / "nested.ts")
    write(tmp_path / "readme.md")
    result = discover_files(tmp_path, tmp_path, load_config(tmp_path))
    assert names(result, tmp_path) == ["main.py", "src/app.py", "src/deep/nested.ts"]
    assert result.stats.unsupported == 1


def test_root_gitignore_excludes_files_and_dirs(tmp_path) -> None:
    write(tmp_path / ".gitignore", "generated/\n*.log\n")
    write(tmp_path / "keep.py")
    write(tmp_path / "skip.log")
    write(tmp_path / "generated" / "code.py")
    result = discover_files(tmp_path, tmp_path, load_config(tmp_path))
    assert names(result, tmp_path) == ["keep.py"]
    assert result.stats.ignored_by_gitignore == 2


def test_gitignore_negation_reincludes_file(tmp_path) -> None:
    write(tmp_path / ".gitignore", "*.py\n!important.py\n")
    write(tmp_path / "a.py")
    write(tmp_path / "important.py")
    result = discover_files(tmp_path, tmp_path, load_config(tmp_path))
    assert names(result, tmp_path) == ["important.py"]


def test_negation_cannot_reinclude_under_excluded_dir(tmp_path) -> None:
    write(tmp_path / ".gitignore", "generated/\n!generated/keep.py\n")
    write(tmp_path / "generated" / "keep.py")
    result = discover_files(tmp_path, tmp_path, load_config(tmp_path))
    assert result.files == ()


def test_nested_gitignore_is_applied(tmp_path) -> None:
    write(tmp_path / ".gitignore", "")
    write(tmp_path / "sub" / ".gitignore", "nested.py\n")
    write(tmp_path / "sub" / "nested.py")
    write(tmp_path / "sub" / "kept.py")
    result = discover_files(tmp_path, tmp_path, load_config(tmp_path))
    assert names(result, tmp_path) == ["sub/kept.py"]
    assert result.stats.ignored_by_gitignore == 1


def test_config_exclude_exact_file(tmp_path) -> None:
    write(tmp_path / ".todoscope.json", '{"exclude": ["src/legacy/example.py"]}')
    write(tmp_path / "src" / "legacy" / "example.py")
    write(tmp_path / "src" / "legacy" / "other.py")
    result = discover_files(tmp_path, tmp_path, load_config(tmp_path))
    assert names(result, tmp_path) == ["src/legacy/other.py"]
    assert result.stats.ignored_by_config == 1


def test_config_exclude_directory_prefix(tmp_path) -> None:
    write(tmp_path / ".todoscope.json", '{"exclude": ["generated/", "tests/fixtures"]}')
    write(tmp_path / "generated" / "a.py")
    write(tmp_path / "tests" / "fixtures" / "b.py")
    write(tmp_path / "tests" / "real_test.py")
    result = discover_files(tmp_path, tmp_path, load_config(tmp_path))
    assert names(result, tmp_path) == ["tests/real_test.py"]


def test_config_exclude_prefix_does_not_match_sibling_names(tmp_path) -> None:
    write(tmp_path / ".todoscope.json", '{"exclude": ["tests"]}')
    write(tmp_path / "tests_extra.py")
    write(tmp_path / "tests" / "a.py")
    result = discover_files(tmp_path, tmp_path, load_config(tmp_path))
    assert names(result, tmp_path) == ["tests_extra.py"]


def test_symlinked_files_and_dirs_are_skipped(tmp_path) -> None:
    write(tmp_path / "real.py")
    write(tmp_path / "real_subdir" / "x.py")
    os.symlink(tmp_path / "real.py", tmp_path / "link.py")
    os.symlink(tmp_path / "real_subdir", tmp_path / "linkdir")
    result = discover_files(tmp_path, tmp_path, load_config(tmp_path))
    assert names(result, tmp_path) == ["real.py", "real_subdir/x.py"]
    assert result.stats.symlinks == 2


def test_explicit_symlink_directory_is_not_scanned(tmp_path) -> None:
    outside = tmp_path / "outside"
    write(outside / "secret.py", "# TODO: outside\n")
    project = tmp_path / "project"
    project.mkdir()
    link = project / "linked"
    link.symlink_to(outside, target_is_directory=True)
    result = discover_files(link, project, load_config(project))
    assert result.files == ()
    assert result.stats.scanned == 0
    assert result.stats.symlinks == 1


def test_target_below_symlink_directory_is_not_scanned(tmp_path) -> None:
    outside = tmp_path / "outside"
    write(outside / "nested" / "secret.py", "# TODO: outside\n")
    project = tmp_path / "project"
    project.mkdir()
    link = project / "linked"
    link.symlink_to(outside, target_is_directory=True)
    target = link / "nested"
    result = discover_files(target, project, load_config(project))
    assert result.files == ()
    assert result.stats.symlinks == 1


def test_unreadable_gitignore_raises_config_error(tmp_path, monkeypatch) -> None:
    gitignore = write(tmp_path / ".gitignore", "generated/\n")
    real_read_text = Path.read_text

    def fail_gitignore(path, *args, **kwargs):
        if path == gitignore:
            raise PermissionError("denied")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_gitignore)
    with pytest.raises(ConfigError, match=r"Cannot read .*\.gitignore"):
        load_gitignore_spec(tmp_path)


def test_unreadable_nested_gitignore_aborts_discovery(tmp_path, monkeypatch) -> None:
    write(tmp_path / "keep.py")
    nested_gitignore = write(tmp_path / "nested" / ".gitignore", "*.py\n")
    write(tmp_path / "nested" / "secret.py")
    real_read_text = Path.read_text

    def fail_nested(path, *args, **kwargs):
        if path == nested_gitignore:
            raise PermissionError("denied")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_nested)
    with pytest.raises(ConfigError, match=r"Cannot read .*nested/\.gitignore"):
        discover_files(tmp_path, tmp_path, load_config(tmp_path))


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="chmod 000 does not make files unreadable on Windows",
)
def test_unreadable_file_is_skipped_and_counted(tmp_path) -> None:
    write(tmp_path / "secret.py")
    os.chmod(tmp_path / "secret.py", 0o000)
    write(tmp_path / "open.py")
    try:
        result = discover_files(tmp_path, tmp_path, load_config(tmp_path))
    finally:
        os.chmod(tmp_path / "secret.py", 0o644)
    assert names(result, tmp_path) == ["open.py"]
    assert result.stats.unreadable == 1


def test_explicit_ignored_file_is_detected(tmp_path) -> None:
    write(tmp_path / ".gitignore", "generated/\n")
    target = write(tmp_path / "generated" / "x.py")
    spec = load_gitignore_spec(tmp_path)
    error = check_ignored(target, tmp_path, load_config(tmp_path), spec=spec)
    assert error is not None
    assert error.relative == "generated/x.py"
    assert error.source == GITIGNORE_SOURCE


def test_explicit_ignored_directory_is_detected(tmp_path) -> None:
    write(tmp_path / ".gitignore", "generated/\n")
    target = tmp_path / "generated"
    write(target / "x.py")
    spec = load_gitignore_spec(tmp_path)
    error = check_ignored(target, tmp_path, load_config(tmp_path), spec=spec)
    assert error is not None
    assert error.relative == "generated"
    assert error.source == GITIGNORE_SOURCE


def test_explicit_config_excluded_target_is_detected(tmp_path) -> None:
    write(tmp_path / ".todoscope.json", '{"exclude": ["fixtures/"]}')
    target = tmp_path / "fixtures"
    write(target / "a.py")
    error = check_ignored(target, tmp_path, load_config(tmp_path))
    assert error is not None
    assert error.source == CONFIG_SOURCE


def test_plain_target_is_not_ignored(tmp_path) -> None:
    write(tmp_path / "x.py")
    assert check_ignored(tmp_path, tmp_path, load_config(tmp_path)) is None


def test_override_scans_confirmed_target_but_keeps_other_rules(tmp_path) -> None:
    write(tmp_path / ".gitignore", "generated/\n*.tmp\n")
    write(tmp_path / ".todoscope.json", '{"exclude": ["generated/archive/"]}')
    target = tmp_path / "generated"
    write(target / "keep.py")
    write(target / "drop.tmp")
    write(target / "archive" / "old.py")
    config = load_config(tmp_path)
    spec = load_gitignore_spec(tmp_path)
    override = build_override(target, tmp_path, config, spec=spec)
    result = discover_files(target, tmp_path, config, spec=spec, override=override)
    assert names(result, tmp_path) == ["generated/keep.py"]


def test_files_are_sorted_deterministically(tmp_path) -> None:
    write(tmp_path / "B.py")
    write(tmp_path / "a.py")
    write(tmp_path / "Z" / "x.py")
    result = discover_files(tmp_path, tmp_path, load_config(tmp_path))
    assert names(result, tmp_path) == ["a.py", "B.py", "Z/x.py"]
