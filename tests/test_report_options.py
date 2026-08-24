"""Report options tests (MS-37): --stats, --sort, --group-by."""

from __future__ import annotations

import json
import os
import subprocess

from todoscope.cli import main
from todoscope.extraction import Finding
from todoscope.report import group_findings, order_findings
from todoscope.scan import IndexedFinding


def _indexed() -> tuple[IndexedFinding, ...]:
    return (
        IndexedFinding(id=1, finding=Finding("TODO", "one", "src/z.py", 5)),
        IndexedFinding(id=2, finding=Finding("FIXME", "two", "a.py", 1)),
        IndexedFinding(id=3, finding=Finding("TODO", "three", "src/a.py", 3)),
    )


def test_stats_prints_only_summary(tmp_path, capsys) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: one\n")
    result = main([str(tmp_path / "src"), "--stats"])
    captured = capsys.readouterr()
    assert result == 0
    assert "Scanned 1 file in" in captured.out
    assert "found 1 TODO comment" in captured.out
    assert "TODO: one" not in captured.out


def test_stats_conflicts_with_quiet(tmp_path, capsys) -> None:
    with __import__("pytest").raises(SystemExit) as exc:
        main([str(tmp_path), "--stats", "--quiet"])
    assert exc.value.code == 2


def test_sort_path_orders_by_path(tmp_path, capsys) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "z.py").write_text("# TODO: z\n")
    (tmp_path / "src" / "a.py").write_text("# TODO: a\n")
    result = main([str(tmp_path / "src"), "--sort", "path"])
    captured = capsys.readouterr()
    assert result == 0
    assert captured.out.index("a.py") < captured.out.index("z.py")


def test_sort_line_keeps_scan_order(tmp_path, capsys) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "z.py").write_text("# TODO: z\n")
    (tmp_path / "src" / "a.py").write_text("# TODO: a\n")
    result = main([str(tmp_path / "src"), "--sort", "line"])
    captured = capsys.readouterr()
    assert result == 0
    assert captured.out.index("a.py") < captured.out.index("z.py")


def test_sort_priority_requires_ai(tmp_path, capsys) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: a\n")
    result = main([str(tmp_path / "src"), "--sort", "priority"])
    captured = capsys.readouterr()
    assert result == 2
    assert "--sort priority requires a completed AI analysis" in captured.err


def test_sort_priority_orders_high_first(tmp_path, monkeypatch, capsys) -> None:
    from todoscope.ai import AnalysisItem, AnalysisResult

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: low\n# TODO: high\n")
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-x")

    def fake_analyze(items, model, api_key, **kwargs):
        return AnalysisResult(
            items=(
                AnalysisItem(id=1, interpretation="x", priority="Low"),
                AnalysisItem(id=2, interpretation="x", priority="High"),
            ),
            overview="s",
        )

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    result = main([str(tmp_path / "src"), "--ai", "--sort", "priority"])
    captured = capsys.readouterr()
    assert result == 0
    assert captured.out.index("2. src/a.py:2") < captured.out.index("1. src/a.py:1")


def test_sort_age_requires_git(tmp_path, capsys) -> None:
    (tmp_path / "a.py").write_text("# TODO: x\n")
    result = main([str(tmp_path), "--sort", "age"])
    captured = capsys.readouterr()
    assert result == 2
    assert "--sort age requires a Git repository" in captured.err


def test_sort_age_orders_oldest_first(tmp_path, capsys) -> None:
    repo = _make_repo(tmp_path)
    result = main([str(repo), "--sort", "age"])
    captured = capsys.readouterr()
    assert result == 0
    lines = [
        line for line in captured.out.splitlines() if line.startswith(("1.", "2."))
    ]
    assert lines[0].startswith("1.") or lines[0].startswith("2.")
    assert captured.out.index("a.py:1") < captured.out.index("a.py:2")


def test_group_by_marker_sections(tmp_path, capsys) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: one\n# FIXME: two\n")
    (tmp_path / ".todoscope.json").write_text('{"markers": ["TODO", "FIXME"]}')
    result = main([str(tmp_path / "src"), "--group-by", "marker"])
    captured = capsys.readouterr()
    assert result == 0
    assert "TODO comments" in captured.out
    assert "FIXME comments" in captured.out
    assert captured.out.index("FIXME comments") < captured.out.index("TODO comments")


def test_group_by_directory_sections(tmp_path, capsys) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "deep").mkdir()
    (tmp_path / "src" / "deep" / "b.py").write_text("# TODO: b\n")
    (tmp_path / "src" / "a.py").write_text("# TODO: a\n")
    result = main([str(tmp_path / "src"), "--group-by", "directory"])
    captured = capsys.readouterr()
    assert result == 0
    assert captured.out.index(".") < captured.out.index("deep")


def test_group_by_rejected_with_quiet(tmp_path, capsys) -> None:
    with __import__("pytest").raises(SystemExit) as exc:
        main([str(tmp_path), "--quiet", "--group-by", "marker"])
    assert exc.value.code == 2


def test_json_order_is_unaffected_by_sort(tmp_path, capsys) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "z.py").write_text("# TODO: z\n")
    (tmp_path / "src" / "a.py").write_text("# TODO: a\n")
    result = main([str(tmp_path / "src"), "--sort", "path", "--format", "json"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    assert [f["path"] for f in data["findings"]] == ["a.py", "z.py"]


def test_order_findings_and_groups_are_deterministic() -> None:
    assert order_findings(_indexed(), "line") == _indexed()
    paths = [f.finding.path for f in order_findings(_indexed(), "path")]
    assert paths == ["a.py", "src/a.py", "src/z.py"]
    groups = group_findings(_indexed(), "marker")
    assert [key for key, _ in groups] == ["FIXME", "TODO"]
    dirs = group_findings(_indexed(), "directory")
    assert [key for key, _ in dirs] == [".", "src"]


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
        "# TODO: old\n# TODO: uncommitted\nprint(1)\n", encoding="utf-8"
    )
    return repo
