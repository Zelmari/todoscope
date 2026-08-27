"""Pre-commit support tests (MS-32): --staged, install-hook, uninstall-hook."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from todoscope.changed import ChangedError, staged_files
from todoscope.cli import HOOK_MARKER, main


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "alice@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Alice"], cwd=repo, check=True)
    (repo / "a.py").write_text("# TODO: committed\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "first"], cwd=repo, check=True)
    return repo


def test_staged_files_lists_only_staged(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "b.py").write_text("# TODO: staged\n", encoding="utf-8")
    (repo / "a.py").write_text(
        "# TODO: committed\n# TODO: unstaged\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "b.py"], cwd=repo, check=True)
    assert staged_files(repo) == ("b.py",)


def test_staged_files_fails_without_repo(tmp_path) -> None:
    (tmp_path / "a.py").write_text("# TODO\n", encoding="utf-8")
    with pytest.raises(ChangedError):
        staged_files(tmp_path)


def test_cli_staged_scans_only_staged_files(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    (repo / "b.py").write_text("# TODO: staged\n", encoding="utf-8")
    (repo / "a.py").write_text(
        "# TODO: committed\n# TODO: unstaged\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "b.py"], cwd=repo, check=True)
    result = main([str(repo), "--staged"])
    captured = capsys.readouterr()
    assert result == 0
    assert "b.py:1: TODO: staged" in captured.out
    assert "unstaged" not in captured.out


def test_cli_staged_json_shape(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    (repo / "b.py").write_text("# TODO: staged\n", encoding="utf-8")
    subprocess.run(["git", "add", "b.py"], cwd=repo, check=True)
    result = main([str(repo), "--staged", "--format", "json"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    assert data["staged"] is True


def test_cli_staged_requires_git_repo(tmp_path, capsys) -> None:
    (tmp_path / "a.py").write_text("# TODO\n", encoding="utf-8")
    result = main([str(tmp_path), "--staged"])
    captured = capsys.readouterr()
    assert result == 2
    assert "--staged requires a Git repository" in captured.err


def test_staged_and_changed_conflict(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main([str(repo), "--staged", "--changed", "HEAD"])
    assert exc.value.code == 2


def test_install_hook_writes_executable_script(tmp_path, monkeypatch, capsys) -> None:
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)
    result = main(["--install-hook"])
    captured = capsys.readouterr()
    assert result == 0
    hook = repo / ".git" / "hooks" / "pre-commit"
    assert hook.exists()
    assert os.access(hook, os.X_OK)
    content = hook.read_text(encoding="utf-8")
    assert HOOK_MARKER in content
    assert "exec todoscope . --staged --quiet --fail" in content
    assert "Installed pre-commit hook" in captured.out


def test_install_hook_is_idempotent(tmp_path, monkeypatch, capsys) -> None:
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)
    assert main(["--install-hook"]) == 0
    capsys.readouterr()
    assert main(["--install-hook"]) == 0


def test_uninstall_hook_removes_only_our_hook(tmp_path, monkeypatch, capsys) -> None:
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)
    main(["--install-hook"])
    capsys.readouterr()
    result = main(["--uninstall-hook"])
    captured = capsys.readouterr()
    assert result == 0
    assert not (repo / ".git" / "hooks" / "pre-commit").exists()
    assert "Removed pre-commit hook" in captured.out


def test_uninstall_hook_refuses_foreign_hook(tmp_path, monkeypatch, capsys) -> None:
    repo = _make_repo(tmp_path)
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho custom\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    result = main(["--uninstall-hook"])
    captured = capsys.readouterr()
    assert result == 2
    assert "refusing to remove it" in captured.err
    assert hook.exists()


def test_uninstall_hook_without_install_reports_none(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)
    result = main(["--uninstall-hook"])
    captured = capsys.readouterr()
    assert result == 0
    assert "No todoscope pre-commit hook is installed." in captured.out


def test_install_hook_in_worktree(tmp_path, monkeypatch, capsys) -> None:
    repo = _make_repo(tmp_path)
    wt = tmp_path / "worktree"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(wt), "-b", "wt-branch"],
        cwd=repo,
        check=True,
    )
    monkeypatch.chdir(wt)
    result = main(["--install-hook"])
    captured = capsys.readouterr()
    assert result == 0
    assert "Installed pre-commit hook" in captured.out
    hook = repo / ".git" / "hooks" / "pre-commit"
    assert hook.exists()
    assert HOOK_MARKER in hook.read_text(encoding="utf-8")


def test_install_hook_outside_repo(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    result = main(["--install-hook"])
    captured = capsys.readouterr()
    assert result == 2
    assert "requires a Git repository" in captured.err


@pytest.mark.skipif(sys.platform == "win32", reason="hooks are POSIX shell scripts")
def test_hook_blocks_commits_with_staged_findings(tmp_path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)
    main(["--install-hook"])
    (repo / "b.py").write_text("# TODO: staged finding\n", encoding="utf-8")
    subprocess.run(["git", "add", "b.py"], cwd=repo, check=True)
    hook = repo / ".git" / "hooks" / "pre-commit"
    result = subprocess.run([str(hook)], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 4
    assert "b.py:1: TODO: staged finding" in result.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="hooks are POSIX shell scripts")
def test_hook_passes_without_staged_findings(tmp_path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)
    main(["--install-hook"])
    (repo / "b.py").write_text("print(1)\n", encoding="utf-8")
    subprocess.run(["git", "add", "b.py"], cwd=repo, check=True)
    hook = repo / ".git" / "hooks" / "pre-commit"
    result = subprocess.run([str(hook)], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0


def test_pre_commit_hooks_yaml_declares_hook() -> None:
    from pathlib import Path as P

    text = (P(__file__).parents[1] / ".pre-commit-hooks.yaml").read_text(
        encoding="utf-8"
    )
    assert "- id: todoscope" in text
    assert "entry: todoscope . --staged --quiet --fail" in text
    assert "language: system" in text
    assert "pass_filenames: false" in text
