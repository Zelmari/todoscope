"""Report formatting (MS-6/8/12): standard, quiet, verbose, AI-merged, JSON."""

from __future__ import annotations

from datetime import date
from importlib.metadata import version
from pathlib import Path
from typing import Any

from todoscope.ai import AnalysisItem, AnalysisResult
from todoscope.blame import BlameInfo
from todoscope.config import Config
from todoscope.discovery import ScanStats
from todoscope.scan import IndexedFinding

AI_SKIPPED_NO_KEY = "AI analysis skipped: no API key was configured."
AI_SKIPPED_NO_MODEL = "AI analysis skipped: no model was configured."
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
AI_SKIPPED_SECRETS = (
    "AI analysis skipped: possible credentials were found in comments. "
    "Comment text is not sent to the AI when it may contain secrets."
)

QUIET_AI_CONFLICT = "--quiet and --ai cannot be used together."

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


def secrets_skip_line(secret_findings: tuple[IndexedFinding, ...]) -> str:
    """Skip message plus the canonical line of every suspicious finding."""
    lines = [AI_SKIPPED_SECRETS, ""]
    for indexed in secret_findings:
        finding = indexed.finding
        suffix = f": {finding.text}" if finding.text else ""
        lines.append(f"   {finding.path}:{finding.line}: {finding.marker}{suffix}")
    return "\n".join(lines)


def _finding_line(indexed: IndexedFinding) -> str:
    """The one canonical finding line used by every text mode."""
    finding = indexed.finding
    suffix = f": {finding.text}" if finding.text else ""
    return f"{indexed.id}. {finding.path}:{finding.line}: {finding.marker}{suffix}"


def _ai_detail_line(item: AnalysisItem) -> str:
    return f"   AI: {item.interpretation} ({item.priority})"


def blame_detail_line(info: BlameInfo | None) -> str:
    """Attribution line for a finding (blame data never enters the AI)."""
    if info is None:
        return "   Blame unavailable"
    if info.uncommitted:
        return "   Not yet committed"
    author = info.author or "Unknown"
    authored_date = info.date or "unknown date"
    return f"   Authored by {author} · {authored_date} · {info.commit[:7]}"


def age_detail_line(info: BlameInfo | None, *, today: date | None = None) -> str:
    """Describe time since the finding's current line was committed."""
    if info is None or (not info.uncommitted and not info.committed_date):
        return "   Age unavailable"
    if info.uncommitted:
        return "   Age: uncommitted"
    if today is None:
        today = date.today()
    committed = date.fromisoformat(info.committed_date)
    days = max((today - committed).days, 0)
    day_word = "day" if days == 1 else "days"
    return f"   Age: {days} {day_word} (committed {info.committed_date})"


def age_entry(info: BlameInfo | None, *, today: date | None = None) -> dict[str, Any]:
    if info is None or (not info.uncommitted and not info.committed_date):
        return {"status": "unavailable", "days": None, "committed": None}
    if info.uncommitted:
        return {"status": "uncommitted", "days": None, "committed": None}
    if today is None:
        today = date.today()
    committed = date.fromisoformat(info.committed_date)
    return {
        "status": "committed",
        "days": max((today - committed).days, 0),
        "committed": info.committed_date,
    }


def standard_report(
    findings: tuple[IndexedFinding, ...],
    files_scanned: int,
    target: str,
    config: Config,
    ai_skip_line: str | None,
    ai_result: AnalysisResult | None = None,
    blames: dict[str, dict[int, BlameInfo]] | None = None,
    ages: dict[str, dict[int, BlameInfo]] | None = None,
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
    blocks: list[str] = []
    for indexed in findings:
        block = [_finding_line(indexed)]
        if blames is not None:
            file_blames = blames.get(indexed.finding.path, {})
            block.append(blame_detail_line(file_blames.get(indexed.finding.line)))
        if ages is not None:
            file_ages = ages.get(indexed.finding.path, {})
            block.append(age_detail_line(file_ages.get(indexed.finding.line)))
        item = ai_by_id.get(indexed.id)
        if item is not None:
            block.append(_ai_detail_line(item))
        blocks.append("\n".join(block))
    lines.append("\n\n".join(blocks))
    if ai_result is not None:
        lines.append("")
        lines.append("Overall AI summary")
        lines.append("")
        lines.append(ai_result.overview)
        lines.append("")
        lines.extend(DISCLAIMER_LINES)
    elif ai_skip_line is not None:
        lines.append("")
        lines.append(ai_skip_line)
    return "\n".join(lines)


def quiet_report(findings: tuple[IndexedFinding, ...]) -> str:
    """One canonical finding line each, nothing else (Overarching 28)."""
    return "\n".join(_finding_line(indexed) for indexed in findings)


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
    blames: dict[str, dict[int, BlameInfo]] | None = None,
    ages: dict[str, dict[int, BlameInfo]] | None = None,
    age_filter: dict[str, Any] | None = None,
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

    def finding_entry(indexed: IndexedFinding) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "id": indexed.id,
            "marker": indexed.finding.marker,
            "text": indexed.finding.text,
            "path": indexed.finding.path,
            "line": indexed.finding.line,
        }
        if blames is not None:
            info = blames.get(indexed.finding.path, {}).get(indexed.finding.line)
            entry["blame"] = (
                {
                    "author": info.author,
                    "date": info.date,
                    "commit": info.commit,
                }
                if info is not None
                else None
            )
        if ages is not None:
            info = ages.get(indexed.finding.path, {}).get(indexed.finding.line)
            entry["age"] = age_entry(info)
        return entry

    return {
        "tool": "todoscope",
        "version": version("todoscope"),
        "target": target,
        "project_root": str(project_root),
        "files_scanned": files_scanned,
        "markers": list(config.markers),
        "findings_count": len(findings),
        "findings": [finding_entry(indexed) for indexed in findings],
        "skipped": {
            "ignored_by_gitignore": stats.ignored_by_gitignore,
            "ignored_by_config": stats.ignored_by_config,
            "unsupported": stats.unsupported,
            "unreadable": stats.unreadable,
            "symlinks": stats.symlinks,
        },
        "ai": ai_section,
    } | ({"age_filter": age_filter} if age_filter is not None else {})


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
    blame_files: int | None = None,
    blame_unavailable: int | None = None,
    blame_budget_exceeded: bool = False,
    age_filter_removed: int | None = None,
    serial_retried_chunks: int = 0,
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
    lines = [
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
    if blame_files is not None:
        lines.append(f"Files with blame: {blame_files}")
        lines.append(f"Blame unavailable: {blame_unavailable}")
        if blame_budget_exceeded:
            lines.append("Blame budget exceeded: yes")
    if age_filter_removed is not None:
        lines.append(f"Findings excluded by age filter: {age_filter_removed}")
    if serial_retried_chunks:
        lines.append(
            f"Chunks retried serially after worker crash: {serial_retried_chunks}"
        )
    return "\n".join(lines)
