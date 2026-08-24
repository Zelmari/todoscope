"""SARIF 2.1.0 report generation (MS-23).

Converts findings, optional AI priorities, and optional history data into a
deterministic SARIF 2.1.0 document so CI pipelines can surface TodoScope
findings as code-scanning alerts. Like every other output, it never contains
API keys or environment values.
"""

from __future__ import annotations

from importlib.metadata import version
from typing import Any

from todoscope.ai import AnalysisResult
from todoscope.blame import BlameInfo
from todoscope.config import Config
from todoscope.report import age_entry
from todoscope.scan import IndexedFinding

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
INFORMATION_URI = "https://github.com/Zelmari/todoscope"

_PRIORITY_LEVELS: dict[str, str] = {
    "High": "error",
    "Medium": "warning",
    "Low": "note",
    "Unclear": "note",
}
DEFAULT_LEVEL = "warning"


def _rule(marker: str) -> dict[str, Any]:
    return {
        "id": marker,
        "name": f"{marker} comment",
        "shortDescription": {"text": f"Maintenance comment matching {marker}"},
    }


def _properties(
    indexed: IndexedFinding,
    ai_by_id: dict[int, Any],
    blames: dict[str, dict[int, BlameInfo]] | None,
    ages: dict[str, dict[int, BlameInfo]] | None,
) -> dict[str, Any]:
    props: dict[str, Any] = {"finding_id": indexed.id}
    item = ai_by_id.get(indexed.id)
    if item is not None:
        props["priority"] = item.priority
    if blames is not None:
        info = blames.get(indexed.finding.path, {}).get(indexed.finding.line)
        if info is not None and not info.uncommitted:
            props["blame"] = {
                "author": info.author,
                "date": info.date,
                "commit": info.commit,
            }
    if ages is not None:
        info = ages.get(indexed.finding.path, {}).get(indexed.finding.line)
        props["age"] = age_entry(info)
    return props


def sarif_report(
    findings: tuple[IndexedFinding, ...],
    config: Config,
    *,
    files_scanned: int,
    ai_result: AnalysisResult | None = None,
    blames: dict[str, dict[int, BlameInfo]] | None = None,
    ages: dict[str, dict[int, BlameInfo]] | None = None,
) -> dict[str, Any]:
    """Deterministic SARIF 2.1.0 document for the given findings."""
    ai_by_id = {item.id: item for item in ai_result.items} if ai_result else {}
    results: list[dict[str, Any]] = []
    for indexed in findings:
        finding = indexed.finding
        item = ai_by_id.get(indexed.id)
        level = (
            _PRIORITY_LEVELS.get(item.priority, DEFAULT_LEVEL)
            if item is not None
            else DEFAULT_LEVEL
        )
        message = (
            f"{finding.marker}: {finding.text}" if finding.text else finding.marker
        )
        results.append(
            {
                "ruleId": finding.marker,
                "level": level,
                "message": {"text": message},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": finding.path},
                            "region": {"startLine": finding.line},
                        }
                    }
                ],
                "properties": _properties(indexed, ai_by_id, blames, ages),
            }
        )
    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "todoscope",
                        "version": version("todoscope"),
                        "informationUri": INFORMATION_URI,
                        "rules": [_rule(marker) for marker in config.markers],
                    }
                },
                "results": results,
                "properties": {
                    "files_scanned": files_scanned,
                    "markers": list(config.markers),
                },
            }
        ],
    }
