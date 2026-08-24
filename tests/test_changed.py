"""Changed-file scanning tests (MS-25): --changed REF."""

from __future__ import annotations

import json
import subprocess

import pytest

from todoscope.changed import ChangedError, changed_files
from todoscope.cli import main
from todoscope.config import load_config
from todoscope.discovery import discover_files


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "alice@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Alice"], cwd=repo, check=True)
    (repo / "a.py").write_text("# TODO: a\n", encoding="utf-8")
    (repo / "b.py").write_text("# TODO: b\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "first"], cwd=repo, check=True)
    (repo / "d.py").write_text("# TODO: d\n", encoding="utf-8")
    subprocess.run(["git", "add", "d.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "second"], cwd=repo, check=True)
    (repo / "b.py").write_text("# TODO: b changed\n", encoding="utf-8")
    (repo / "c.py").write_text("# TODO: c untracked\n", encoding="utf-8")
    return repo


def test_changed_files_diffs_against_ref(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    assert changed_files(repo, "HEAD~1") == ("b.py", "d.py")
    assert changed_files(repo, "HEAD") == ("b.py",)


def test_changed_files_ignores_untracked_files(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    assert "c.py" not in changed_files(repo, "HEAD")


def test_changed_files_unknown_ref_raises(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    with pytest.raises(ChangedError, match="unknown ref"):
        changed_files(repo, "no-such-ref")


def test_changed_files_timeout_is_wrapped(tmp_path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 1.0)

    monkeypatch.setattr("todoscope.changed.subprocess.run", timeout)
    with pytest.raises(ChangedError, match="timed out"):
        changed_files(repo, "HEAD")


def test_discover_files_intersects_with_changed_set(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    result = discover_files(repo, repo, load_config(repo), changed={"b.py", "d.py"})
    assert [path.name for path in result.files] == ["b.py", "d.py"]
    assert result.stats.scanned == 2


def test_cli_changed_requires_git_repo(tmp_path, capsys) -> None:
    (tmp_path / "a.py").write_text("# TODO: x\n", encoding="utf-8")
    result = main([str(tmp_path), "--changed", "HEAD"])
    captured = capsys.readouterr()
    assert result == 2
    assert "--changed requires a Git repository" in captured.err


def test_cli_changed_unknown_ref_fails(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    result = main([str(repo), "--changed", "no-such-ref"])
    captured = capsys.readouterr()
    assert result == 2
    assert "unknown ref" in captured.err


def test_cli_changed_scans_only_changed_files(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    result = main([str(repo), "--changed", "HEAD~1"])
    captured = capsys.readouterr()
    assert result == 0
    assert "1. b.py:1: TODO: b changed" in captured.out
    assert "2. d.py:1: TODO: d" in captured.out
    assert "a.py" not in captured.out
    assert "c.py" not in captured.out
    assert "Scanned 2 files" in captured.out


def test_cli_changed_json_reports_ref(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    result = main([str(repo), "--changed", "HEAD", "--format", "json"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    assert data["changed_ref"] == "HEAD"
    assert data["files_scanned"] == 1
    assert data["findings"][0]["path"] == "b.py"


def test_cli_changed_composes_with_age(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    result = main([str(repo), "--changed", "HEAD~1", "--age"])
    captured = capsys.readouterr()
    assert result == 0
    assert "Age:" in captured.out
    assert "a.py" not in captured.out
