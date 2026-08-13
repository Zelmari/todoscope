"""Benchmark todoscope's scan engine across workloads and worker counts.

Run from the repository root with the project environment:

    uv run python benchmarks/run.py --preset few-large

Reports median and min over 5 timed runs after a warmup, writes CSV plus a
machine-spec block to benchmarks/.results/, and can split discovery
(read/walk) from extraction (parse) timing.
"""

from __future__ import annotations

import argparse
import csv
import platform
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

PRESETS: dict[str, dict] = {
    "tiny": {"files": 50, "max_depth": 3, "seed": 1},
    "many-small": {"files": 5000, "max_depth": 6, "seed": 2},
    "few-large": {"files": 8, "max_depth": 1, "seed": 3, "fixed_size": 2_000_000},
    "monorepo": {"files": 2000, "max_depth": 5, "seed": 42},
}

WORKERS = (2, 4, 8, 16, 32)
RUNS = 5


def machine_spec() -> str:
    try:
        import os

        page = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
        ram = f"{page * pages / 1024**3:.1f} GiB"
    except (ImportError, ValueError, OSError):
        ram = "unknown"
    processor = platform.processor() or platform.machine()
    return "\n".join(
        [
            f"platform: {platform.platform()}",
            f"processor: {processor}",
            f"cpu_count: {__import__('os').cpu_count()}",
            f"ram: {ram}",
            f"python: {platform.python_version()}",
        ]
    )


def _tree_path(name: str) -> Path:
    return TREES / name


def _ensure_tree(name: str) -> Path:
    path = _tree_path(name)
    if not path.exists():
        preset = PRESETS[name]
        command = [
            "uv",
            "run",
            "python",
            "benchmarks/gen_tree.py",
            "--name",
            name,
            "--files",
            str(preset["files"]),
            "--max-depth",
            str(preset["max_depth"]),
            "--seed",
            str(preset["seed"]),
        ]
        if "fixed_size" in preset:
            command += ["--fixed-size", str(preset["fixed_size"])]
        subprocess.run(command, check=True)
    return path


def _timed(fn) -> float:
    started = time.perf_counter()
    fn()
    return time.perf_counter() - started


def run_benchmark(
    tree: Path,
    name: str,
    *,
    split: bool,
    workers: tuple[int, ...] = WORKERS,
) -> None:
    config = load_config(tree)

    discovery_times: list[float] = []
    files = None

    def discover():
        nonlocal files
        files = discover_files(tree, tree, config).files

    if split:
        _timed(discover)
        discovery_times = [_timed(discover) for _ in range(RUNS)]

    files = discover_files(tree, tree, config).files
    total_mb = sum(p.stat().st_size for p in files) / 1024 / 1024

    rows: list[dict] = []
    modes: list[tuple[str, dict]] = [("serial", {"parallel": False})]
    for count in workers:
        modes.append((f"workers={count}", {"parallel": True, "max_workers": count}))

    print(f"workload={name} files={len(files)} size={total_mb:.1f} MiB")
    print(machine_spec())
    print()

    for label, kwargs in modes:

        def run_scan(kwargs=kwargs):
            indexed, _ = scan_files(files, tree, config, **kwargs)
            return indexed

        _timed(run_scan)  # warmup
        times = [_timed(run_scan) for _ in range(RUNS)]
        median = statistics.median(times)
        best = min(times)
        rows.append(
            {
                "workload": name,
                "mode": label,
                "files": len(files),
                "size_mb": round(total_mb, 2),
                "median_s": f"{median:.4f}",
                "min_s": f"{best:.4f}",
            }
        )
        print(f"{label:>12}: median {median:.4f}s  min {best:.4f}s")

    if split:
        print(f"discovery only: median {statistics.median(discovery_times):.4f}s")

    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    csv_path = RESULTS / f"{name}-{stamp}.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    spec_path = RESULTS / f"{name}-{stamp}-machine.txt"
    spec_path.write_text(machine_spec() + "\n", encoding="utf-8")
    print(f"\nresults: {csv_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", choices=sorted(PRESETS), help="workload preset")
    parser.add_argument("--tree", help="path to an existing generated tree")
    parser.add_argument(
        "--split", action="store_true", help="also time discovery separately"
    )
    parser.add_argument(
        "--cold", action="store_true", help="print drop-caches instructions and exit"
    )
    args = parser.parse_args()

    if args.cold:
        print("Cold-cache runs need root; run manually then repeat:")
        print("  sudo sysctl vm.drop_caches=3")
        return

    if args.preset:
        tree = _ensure_tree(args.preset)
        run_benchmark(tree, args.preset, split=args.split)
    elif args.tree:
        tree = Path(args.tree)
        run_benchmark(tree, tree.name, split=args.split)
    else:
        parser.error("--preset or --tree is required")


if __name__ == "__main__":
    main()
