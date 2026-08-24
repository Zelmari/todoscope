"""Age-based filtering tests (MS-24): --min-age and --max-age."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import date

from todoscope.blame import BlameInfo, age_days, filter_by_age
from todoscope.cli import main
from todoscope.extraction import Finding
from todoscope.scan import IndexedFinding

COMMITTED = BlameInfo(
    commit="a1b2c3", author="Alice", date="", committed_date="2025-05-12"
)
UNCOMMITTED = BlameInfo(commit="0" * 40, author="", date="", committed_date="")


def indexed() -> tuple[IndexedFinding, ...]:
    return (
        IndexedFinding(id=1, finding=Finding("TODO", "old", "a.py", 1)),
        IndexedFinding(id=2, finding=Finding("TODO", "new", "a.py", 2)),
        IndexedFinding(id=3, finding=Finding("TODO", "unknown", "a.py", 3)),
    )


def blames() -> dict[str, dict[int, BlameInfo]]:
    return {
        "a.py": {
            1: COMMITTED,
            2: UNCOMMITTED,
            3: None,
        }
    }


def test_age_days_committed() -> None:
    today = date(2026, 8, 24)
    assert age_days(COMMITTED, today=today) == (today - date(2025, 5, 12)).days


def test_age_days_uncommitted_is_zero() -> None:
    assert age_days(UNCOMMITTED) == 0


def test_age_days_unavailable_is_none() -> None:
    assert age_days(None) is None
    no_history = BlameInfo(commit="x", author="", date="", committed_date="")
    assert age_days(no_history) is None


def test_filter_without_bounds_returns_all() -> None:
    assert filter_by_age(indexed(), blames(), min_age=None, max_age=None) == indexed()


def test_filter_min_age_keeps_only_old_enough() -> None:
    kept = filter_by_age(indexed(), blames(), min_age=30, max_age=None)
    assert [item.id for item in kept] == [1]


def test_filter_max_age_keeps_only_young_enough() -> None:
    kept = filter_by_age(indexed(), blames(), min_age=None, max_age=0)
    assert [item.id for item in kept] == [2]


def test_filter_bounds_drop_unavailable() -> None:
    kept = filter_by_age(indexed(), blames(), min_age=0, max_age=0)
    assert [item.id for item in kept] == [2]


def test_filter_requires_git_repo(tmp_path, capsys) -> None:
    (tmp_path / "a.py").write_text("# TODO: x\n", encoding="utf-8")
    result = main([str(tmp_path), "--min-age", "30"])
    captured = capsys.readouterr()
    assert result == 2
    assert "--min-age requires a Git repository" in captured.err


def test_quiet_min_age_conflict(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    result = main([str(repo), "--quiet", "--min-age", "30"])
    captured = capsys.readouterr()
    assert result == 0
    assert "--quiet and --min-age cannot be used together." in captured.err
    assert "a.py:1" in captured.out


def test_negative_age_is_rejected(tmp_path, capsys) -> None:
    result = main([str(tmp_path), "--min-age", "-1"])
    captured = capsys.readouterr()
    assert result == 2
    assert "--min-age must be a non-negative number of days" in captured.err


def test_cli_max_age_zero_keeps_only_uncommitted(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    result = main([str(repo), "--max-age", "0"])
    captured = capsys.readouterr()
    assert result == 0
    assert "2. a.py:2: TODO: new uncommitted" in captured.out
    assert "old" not in captured.out


def test_cli_min_age_keeps_only_committed(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    result = main([str(repo), "--min-age", "100"])
    captured = capsys.readouterr()
    assert result == 0
    assert "1. a.py:1: TODO: old" in captured.out
    assert "uncommitted" not in captured.out


def test_cli_json_reports_age_filter(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    result = main([str(repo), "--max-age", "0", "--format", "json"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    assert data["findings_count"] == 1
    assert data["age_filter"] == {"min_age": None, "max_age": 0, "removed": 1}


def test_ai_analyzes_only_filtered_findings(tmp_path, monkeypatch, capsys) -> None:
    from todoscope.ai import AnalysisItem, AnalysisResult

    repo = _make_repo(tmp_path)
    (repo / ".todoscope.json").write_text('{"model": "m"}')
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-x")
    captured_items: list = []

    def fake_analyze(items, model, api_key, **kwargs):
        captured_items.append(items)
        return AnalysisResult(
            items=tuple(
                AnalysisItem(id=item["id"], interpretation="x", priority="Low")
                for item in items
            ),
            overview="s",
        )

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    result = main([str(repo), "--ai", "--min-age", "100"])
    captured = capsys.readouterr()
    assert result == 0
    assert [item["id"] for item in captured_items[0]] == [1]
    assert "Overall AI summary" in captured.out


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "alice@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Alice"], cwd=repo, check=True)
    (repo / "a.py").write_text("# TODO: old\nprint(1)\n", encoding="utf-8")
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
    (repo / "a.py").write_text(
        "# TODO: old\n# TODO: new uncommitted\nprint(1)\n", encoding="utf-8"
    )
    return repo
