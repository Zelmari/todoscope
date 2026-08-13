"""Parallel scanning tests (MS-13): identical results, deterministic order."""

from __future__ import annotations

from todoscope.config import load_config
from todoscope.scan import MAX_PARALLEL_WORKERS, scan_files


def build_tree(tmp_path, dirs: int = 4, files: int = 4) -> None:
    for d in range(dirs):
        for f in range(files):
            path = tmp_path / f"d{d}" / f"m{f}.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# TODO: fix {d}/{f}\ns = '# TODO: not a comment'\n")


def files_of(tmp_path):
    from todoscope.discovery import discover_files

    return discover_files(tmp_path, tmp_path, load_config(tmp_path)).files


def test_serial_and_parallel_are_identical(tmp_path) -> None:
    build_tree(tmp_path)
    files = files_of(tmp_path)
    config = load_config(tmp_path)
    serial = scan_files(files, tmp_path, config, parallel=False)
    parallel = scan_files(files, tmp_path, config, parallel=True, max_workers=2)
    assert [(i.id, i.finding) for i in serial] == [(i.id, i.finding) for i in parallel]
    assert [i.id for i in serial] == list(range(1, len(serial) + 1))


def test_parallel_default_uses_threshold(tmp_path, monkeypatch) -> None:
    build_tree(tmp_path)
    files = files_of(tmp_path)
    config = load_config(tmp_path)
    total = sum(p.stat().st_size for p in files)

    pool_used: list[int] = []
    real_executor = __import__(
        "todoscope.scan", fromlist=["ProcessPoolExecutor"]
    ).ProcessPoolExecutor

    class SpyExecutor(real_executor):
        def __init__(self, **kwargs):
            pool_used.append(kwargs["max_workers"])
            super().__init__(**kwargs)

    monkeypatch.setattr("todoscope.scan.ProcessPoolExecutor", SpyExecutor)
    scan_files(files, tmp_path, config, size_threshold=total + 1)
    assert pool_used == []
    scan_files(files, tmp_path, config, size_threshold=total - 1)
    assert pool_used == [MAX_PARALLEL_WORKERS]


def test_worker_function_is_picklable_module_level() -> None:
    from todoscope.scan import _extract_worker

    assert _extract_worker.__module__ == "todoscope.scan"


def test_scan_files_with_empty_input(tmp_path) -> None:
    config = load_config(tmp_path)
    assert scan_files((), tmp_path, config) == ()
