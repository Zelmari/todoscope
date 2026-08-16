"""Git blame tests: parser, integration, CLI, and privacy (MS-21)."""

from __future__ import annotations

import json
import subprocess
from datetime import date

from todoscope.blame import BlameError, blame_for_file, parse_porcelain
from todoscope.cli import main

PORCELAIN_SAMPLE = """\
abc123def4567890abcdef0123456789abcdef01 1 1 2
author Alice
author-time 1750000000
committer-time 1750003600
summary first change
filename a.py
	line one
	line two
0000000000000000000000000000000000000000 3 3 1
author Not Committed Yet
author-time 1750000100
committer-time 1750000100
	line three
"""


def test_parse_porcelain_groups_and_boundary() -> None:
    result = parse_porcelain(PORCELAIN_SAMPLE)
    assert result[1].author == "Alice"
    assert result[1].commit == "abc123def4567890abcdef0123456789abcdef01"
    assert result[1].date == "2025-06-15"
    assert result[1].committed_date == "2025-06-15"
    assert result[2].author == "Alice"
    assert result[3].uncommitted is True


def test_parse_porcelain_empty() -> None:
    assert parse_porcelain("") == {}


SAME_COMMIT_HUNKS = """\
abc123def4567890abcdef0123456789abcdef01 1 1 16
author Alice
author-time 1750000000
committer-time 1750003600
filename a.py
	line one
	line two
abc123def4567890abcdef0123456789abcdef01 3 3
	line three (same commit, no repeated attributes)
"""


def test_parse_porcelain_carries_attributes_across_hunks() -> None:
    result = parse_porcelain(SAME_COMMIT_HUNKS)
    assert result[1].author == "Alice"
    assert result[2].author == "Alice"
    assert result[3].author == "Alice"
    assert result[3].date == "2025-06-15"
    assert result[3].committed_date == "2025-06-15"


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
        env={**__import__("os").environ, **env},
        check=True,
    )
    (repo / "a.py").write_text(
        "# TODO: old\n# TODO: new uncommitted\nprint(1)\n", encoding="utf-8"
    )
    return repo


def test_blame_integration_with_real_repo(tmp_path) -> None:
    repo = _make_repo(tmp_path)
    result = blame_for_file(repo / "a.py")
    assert result[1].author == "Alice"
    assert result[1].date == "2025-05-12"
    assert result[1].committed_date == "2025-05-12"
    assert result[1].commit
    assert result[2].uncommitted is True


def test_blame_missing_file_raises_blame_error(tmp_path) -> None:
    try:
        blame_for_file(tmp_path / "nope.py")
    except BlameError:
        pass
    else:
        raise AssertionError("expected BlameError")


