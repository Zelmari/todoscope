"""Report formatting (MS-6): standard, quiet, and verbose output."""

from __future__ import annotations

from pathlib import Path

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
) -> str:
    """Complete human-readable report, printed once (Overarching 17)."""
    lines = [scan_header(files_scanned, target, len(findings), config)]
    if findings:
        lines.append("")
        lines.append(marker_label(config))
        lines.append("")
        for indexed in findings:
            lines.extend(_finding_lines(indexed))
            lines.append("")
        if ai_skip_line is not None:
            lines.append(ai_skip_line)
    else:
        lines.append(no_findings_line(config))
    return "\n".join(lines)


def quiet_report(findings: tuple[IndexedFinding, ...]) -> str:
    """One finding per line, no headings or summaries (Overarching 28)."""
    lines: list[str] = []
    for indexed in findings:
        finding = indexed.finding
        suffix = f": {finding.text}" if finding.text else ""
        lines.append(f"{finding.path}:{finding.line}: {finding.marker}{suffix}")
    return "\n".join(lines)


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
