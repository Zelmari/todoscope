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

PARALLEL_MIN_FILES = 500
"""Pool gate: the first file count at which the pool clearly wins.

Sweep-measured (docs/BENCHMARKS.md): 100 files lose (0.66x), 250 break
even (1.03x), 500 win 1.63x and improve monotonically after. A total-byte
floor proved unnecessary: at qualifying file counts the pool wins even for
100-byte files (1.28x at 500 x 100B, 2.33x at 1000 x 100B).
"""

MAX_PARALLEL_WORKERS = 8
"""Hard cap: benchmark plateau at 8 workers (16 buys <=15% on some
workloads, 32 is flat or slower), and each worker holds a Python runtime
plus parser libraries."""

SUBMIT_CHUNK_SIZE = 50
"""Files per chunk; sweep-measured (50 > 100 ~ 200 >> 500 >> 1000 on the
monorepo workload) with at most 2 x workers chunks in flight at once."""


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
) -> tuple[list[Finding], int]:
    """Windowed pool extraction with per-chunk retry.

    At most ``2 * workers`` chunks are ever in flight: new chunks are
    submitted only as completed ones come back, so the queue stays strictly
    bounded regardless of repository size. A crashed worker
    (BrokenProcessPool) fails only the chunks that never finished; those
    are re-run serially so findings are never lost, and the retried count
    is returned for verbose reporting. Results are reassembled in input
    order.
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

            def submit_next() -> Future | None:
                nonlocal next_index
                if next_index >= len(chunks):
                    return None
                index = next_index
                next_index += 1
                future = executor.submit(
                    _extract_chunk_worker,
                    chunks[index],
                    str(project_root),
                    config.markers,
                )
                future_to_index[future] = index
                return future

            pending: set[Future] = set()
            while True:
                while len(pending) < window:
                    future = submit_next()
                    if future is None:
                        break
                    pending.add(future)
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

    retried = sum(1 for chunk in results if chunk is None)
    for index, chunk in enumerate(chunks):
        if results[index] is None:
            results[index] = _extract_chunk_worker(
                chunk, str(project_root), config.markers
            )
    return [finding for chunk in results if chunk for finding in chunk], retried


@dataclass(frozen=True, slots=True)
class IndexedFinding:
    """A finding with its scan-local ID assigned after deterministic sorting."""

    id: int
    finding: Finding


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Deterministic order: directory depth, case-normalised path, line."""
    return sorted(
        findings,
        key=lambda f: (f.path.count("/"), f.path.casefold(), f.path, f.line),
    )


def scan_files(
    files: tuple[Path, ...],
    project_root: Path,
    config: Config,
    *,
    max_workers: int | None = None,
    parallel: bool | None = None,
    chunk_size: int = SUBMIT_CHUNK_SIZE,
) -> tuple[tuple[IndexedFinding, ...], int]:
    """Extract findings from permitted files, sort them, and assign IDs.

    ``parallel`` may force or forbid the process pool; by default it is
    used when the file count reaches PARALLEL_MIN_FILES (sweep-derived
    crossover; total bytes proved irrelevant once the count qualifies).
    Crashed chunks retry serially so findings are never lost; the returned
    retry count feeds verbose reporting.
    """
    if parallel is None:
        parallel = len(files) >= PARALLEL_MIN_FILES

    retried = 0
    if parallel:
        workers = max_workers if max_workers is not None else _worker_count()
        try:
            extracted, retried = _extract_parallel(
                files, project_root, config, workers, chunk_size
            )
        except BrokenProcessPool:
            extracted = _extract_serial(files, project_root, config)
    else:
        extracted = _extract_serial(files, project_root, config)

    ordered = sort_findings(extracted)
    indexed = tuple(
        IndexedFinding(id=index, finding=finding)
        for index, finding in enumerate(ordered, start=1)
    )
    return indexed, retried


def scan(
    target: Path,
    project_root: Path,
    config: Config,
    *,
    spec=None,
    override=None,
    changed: set[str] | None = None,
) -> tuple[tuple[IndexedFinding, ...], ScanStats]:
    """Run the full local scan and return indexed findings plus stats."""
    result: DiscoveryResult = discover_files(
        target,
        project_root,
        config,
        spec=spec,
        override=override,
        changed=changed,
    )
    findings, retried = scan_files(result.files, project_root, config)
    result.stats.serial_retry_chunks = retried
    return findings, result.stats
