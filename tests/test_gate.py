"""--fail / --fail-count gate tests (MS-30)."""

from __future__ import annotations

import json
import os
import subprocess

from todoscope.cli import FINDINGS_GATE_EXIT_CODE, main


def _write_project(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix me\n")


def test_fail_exits_four_with_findings(tmp_path, capsys) -> None:
    _write_project(tmp_path)
    result = main([str(tmp_path / "src"), "--fail"])
    captured = capsys.readouterr()
    assert result == FINDINGS_GATE_EXIT_CODE
    assert "1. a.py:1: TODO: fix me" in captured.out


def test_fail_exits_zero_without_findings(tmp_path, capsys) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print(1)\n")
    result = main([str(tmp_path / "src"), "--fail"])
    captured = capsys.readouterr()
    assert result == 0
    assert "No TODO comments were found" in captured.out


def test_fail_count_threshold(tmp_path, capsys) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: one\n# TODO: two\n# TODO: three\n")
    result = main([str(tmp_path / "src"), "--fail-count", "3"])
    capsys.readouterr()
    assert result == 0
    result = main([str(tmp_path / "src"), "--fail-count", "2"])
    capsys.readouterr()
    assert result == FINDINGS_GATE_EXIT_CODE


def test_fail_and_fail_count_are_mutually_exclusive(tmp_path, capsys) -> None:
    _write_project(tmp_path)
    with __import__("pytest").raises(SystemExit) as exc:
        main([str(tmp_path / "src"), "--fail", "--fail-count", "1"])
    assert exc.value.code == 2


def test_negative_fail_count_is_rejected(tmp_path, capsys) -> None:
    _write_project(tmp_path)
    result = main([str(tmp_path / "src"), "--fail-count", "-1"])
    captured = capsys.readouterr()
    assert result == 2
    assert "--fail-count must be a non-negative integer" in captured.err


def test_json_reports_gate(tmp_path, capsys) -> None:
    _write_project(tmp_path)
    result = main([str(tmp_path / "src"), "--fail", "--format", "json"])
    captured = capsys.readouterr()
    assert result == FINDINGS_GATE_EXIT_CODE
    data = json.loads(captured.out)
    assert data["gate"] == {
        "enabled": True,
        "threshold": None,
        "count": 1,
        "failed": True,
    }


def test_json_omits_gate_without_flags(tmp_path, capsys) -> None:
    _write_project(tmp_path)
    result = main([str(tmp_path / "src"), "--format", "json"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    assert "gate" not in data


def test_gate_counts_filtered_findings(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    result = main([str(repo), "--min-age", "1", "--fail"])
    captured = capsys.readouterr()
    assert result == 0
    assert "uncommitted" not in captured.out
    result = main([str(repo), "--fail"])
    captured = capsys.readouterr()
    assert result == FINDINGS_GATE_EXIT_CODE


def test_gate_applies_to_sarif_and_gha(tmp_path, capsys) -> None:
    _write_project(tmp_path)
    result = main([str(tmp_path / "src"), "--fail", "--format", "sarif"])
    capsys.readouterr()
    assert result == FINDINGS_GATE_EXIT_CODE
    result = main([str(tmp_path / "src"), "--fail", "--format", "github-actions"])
    capsys.readouterr()
    assert result == FINDINGS_GATE_EXIT_CODE


def test_quiet_gate_one_liner(tmp_path, capsys) -> None:
    _write_project(tmp_path)
    result = main([str(tmp_path / "src"), "--quiet", "--fail"])
    captured = capsys.readouterr()
    assert result == FINDINGS_GATE_EXIT_CODE
    assert "1. a.py:1: TODO: fix me" in captured.out


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "alice@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Alice"], cwd=repo, check=True)
    (repo / "a.py").write_text("print(1)\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=repo, check=True)
    env = {
        "GIT_AUTHOR_DATE": "2025-05-12T10:00:00Z",
        "GIT_COMMITTER_DATE": "2025-05-12T10:00:00Z",
    }
    subprocess.run(
        ["git", "commit", "-q", "-m", "first"],
        cwd=repo,
        env={**os.environ, **env},
        check=True,
    )
    (repo / "a.py").write_text("print(1)\n# TODO: uncommitted\n", encoding="utf-8")
    return repo
