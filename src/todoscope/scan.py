"""Scan orchestration (MS-6/13): discovery + extraction + sorting + IDs.

Extraction runs in a process pool only when the workload is large enough to
beat process startup overhead (benchmarked: threads do not help; processes
scale ~3.4x on many-file workloads). Submission is windowed: at most
2 x workers chunks are ever in flight, so huge repositories have a strictly
bounded queue. A crashed pool (BrokenProcessPool) retries only the
unfinished chunks serially, so findings are never lost. Results are
order-independent and sorted after collection, so determinism is preserved.
"""

from __future__ import annotations

import os
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ProcessPoolExecutor,
    wait,
)
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

Measured (2026-08-13, 32-core machine, all ten languages, warm cache; see
docs/BENCHMARKS.md): tiny (50 files) serial wins; monorepo (2k files,
~4 MiB) parallel 3.5x; many-small (5k files, ~11 MiB) 3.4x; few-large
(8 x 2 MB) parallel LOSES because chunk results with ~33k findings per file
dominate the IPC cost.
"""

PARALLEL_MIN_FILES = 500
"""File-count floor for the pool: few big files (few-large) hurt in a pool,
many small ones win; the measured crossover sits between 50 and 2000 files,
so 500 is a conservative midpoint."""

MAX_PARALLEL_WORKERS = 8
"""Hard cap: benchmark plateau at 8 workers (16 buys <=15% on some
workloads, 32 is flat or slower), and each worker holds a Python runtime
plus parser libraries."""

SUBMIT_CHUNK_SIZE = 200
"""Files per chunk; at most 2 x workers chunks are in flight at once
(windowed submission, strictly bounded queue)."""


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
    """Windowed pool extraction with per-chunk retry.

    At most ``2 * workers`` chunks are ever in flight: new chunks are
    submitted only as completed ones come back, so the queue stays strictly
    bounded regardless of repository size. A crashed worker
    (BrokenProcessPool) fails only the chunks that never finished; those
    are re-run serially so findings are never lost. Results are reassembled
    in input order.
    """
    chunks = [
        [str(p) for p in files[i : i + chunk_size]]
        for i in range(0, len(files), chunk_size)
    ]
    results: list[list[Finding] | None] = [None] * len(chunks)
    window = max(workers * 2, 1)

    try:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_to_index: dict[Future, int] = {}
            next_index = 0

            def submit_next() -> bool:
                nonlocal next_index
                if next_index >= len(chunks):
                    return False
                index = next_index
                next_index += 1
                future = executor.submit(
                    _extract_chunk_worker,
                    chunks[index],
                    str(project_root),
                    config.markers,
                )
                future_to_index[future] = index
                return True

            pending: set[Future] = set()
            while True:
                while len(pending) < window and submit_next():
                    pending.update(future_to_index)
                if not pending:
                    break
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    pending.remove(future)
                    index = future_to_index.pop(future)
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
