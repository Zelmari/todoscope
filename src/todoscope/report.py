"""Report formatting (MS-6/8/12): standard, quiet, verbose, AI-merged, JSON."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path
from typing import Any

from todoscope.ai import AnalysisResult
from todoscope.config import Config
from todoscope.discovery import ScanStats
from todoscope.scan import IndexedFinding

AI_SKIPPED_NO_KEY = "AI analysis skipped: no API key was configured."
AI_SKIPPED_NO_MODEL = "AI analysis skipped: no model was configured."
AI_SKIPPED_NO_AI_FLAG = "AI analysis skipped: --no-ai was used."
AI_SKIPPED_UNSAFE_ENV = (
    "AI analysis skipped: the API key would be loaded from a .env file that "
    "is not ignored by .gitignore."
)
AI_SKIPPED_REQUEST_FAILED = "AI analysis skipped: the AI request failed."
AI_SKIPPED_NONINTERACTIVE = (
    "AI analysis skipped: the AI request failed. Secondary-key confirmation "
    "was skipped in non-interactive mode."
)
AI_SKIPPED_SECONDARY_FAILED = "AI analysis skipped: the secondary AI request failed."

DISCLAIMER_LINES = (
    "Priorities are estimated from comment text only.",
    "No source code was provided to the AI.",
)


def payload_too_large_message(config: Config) -> str:
    """Overarching 22 message; local findings remain displayed above it."""
    return "\n".join(
        [
            "AI analysis skipped.",
            "",
            f"The extracted {marker_label(config)} exceed the maximum AI payload size.",
            "Scan a narrower file or directory.",
        ]
    )


def marker_label(config: Config) -> str:
    """Plural label for the configured markers, e.g. 'TODO comments'."""
    if not config.markers:
        return "comments"
    if config.markers == ("TODO",):
        return "TODO comments"
    return f"{', '.join(config.markers)} comments"


def _singular(label: str) -> str:
    return label.removesuffix("s")


def scan_header(files_scanned: int, target: str, count: int, config: Config) -> str:
    label = marker_label(config)
    files_word = "file" if files_scanned == 1 else "files"
    if count == 0:
        return f"Scanned {files_scanned} {files_word} in '{target}'."
    comment_word = _singular(label) if count == 1 else label
    return (
        f"Scanned {files_scanned} {files_word} in '{target}' "
        f"and found {count} {comment_word}."
    )


def no_findings_line(config: Config) -> str:
    return f"No {marker_label(config)} were found."


def _finding_lines(indexed: IndexedFinding) -> list[str]:
    finding = indexed.finding
    if finding.text:
        return [
            f"{indexed.id}. {finding.path}:{finding.line}",
            f"   {finding.marker}: {finding.text}",
        ]
    return [
        f"{indexed.id}. {finding.path}:{finding.line}",
        f"   {finding.marker}",
    ]


def standard_report(
    findings: tuple[IndexedFinding, ...],
    files_scanned: int,
    target: str,
    config: Config,
    ai_skip_line: str | None,
    ai_result: AnalysisResult | None = None,
) -> str:
    """Complete human-readable report, printed once (Overarching 17/21)."""
    lines = [scan_header(files_scanned, target, len(findings), config)]
    if not findings:
        lines.append(no_findings_line(config))
        return "\n".join(lines)

    lines.append("")
    lines.append(marker_label(config))
    lines.append("")
    ai_by_id = {item.id: item for item in ai_result.items} if ai_result else {}
    for indexed in findings:
        lines.extend(_finding_lines(indexed))
        item = ai_by_id.get(indexed.id)
        if item is not None:
            lines.append("")
            lines.append(f"   AI interpretation: {item.interpretation}")
            lines.append(f"   Estimated priority: {item.priority}")
        lines.append("")
    if ai_result is not None:
        lines.append("Overall AI summary")
        lines.append("")
        lines.append(ai_result.overview)
        lines.append("")
        lines.extend(DISCLAIMER_LINES)
    elif ai_skip_line is not None:
        lines.append(ai_skip_line)
    return "\n".join(lines)


def quiet_report(findings: tuple[IndexedFinding, ...]) -> str:
    """One finding per line, no headings or summaries (Overarching 28)."""
    lines: list[str] = []
    for indexed in findings:
        finding = indexed.finding
        suffix = f": {finding.text}" if finding.text else ""
        lines.append(f"{finding.path}:{finding.line}: {finding.marker}{suffix}")
    return "\n".join(lines)


def json_report(
    findings: tuple[IndexedFinding, ...],
    files_scanned: int,
    target: str,
    project_root: Path,
    config: Config,
    stats: ScanStats,
    ai_result: AnalysisResult | None = None,
    ai_status: str | None = None,
    ai_reason: str | None = None,
) -> dict[str, Any]:
    """Deterministic JSON report for agents (Overarching 31, MS-12).

    Never contains API keys or environment values.
    """
    ai_section: dict[str, Any] | None = None
    if ai_result is not None:
        ai_section = {
            "status": "completed",
            "items": [
                {
                    "id": item.id,
                    "interpretation": item.interpretation,
                    "priority": item.priority,
                }
                for item in ai_result.items
            ],
            "overview": ai_result.overview,
            "disclaimer": list(DISCLAIMER_LINES),
        }
    elif ai_status is not None:
        ai_section = {"status": ai_status}
        if ai_reason is not None:
            ai_section["reason"] = ai_reason

    return {
        "tool": "todoscope",
        "version": version("todoscope"),
        "target": target,
        "project_root": str(project_root),
        "files_scanned": files_scanned,
        "markers": list(config.markers),
        "findings_count": len(findings),
        "findings": [
            {
                "id": indexed.id,
                "marker": indexed.finding.marker,
                "text": indexed.finding.text,
                "path": indexed.finding.path,
                "line": indexed.finding.line,
            }
            for indexed in findings
        ],
        "skipped": {
            "ignored_by_gitignore": stats.ignored_by_gitignore,
            "ignored_by_config": stats.ignored_by_config,
            "unsupported": stats.unsupported,
            "unreadable": stats.unreadable,
            "symlinks": stats.symlinks,
        },
        "ai": ai_section,
    }


def verbose_report(
    target: str,
    project_root: Path,
    config: Config,
    stats: ScanStats,
    duration_seconds: float,
    gitignore_path: Path | None,
    *,
    secondary_key_configured: bool = False,
    ai_payload_characters: int | None = None,
) -> str:
    """Extra scan details; written to stderr, never contains secrets."""
    config_used = str(config.path) if config.path is not None else "(defaults)"
    gitignore = str(gitignore_path) if gitignore_path is not None else "(none)"
    model = config.model if config.model is not None else "(not configured)"
    payload = (
        str(ai_payload_characters)
        if ai_payload_characters is not None
        else "(no AI request)"
    )
    return "\n".join(
        [
            f"Configuration file: {config_used}",
            f"Project root: {project_root}",
            f".gitignore: {gitignore}",
            f"Excluded by .gitignore: {stats.ignored_by_gitignore}",
            f"Excluded by configuration: {stats.ignored_by_config}",
            f"Unsupported files: {stats.unsupported}",
            f"Unreadable files: {stats.unreadable}",
            f"Symlinks skipped: {stats.symlinks}",
            f"Scan duration: {duration_seconds:.3f}s",
            f"Configured model: {model}",
            (
                "Secondary API key configured: "
                f"{'yes' if secondary_key_configured else 'no'}"
            ),
            f"AI payload characters: {payload}",
        ]
    )
