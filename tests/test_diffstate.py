"""New-findings diff tests (MS-34): --diff."""

from __future__ import annotations

import json

from todoscope.cli import main
from todoscope.diffstate import (
    diff_sets,
    finding_key,
    finding_keys,
    load_state,
    project_key,
    save_state,
    state_path,
)
from todoscope.extraction import Finding
from todoscope.scan import IndexedFinding


def _indexed() -> tuple[IndexedFinding, ...]:
    return (
        IndexedFinding(id=1, finding=Finding("TODO", "one", "a.py", 1)),
        IndexedFinding(id=2, finding=Finding("TODO", "two", "b.py", 2)),
    )


def test_finding_keys_are_sorted_and_stable() -> None:
    keys = finding_keys(_indexed())
    assert keys == ("a.py:1:TODO:one", "b.py:2:TODO:two")
    assert finding_key(_indexed()[0]) == "a.py:1:TODO:one"


def test_diff_sets_new_and_removed() -> None:
    current = ("a.py:1:TODO:one", "c.py:3:FIXME:three")
    new, removed = diff_sets({"a.py:1:TODO:one", "b.py:2:TODO:two"}, current)
    assert new == {"c.py:3:FIXME:three"}
    assert removed == {"b.py:2:TODO:two"}


def test_project_key_differs_across_roots(tmp_path) -> None:
    assert project_key(tmp_path / "repo-a") != project_key(tmp_path / "repo-b")


def test_state_roundtrip_and_prune(tmp_path) -> None:
    path = state_path(tmp_path)
    data = {}
    save_state(path, data)
    assert load_state(path) == {}
    data["k"] = {"findings": ["x"], "ts": 1}
    assert save_state(path, data) is True
    assert load_state(path) == {"k": {"findings": ["x"], "ts": 1}}
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{nope", encoding="utf-8")
    assert load_state(corrupt) == {}


def _write_project(tmp_path, lines: list[str]) -> None:
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "a.py").write_text("".join(lines), encoding="utf-8")


def test_first_diff_run_reports_all_new(tmp_path, capsys) -> None:
    _write_project(tmp_path, ["# TODO: one\n"])
    result = main([str(tmp_path / "src"), "--diff"])
    captured = capsys.readouterr()
    assert result == 0
    assert "New since last scan" in captured.out
    assert "1. a.py:1: TODO: one" in captured.out


def test_second_diff_run_reports_nothing_new(tmp_path, capsys) -> None:
    _write_project(tmp_path, ["# TODO: one\n"])
    main([str(tmp_path / "src"), "--diff"])
    capsys.readouterr()
    result = main([str(tmp_path / "src"), "--diff"])
    captured = capsys.readouterr()
    assert result == 0
    assert "No new findings." in captured.out
    assert "New since last scan" in captured.out


def test_diff_reports_only_the_new_finding(tmp_path, capsys) -> None:
    _write_project(tmp_path, ["# TODO: one\n"])
    main([str(tmp_path / "src"), "--diff"])
    capsys.readouterr()
    _write_project(tmp_path, ["# TODO: one\n", "# TODO: two\n"])
    result = main([str(tmp_path / "src"), "--diff"])
    captured = capsys.readouterr()
    assert result == 0
    section = captured.out.split("New since last scan")[1]
    assert "2. a.py:2: TODO: two" in section
    assert "1. a.py:1: TODO: one" not in section


def test_diff_reports_removed_findings(tmp_path, capsys) -> None:
    _write_project(tmp_path, ["# TODO: one\n", "# TODO: two\n"])
    main([str(tmp_path / "src"), "--diff"])
    capsys.readouterr()
    _write_project(tmp_path, ["# TODO: one\n"])
    result = main([str(tmp_path / "src"), "--diff"])
    captured = capsys.readouterr()
    assert result == 0
    assert "No new findings." in captured.out
    assert "1 previously seen finding disappeared" in captured.out


def test_quiet_diff_prints_only_new_lines(tmp_path, capsys) -> None:
    _write_project(tmp_path, ["# TODO: one\n"])
    main([str(tmp_path / "src"), "--diff"])
    capsys.readouterr()
    _write_project(tmp_path, ["# TODO: one\n", "# TODO: two\n"])
    result = main([str(tmp_path / "src"), "--quiet", "--diff"])
    captured = capsys.readouterr()
    assert result == 0
    assert "2. a.py:2: TODO: two" in captured.out
    assert "TODO: one" not in captured.out


def test_diff_json_shape(tmp_path, capsys) -> None:
    _write_project(tmp_path, ["# TODO: one\n"])
    main([str(tmp_path / "src"), "--diff"])
    capsys.readouterr()
    _write_project(tmp_path, ["# TODO: one\n", "# TODO: two\n"])
    result = main([str(tmp_path / "src"), "--diff", "--format", "json"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    assert data["diff"]["new_count"] == 1
    assert data["diff"]["new"][0]["text"] == "two"
    assert data["diff"]["removed_count"] == 0


def test_json_omits_diff_without_flag(tmp_path, capsys) -> None:
    _write_project(tmp_path, ["# TODO: one\n"])
    result = main([str(tmp_path / "src"), "--format", "json"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    assert "diff" not in data


def test_filters_do_not_affect_baseline(tmp_path, capsys) -> None:
    _write_project(tmp_path, ["# TODO: one\n"])
    main([str(tmp_path / "src"), "--diff"])
    capsys.readouterr()
    result = main([str(tmp_path / "src"), "--diff"])
    captured = capsys.readouterr()
    assert result == 0
    assert "No new findings." in captured.out


def test_diff_is_per_project(tmp_path, capsys) -> None:
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    for repo in (repo_a, repo_b):
        (repo / "src").mkdir(parents=True)
        (repo / "src" / "x.py").write_text("# TODO: shared\n", encoding="utf-8")
    main([str(repo_a / "src"), "--diff"])
    capsys.readouterr()
    result = main([str(repo_b / "src"), "--diff"])
    captured = capsys.readouterr()
    assert result == 0
    assert "1. x.py:1: TODO: shared" in captured.out


def test_gate_counts_unfiltered_scan(tmp_path, capsys) -> None:
    from todoscope.cli import FINDINGS_GATE_EXIT_CODE

    _write_project(tmp_path, ["# TODO: one\n"])
    result = main([str(tmp_path / "src"), "--diff", "--fail"])
    captured = capsys.readouterr()
    assert result == FINDINGS_GATE_EXIT_CODE
    assert "New since last scan" in captured.out