def test_cli_blame_lines(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    result = main([str(repo), "--blame"])
    captured = capsys.readouterr()
    assert result == 0
    assert "Authored by Alice · 2025-05-12 ·" in captured.out
    assert "Not yet committed" in captured.out


def test_cli_blame_json_shape(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    result = main([str(repo), "--blame", "--format", "json"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    first = data["findings"][0]
    assert first["blame"]["author"] == "Alice"
    assert first["blame"]["date"] == "2025-05-12"
    assert first["blame"]["commit"]
    second = data["findings"][1]
    assert second["blame"]["commit"] == "0" * 40


def test_cli_age_lines(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    result = main([str(repo), "--age"])
    captured = capsys.readouterr()
    expected_days = (date.today() - date(2025, 5, 12)).days
    assert result == 0
    assert f"Age: {expected_days} days (committed 2025-05-12)" in captured.out
    assert "Age: uncommitted" in captured.out
    assert "Authored by" not in captured.out


def test_cli_age_and_blame_share_output(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    result = main([str(repo), "--age", "--blame"])
    captured = capsys.readouterr()
    assert result == 0
    assert "Age:" in captured.out
    assert "Authored by Alice" in captured.out


def test_cli_age_json_shape(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    result = main([str(repo), "--age", "--format", "json"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    assert data["findings"][0]["age"] == {
        "status": "committed",
        "days": (date.today() - date(2025, 5, 12)).days,
        "committed": "2025-05-12",
    }
    assert data["findings"][1]["age"] == {
        "status": "uncommitted",
        "days": None,
        "committed": None,
    }


def test_cli_blame_requires_git_repo(tmp_path, capsys) -> None:
    (tmp_path / "a.py").write_text("# TODO: x\n", encoding="utf-8")
    result = main([str(tmp_path), "--blame"])
    captured = capsys.readouterr()
    assert result == 2
    assert "--blame requires a Git repository" in captured.err


def test_cli_age_requires_git_repo(tmp_path, capsys) -> None:
    (tmp_path / "a.py").write_text("# TODO: x\n", encoding="utf-8")
    result = main([str(tmp_path), "--age"])
    captured = capsys.readouterr()
    assert result == 2
    assert "--age requires a Git repository" in captured.err


def test_quiet_blame_conflict(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    result = main([str(repo), "--quiet", "--blame"])
    captured = capsys.readouterr()
    assert result == 0
    assert "--quiet and --blame cannot be used together." in captured.err
    assert "Authored by" not in captured.out


def test_quiet_age_conflict(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    result = main([str(repo), "--quiet", "--age"])
    captured = capsys.readouterr()
    assert result == 0
    assert "--quiet and --age cannot be used together." in captured.err
    assert "Age:" not in captured.out


def test_blame_data_never_enters_ai_payload(tmp_path, monkeypatch, capsys) -> None:
    from todoscope.ai import AnalysisItem, AnalysisResult

    repo = _make_repo(tmp_path)
    (repo / ".gitignore").write_text(".env\n")
    (repo / ".todoscope.json").write_text('{"model": "m"}')
    (repo / ".env").write_text("TODOSCOPE_API_KEY=sk-x\n")
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-x")
    captured_items: list = []

    def fake_analyze(items, model, api_key, **kwargs):
        captured_items.append(json.dumps(items))
        ids = [item["id"] for item in items]
        return AnalysisResult(
            items=tuple(
                AnalysisItem(id=i, interpretation="x", priority="Low") for i in ids
            ),
            overview="s",
        )

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    result = main([str(repo), "--ai", "--blame"])
    assert result == 0
    payload = captured_items[0]
    assert "Alice" not in payload
    assert "2025-05-12" not in payload
    assert '"author"' not in payload
    assert '"commit"' not in payload


def test_blame_failure_isolation(tmp_path, monkeypatch, capsys) -> None:
    repo = _make_repo(tmp_path)

    def failing(path, *args, **kwargs):
        raise BlameError("boom")

    monkeypatch.setattr("todoscope.cli.blame_for_file", failing)
    result = main([str(repo), "--blame"])
    captured = capsys.readouterr()
    assert result == 0
    assert "Blame unavailable" in captured.out
    assert "TODO: old" in captured.out


def test_age_failure_isolation(tmp_path, monkeypatch, capsys) -> None:
    repo = _make_repo(tmp_path)

    def failing(path, *args, **kwargs):
        raise BlameError("boom")

    monkeypatch.setattr("todoscope.cli.blame_for_file", failing)
    result = main([str(repo), "--age"])
    captured = capsys.readouterr()
    assert result == 0
    assert "Age unavailable" in captured.out


def test_blame_aggregate_budget_cutoff(tmp_path, monkeypatch, capsys) -> None:
    repo = _make_repo(tmp_path)
    monkeypatch.setattr("todoscope.cli.BLAME_TOTAL_BUDGET_SECONDS", 0.0)
    result = main([str(repo), "--blame", "--verbose"])
    captured = capsys.readouterr()
    assert result == 0
    assert "Blame unavailable" in captured.out
    assert "Files with blame: 0" in captured.err
    assert "Blame budget exceeded: yes" in captured.err
    assert "Authored by" not in captured.out
