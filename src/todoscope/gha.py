"""GitHub Actions workflow command output (MS-29).

Emits one ``::warning``/``::error``/``::notice`` workflow command per
finding so CI logs and pull request pages surface TodoScope results
inline. Property values and messages are escaped per the workflow-command
spec (``%``, CR, LF). Deterministic, and never contains API keys.
"""

from __future__ import annotations

from todoscope.ai import AnalysisResult
from todoscope.scan import IndexedFinding

_PRIORITY_COMMANDS: dict[str, str] = {
    "High": "error",
    "Medium": "warning",
    "Low": "notice",
    "Unclear": "notice",
}
DEFAULT_COMMAND = "warning"


def _escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def gha_report(
    findings: tuple[IndexedFinding, ...],
    ai_result: AnalysisResult | None = None,
) -> str:
    """One workflow command per finding, in report order."""
    ai_by_id = {item.id: item for item in ai_result.items} if ai_result else {}
    lines: list[str] = []
    for indexed in findings:
        finding = indexed.finding
        item = ai_by_id.get(indexed.id)
        command = (
            _PRIORITY_COMMANDS.get(item.priority, DEFAULT_COMMAND)
            if item is not None
            else DEFAULT_COMMAND
        )
        message = (
            f"{finding.marker}: {finding.text}" if finding.text else finding.marker
        )
        lines.append(
            f"::{command} file={_escape(finding.path)},line={finding.line},"
            f"endLine={finding.line},title={_escape(finding.marker)}::"
            f"{_escape(message)}"
        )
    return "\n".join(lines)
