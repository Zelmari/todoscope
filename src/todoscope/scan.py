"""Scan orchestration (MS-6/13): discovery + extraction + sorting + IDs.

Extraction runs in a process pool only when the workload is large enough to
beat process startup overhead (benchmarked: threads do not help; processes
scale ~2.4x on multi-megabyte workloads). Results are order-independent and
sorted after collection, so determinism is preserved.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from todoscope.config import Config
from todoscope.discovery import (
    DiscoveryResult,
    ScanStats,
    discover_files,
)
from todoscope.extraction import Finding, findings_for_file

PARALLEL_SIZE_THRESHOLD = 2_000_000
"""Total file bytes above which extraction uses a process pool."""

MAX_PARALLEL_WORKERS = 8


def _extract_worker(
    path: str, project_root: str, markers: tuple[str, ...]
) -> list[Finding]:
    """Module-level pool worker (picklable on every platform)."""
    return findings_for_file(Path(path), Path(project_root), markers)


def _total_bytes(files: tuple[Path, ...]) -> int:
    total = 0
    for path in files:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


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
    files: tuple[Path, ...],
    project_root: Path,
    config: Config,
    *,
    max_workers: int = MAX_PARALLEL_WORKERS,
    parallel: bool | None = None,
    size_threshold: int = PARALLEL_SIZE_THRESHOLD,
) -> tuple[IndexedFinding, ...]:
    """Extract findings from permitted files, sort them, and assign IDs.

    ``parallel`` may force or forbid the process pool; by default it is used
    only when more than one file and at least ``size_threshold`` total bytes
    are involved (process startup otherwise costs more than it saves).
    """
    if parallel is None:
        parallel = len(files) > 1 and _total_bytes(files) >= size_threshold

    if parallel:
        roots = (str(project_root),) * len(files)
        marker_sets = (config.markers,) * len(files)
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            batches = executor.map(
                _extract_worker, (str(p) for p in files), roots, marker_sets
            )
        extracted = [finding for batch in batches for finding in batch]
    else:
        extracted = [
            finding
            for path in files
            for finding in findings_for_file(path, project_root, config.markers)
        ]

    ordered = sort_findings(extracted)
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
