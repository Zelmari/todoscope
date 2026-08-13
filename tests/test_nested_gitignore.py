"""Nested .gitignore semantics tests (MS-14)."""

from __future__ import annotations

from todoscope.config import load_config
from todoscope.discovery import (
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


def test_nested_patterns_apply_only_to_their_subtree(tmp_path) -> None:
    write(tmp_path / "sub" / ".gitignore", "drop.py\n")
    write(tmp_path / "sub" / "drop.py")
    write(tmp_path / "sub" / "keep.py")
    write(tmp_path / "root_drop.py")
    result = discover_files(tmp_path, tmp_path, load_config(tmp_path))
    assert names(result, tmp_path) == ["root_drop.py", "sub/keep.py"]


def test_deeper_file_overrides_parent_decision(tmp_path) -> None:
    write(tmp_path / ".gitignore", "drop_*.py\n")
    write(tmp_path / "sub" / ".gitignore", "!keep_important.py\n")
    write(tmp_path / "drop_root.py")
    write(tmp_path / "sub" / "keep_important.py")
    write(tmp_path / "sub" / "drop_other.py")
    result = discover_files(tmp_path, tmp_path, load_config(tmp_path))
    assert names(result, tmp_path) == ["sub/keep_important.py"]


def test_deeper_file_can_reignore_parent_unignored_file(tmp_path) -> None:
    write(tmp_path / "sub" / ".gitignore", "gen.py\n")
    write(tmp_path / "sub" / "gen.py")
    write(tmp_path / "sub" / "ok.py")
    result = discover_files(tmp_path, tmp_path, load_config(tmp_path))
    assert names(result, tmp_path) == ["sub/ok.py"]


def test_parent_patterns_apply_to_deep_descendants(tmp_path) -> None:
    write(tmp_path / ".gitignore", "*.tmp\n")
    write(tmp_path / "a" / "b" / "c" / "drop.tmp")
    write(tmp_path / "a" / "b" / "c" / "keep.py")
    result = discover_files(tmp_path, tmp_path, load_config(tmp_path))
    assert names(result, tmp_path) == ["a/b/c/keep.py"]


def test_negation_cannot_reinclude_under_excluded_dir(tmp_path) -> None:
    write(tmp_path / ".gitignore", "vendor/\n")
    write(tmp_path / "vendor" / ".gitignore", "!keep.py\n")
    write(tmp_path / "vendor" / "keep.py")
    result = discover_files(tmp_path, tmp_path, load_config(tmp_path))
    assert result.files == ()


def test_deep_nested_patterns_and_scan_from_subdir(tmp_path) -> None:
    write(tmp_path / ".gitignore", "top.log\n")
    write(tmp_path / "src" / ".gitignore", "secret.py\n")
    write(tmp_path / "top.log")
    write(tmp_path / "src" / "secret.py")
    write(tmp_path / "src" / "open.py")
    result = discover_files(tmp_path / "src", tmp_path, load_config(tmp_path))
    assert names(result, tmp_path) == ["src/open.py"]


def test_explicit_target_ignored_by_nested_gitignore(tmp_path) -> None:
    write(tmp_path / "sub" / ".gitignore", "fixtures/\n")
    target = tmp_path / "sub" / "fixtures"
    write(target / "x.py")
    spec = load_gitignore_spec(tmp_path)
    error = check_ignored(target, tmp_path, load_config(tmp_path), spec=spec)
    assert error is not None
    assert error.source == GITIGNORE_SOURCE
    assert error.relative == "sub/fixtures"


def test_override_disables_only_blocking_rule(tmp_path) -> None:
    write(tmp_path / ".gitignore", "*.tmp\n")
    write(tmp_path / "sub" / ".gitignore", "gen/\n")
    target = tmp_path / "sub" / "gen"
    write(target / "keep.py")
    write(target / "drop.tmp")
    config = load_config(tmp_path)
    spec = load_gitignore_spec(tmp_path)
    override = build_override(target, tmp_path, config, spec=spec)
    result = discover_files(target, tmp_path, config, spec=spec, override=override)
    assert names(result, tmp_path) == ["sub/gen/keep.py"]


def test_override_keeps_independent_nested_rules(tmp_path) -> None:
    write(tmp_path / "sub" / ".gitignore", "gen/\n")
    write(tmp_path / ".todoscope.json", '{"exclude": ["sub/gen/archive/"]}')
    target = tmp_path / "sub" / "gen"
    write(target / "keep.py")
    write(target / "archive" / "old.py")
    config = load_config(tmp_path)
    spec = load_gitignore_spec(tmp_path)
    override = build_override(target, tmp_path, config, spec=spec)
    result = discover_files(target, tmp_path, config, spec=spec, override=override)
    assert names(result, tmp_path) == ["sub/gen/keep.py"]


def test_env_safety_check_uses_root_gitignore_only(tmp_path) -> None:
    from todoscope.keys import env_file_is_ignored

    write(tmp_path / "sub" / ".gitignore", ".env\n")
    assert env_file_is_ignored(tmp_path, load_gitignore_spec(tmp_path)) is False
    write(tmp_path / ".gitignore", ".env\n")
    assert env_file_is_ignored(tmp_path, load_gitignore_spec(tmp_path)) is True


def test_single_file_target_under_nested_rules(tmp_path) -> None:
    write(tmp_path / "sub" / ".gitignore", "drop.py\n")
    write(tmp_path / "sub" / "drop.py")
    write(tmp_path / "sub" / "keep.py")
    result = discover_files(
        tmp_path / "sub" / "keep.py", tmp_path, load_config(tmp_path)
    )
    assert names(result, tmp_path) == ["sub/keep.py"]
