"""Scan orchestration tests (MS-6): sorting and ID assignment."""

from __future__ import annotations

from todoscope.config import load_config
from todoscope.extraction import Finding
from todoscope.scan import scan_files, sort_findings


def test_sort_by_depth_then_casefold_path_then_line() -> None:
    findings = [
        Finding("TODO", "z", "src/deep/b.py", 1),
        Finding("TODO", "a", "main.py", 2),
        Finding("TODO", "b", "main.py", 1),
        Finding("TODO", "c", "src/app.py", 5),
        Finding("TODO", "d", "src/B.py", 5),
    ]
    ordered = sort_findings(findings)
    assert [(f.path, f.line) for f in ordered] == [
        ("main.py", 1),
        ("main.py", 2),
        ("src/app.py", 5),
        ("src/B.py", 5),
        ("src/deep/b.py", 1),
    ]


def test_scan_files_assigns_ids_in_sorted_order(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "b.py").write_text("# TODO: first\n")
    (tmp_path / "main.py").write_text("# TODO: second\n")
    files = tuple(sorted((tmp_path / "main.py", tmp_path / "src" / "b.py")))
    indexed, retried = scan_files(files, tmp_path, load_config(tmp_path))
    assert retried == 0
    assert [(i.id, i.finding.path) for i in indexed] == [
        (1, "main.py"),
        (2, "src/b.py"),
    ]
