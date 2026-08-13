"""Parameter sweeps for the parallel engine (derives the shipped constants).

Three sweeps, each answering one question with data:

- ``crossover``: at which FILE COUNT does the pool start winning?
- ``bytefloor``: does a small total-byte workload still benefit from the
  pool once the file count qualifies (does the byte floor matter)?
- ``chunks``: which chunk size is best on a representative tree?

Usage (repo root):

    uv run python benchmarks/sweep.py --kind crossover
    uv run python benchmarks/sweep.py --kind bytefloor
    uv run python benchmarks/sweep.py --kind chunks
"""

from __future__ import annotations

import argparse
import csv
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from todoscope.config import load_config
from todoscope.discovery import discover_files
from todoscope.scan import scan_files

HERE = Path(__file__).resolve().parent
TREES = HERE / ".trees"
RESULTS = HERE / ".results"

RUNS = 5


def _generate(
    name: str, files: int, seed: int, fixed_size: int | None = None, max_depth: int = 4
) -> Path:
    tree = TREES / f"sweep-{name}"
    if not tree.exists():
        command = [
            "uv",
            "run",
            "python",
            "benchmarks/gen_tree.py",
            "--name",
            f"sweep-{name}",
            "--files",
            str(files),
            "--max-depth",
            str(max_depth),
            "--seed",
            str(seed),
        ]
        if fixed_size is not None:
            command += ["--fixed-size", str(fixed_size)]
        subprocess.run(command, check=True)
    return tree


def _measure(tree: Path, workers: int | None, chunk_size: int = 200) -> float:
    config = load_config(tree)
    files = discover_files(tree, tree, config).files
    kwargs = (
        {"parallel": False}
        if workers is None
        else {
            "parallel": True,
            "max_workers": workers,
            "chunk_size": chunk_size,
        }
    )
    scan_files(files, tree, config, **kwargs)  # warmup
    times = [
        _timed(lambda: scan_files(files, tree, config, **kwargs)) for _ in range(RUNS)
    ]
    return statistics.median(times)


def _timed(fn) -> float:
    started = time.perf_counter()
    fn()
    return time.perf_counter() - started


def sweep_crossover() -> None:
    rows = []
    for count in (100, 250, 500, 750, 1000, 1500, 2000):
        tree = _generate(f"count{count}", count, seed=count)
        serial = _measure(tree, None)
        parallel = _measure(tree, 8)
        rows.append(
            {
                "files": count,
                "serial_s": f"{serial:.4f}",
                "workers8_s": f"{parallel:.4f}",
                "speedup": f"{serial / parallel:.2f}",
            }
        )
        print(
            f"files={count:>5}: serial {serial:.4f}s  8w {parallel:.4f}s  "
            f"({serial / parallel:.2f}x)"
        )
    _save("crossover", rows)


def sweep_bytefloor() -> None:
    rows = []
    for fixed in (100, 500, 2000, 10000):
        total_kb = fixed * 1000 / 1024
        tree = _generate(f"size{fixed}", 1000, seed=fixed, fixed_size=fixed)
        serial = _measure(tree, None)
        parallel = _measure(tree, 8)
        rows.append(
            {
                "total_mb": round(total_kb / 1024, 3),
                "serial_s": f"{serial:.4f}",
                "workers8_s": f"{parallel:.4f}",
                "speedup": f"{serial / parallel:.2f}",
            }
        )
        print(
            f"size={total_kb / 1024:.2f} MiB (1000 files): serial "
            f"{serial:.4f}s  8w {parallel:.4f}s  ({serial / parallel:.2f}x)"
        )
    _save("bytefloor", rows)


def sweep_chunks() -> None:
    tree = _generate("chunks", 2000, seed=7)
    rows = []
    for chunk in (50, 100, 200, 500, 1000):
        median = _measure(tree, 8, chunk_size=chunk)
        rows.append({"chunk_size": chunk, "workers8_s": f"{median:.4f}"})
        print(f"chunk={chunk:>5}: 8w {median:.4f}s")
    _save("chunks", rows)


def _save(kind: str, rows: list[dict]) -> None:
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = RESULTS / f"sweep-{kind}-{stamp}.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"results: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind", required=True, choices=("crossover", "bytefloor", "chunks")
    )
    args = parser.parse_args()
    {
        "crossover": sweep_crossover,
        "bytefloor": sweep_bytefloor,
        "chunks": sweep_chunks,
    }[args.kind]()


if __name__ == "__main__":
    main()
