"""Scan orchestration (MS-6): discovery + extraction + sorting + IDs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from todoscope.config import Config
from todoscope.discovery import (
    DiscoveryResult,
    ScanStats,
    discover_files,
)
from todoscope.extraction import Finding, findings_for_file


@dataclass(frozen=True, slots=True)
class IndexedFinding:
    """A finding with its scan-local ID assigned after deterministic sorting."""

    id: int
    finding: Finding


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Deterministic order: directory depth, case-normalised path, line."""
    return sorted(
        findings,
        key=lambda f: (f.path.count("/"), f.path.casefold(), f.line),
    )


def scan_files(
    files: tuple[Path, ...], project_root: Path, config: Config
) -> tuple[IndexedFinding, ...]:
    """Extract findings from permitted files, sort them, and assign IDs."""
    findings: list[Finding] = []
    for path in files:
        findings.extend(findings_for_file(path, project_root, config.markers))
    ordered = sort_findings(findings)
    return tuple(
        IndexedFinding(id=index, finding=finding)
        for index, finding in enumerate(ordered, start=1)
    )


def scan(
    target: Path,
    project_root: Path,
    config: Config,
    *,
    spec=None,
    override=None,
) -> tuple[tuple[IndexedFinding, ...], ScanStats]:
    """Run the full local scan and return indexed findings plus stats."""
    result: DiscoveryResult = discover_files(
        target, project_root, config, spec=spec, override=override
    )
    findings = scan_files(result.files, project_root, config)
    return findings, result.stats
