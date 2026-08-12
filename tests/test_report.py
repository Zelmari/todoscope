"""Report formatting tests (MS-6)."""

from __future__ import annotations

from pathlib import Path

from todoscope.config import load_config
from todoscope.discovery import ScanStats
from todoscope.extraction import Finding
from todoscope.report import (
    AI_SKIPPED_NO_AI_FLAG,
    AI_SKIPPED_NO_KEY,
    AI_SKIPPED_NO_MODEL,
    marker_label,
    no_findings_line,
    quiet_report,
    scan_header,
    standard_report,
    verbose_report,
)
from todoscope.scan import IndexedFinding


def indexed(pairs) -> tuple[IndexedFinding, ...]:
    return tuple(
        IndexedFinding(
            id=i, finding=Finding(marker=marker, text=text, path=path, line=line)
        )
        for i, (path, line, marker, text) in enumerate(pairs, start=1)
    )


def test_scan_header_with_findings(tmp_path) -> None:
    config = load_config(tmp_path)
    assert (
        scan_header(47, "src/", 3, config)
        == "Scanned 47 files in 'src/' and found 3 TODO comments."
    )


def test_scan_header_singulars(tmp_path) -> None:
    config = load_config(tmp_path)
    assert (
        scan_header(1, "a.py", 1, config)
        == "Scanned 1 file in 'a.py' and found 1 TODO comment."
    )


def test_scan_header_without_findings(tmp_path) -> None:
    config = load_config(tmp_path)
    assert scan_header(47, "src/", 0, config) == "Scanned 47 files in 'src/'."


def test_no_findings_line(tmp_path) -> None:
    assert no_findings_line(load_config(tmp_path)) == "No TODO comments were found."


def test_marker_label_custom_markers(tmp_path) -> None:
    (tmp_path / ".todoscope.json").write_text('{"markers": ["TODO", "FIXME"]}')
    assert marker_label(load_config(tmp_path)) == "TODO, FIXME comments"


def test_standard_report_structure(tmp_path) -> None:
    config = load_config(tmp_path)
    findings = indexed(
        [("src/auth/session.py", 84, "TODO", "Handle expired refresh tokens")]
    )
    report = standard_report(findings, 47, "src/", config, AI_SKIPPED_NO_KEY)
    expected = (
        "Scanned 47 files in 'src/' and found 1 TODO comment.\n"
        "\n"
        "TODO comments\n"
        "\n"
        "1. src/auth/session.py:84\n"
        "   TODO: Handle expired refresh tokens\n"
        "\n"
        "AI analysis skipped: no API key was configured."
    )
    assert report == expected


def test_standard_report_no_findings(tmp_path) -> None:
    config = load_config(tmp_path)
    report = standard_report((), 47, "src/", config, AI_SKIPPED_NO_KEY)
    assert report == ("Scanned 47 files in 'src/'.\nNo TODO comments were found.")


def test_standard_report_empty_todo(tmp_path) -> None:
    config = load_config(tmp_path)
    findings = indexed([("a.py", 1, "TODO", "")])
    report = standard_report(findings, 1, "a.py", config, AI_SKIPPED_NO_AI_FLAG)
    assert "   TODO\n" in report
    assert AI_SKIPPED_NO_AI_FLAG in report


def test_quiet_report(tmp_path) -> None:
    findings = indexed(
        [
            ("src/auth/session.py", 84, "TODO", "Handle expired refresh tokens"),
            ("src/api/users.py", 41, "TODO", "Validate pagination limits"),
            ("a.py", 3, "TODO", ""),
        ]
    )
    assert quiet_report(findings) == (
        "src/auth/session.py:84: TODO: Handle expired refresh tokens\n"
        "src/api/users.py:41: TODO: Validate pagination limits\n"
        "a.py:3: TODO"
    )


def test_verbose_report_contains_details_but_no_secrets(tmp_path) -> None:
    config = load_config(tmp_path)
    stats = ScanStats(
        scanned=3,
        unsupported=2,
        ignored_by_gitignore=1,
        ignored_by_config=4,
        unreadable=1,
        symlinks=2,
    )
    report = verbose_report("src/", Path("/proj"), config, stats, 0.125, None)
    assert "Project root: /proj" in report
    assert "Excluded by .gitignore: 1" in report
    assert "Unsupported files: 2" in report
    assert "Unreadable files: 1" in report
    assert "Symlinks skipped: 2" in report
    assert "Scan duration: 0.125s" in report
    assert ".gitignore: (none)" in report
    assert "API" not in report
    assert "TODOSCOPE" not in report


def test_ai_skip_line_constants_are_distinct() -> None:
    assert AI_SKIPPED_NO_KEY != AI_SKIPPED_NO_MODEL != AI_SKIPPED_NO_AI_FLAG
