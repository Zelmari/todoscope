"""Scan orchestration (MS-6/13): discovery + extraction + sorting + IDs.

Extraction runs in a process pool only when the workload is large enough to
beat process startup overhead (benchmarked: threads do not help; processes
scale ~2.4x on multi-megabyte workloads). Files are submitted in bounded
chunks so huge repositories never queue everything at once, and a crashed
pool (BrokenProcessPool) falls back to serial extraction so a scan never
loses findings. Results are order-independent and sorted after collection,
so determinism is preserved.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
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
"""Total file bytes above which extraction may use a process pool.

Measured (2026-08-13, 32-core machine, warm cache): tiny (50 files) serial
wins; monorepo (2k files, ~5 MB) parallel 2.5x; many-small (5k files,
~10 MB) 3x; few-large (8 x 2 MB) parallel LOSES because chunk results with
~33k findings per file dominate the IPC cost.
"""

PARALLEL_MIN_FILES = 500
"""File-count floor for the pool: few big files (few-large) hurt in a pool,
many small ones win; the measured crossover sits between 50 and 2000 files,
so 500 is a conservative midpoint."""

MAX_PARALLEL_WORKERS = 8
"""Hard cap: benchmark plateau at 8 workers (16/32 flat or slower), and each
worker holds a Python runtime plus parser libraries."""

SUBMIT_CHUNK_SIZE = 200
"""Files submitted to the pool per chunk (backpressure on huge repos)."""


def _extract_chunk_worker(
    paths: list[str], project_root: str, markers: tuple[str, ...]
) -> list[Finding]:
    """Module-level chunk worker (picklable on every platform)."""
    root = Path(project_root)
    findings: list[Finding] = []
    for path in paths:
        findings.extend(findings_for_file(Path(path), root, markers))
    return findings


def _worker_count() -> int:
    """Pool size: never more than the machine's CPUs, capped at 8."""
    cpus = os.cpu_count() or 1
    return max(1, min(MAX_PARALLEL_WORKERS, cpus))


def _total_bytes(files: tuple[Path, ...]) -> int:
    total = 0
    for path in files:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def _extract_serial(
    files: tuple[Path, ...], project_root: Path, config: Config
) -> list[Finding]:
    return [
        finding
        for path in files
        for finding in findings_for_file(path, project_root, config.markers)
    ]


def _extract_parallel(
    files: tuple[Path, ...],
    project_root: Path,
    config: Config,
    workers: int,
    chunk_size: int,
) -> list[Finding]:
    """Chunked pool extraction with per-chunk retry.

    A crashed worker (BrokenProcessPool) fails only the chunks that never
    finished; those are re-run serially so findings are never lost. Results
    are reassembled in input order.
    """
    chunks = [
        [str(p) for p in files[i : i + chunk_size]]
        for i in range(0, len(files), chunk_size)
    ]
    results: list[list[Finding] | None] = [None] * len(chunks)

    try:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _extract_chunk_worker,
                    chunk,
                    str(project_root),
                    config.markers,
                ): index
                for index, chunk in enumerate(chunks)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except BrokenProcessPool:
                    results[index] = None
    except BrokenProcessPool:
        pass

    for index, chunk in enumerate(chunks):
        if results[index] is None:
            results[index] = _extract_chunk_worker(
                chunk, str(project_root), config.markers
            )
    return [finding for chunk in results if chunk for finding in chunk]


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
    max_workers: int | None = None,
    parallel: bool | None = None,
    size_threshold: int = PARALLEL_SIZE_THRESHOLD,
    chunk_size: int = SUBMIT_CHUNK_SIZE,
) -> tuple[IndexedFinding, ...]:
    """Extract findings from permitted files, sort them, and assign IDs.

    ``parallel`` may force or forbid the process pool; by default it is used
    only when the file count reaches PARALLEL_MIN_FILES and the total size
    reaches ``size_threshold`` (benchmark data: few big files lose in a
    pool, many small ones win). Crashed chunks retry serially so findings
    are never lost.
    """
    if parallel is None:
        parallel = (
            len(files) >= PARALLEL_MIN_FILES and _total_bytes(files) >= size_threshold
        )

    if parallel:
        workers = max_workers if max_workers is not None else _worker_count()
        try:
            extracted = _extract_parallel(
                files, project_root, config, workers, chunk_size
            )
        except BrokenProcessPool:
            extracted = _extract_serial(files, project_root, config)
    else:
        extracted = _extract_serial(files, project_root, config)

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
