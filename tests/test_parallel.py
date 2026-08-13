"""Parallel scanning tests (MS-13 + robustness fixes)."""

from __future__ import annotations

from concurrent.futures.process import BrokenProcessPool

from todoscope.config import load_config
from todoscope.scan import (
    MAX_PARALLEL_WORKERS,
    _worker_count,
    scan_files,
)


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
    serial, _ = scan_files(files, tmp_path, config, parallel=False)
    parallel, _ = scan_files(files, tmp_path, config, parallel=True, max_workers=2)
    assert [(i.id, i.finding) for i in serial] == [(i.id, i.finding) for i in parallel]
    assert [i.id for i in serial] == list(range(1, len(serial) + 1))


def test_parallel_default_uses_file_count_gate(tmp_path, monkeypatch) -> None:
    build_tree(tmp_path)
    files = files_of(tmp_path)
    config = load_config(tmp_path)

    pool_used: list[int] = []
    real_executor = __import__(
        "todoscope.scan", fromlist=["ProcessPoolExecutor"]
    ).ProcessPoolExecutor

    class SpyExecutor(real_executor):
        def __init__(self, **kwargs):
            pool_used.append(kwargs["max_workers"])
            super().__init__(**kwargs)

    monkeypatch.setattr("todoscope.scan.ProcessPoolExecutor", SpyExecutor)
    monkeypatch.setattr("todoscope.scan.PARALLEL_MIN_FILES", 10)
    scan_files(files, tmp_path, config)
    assert pool_used == [_worker_count()]
    monkeypatch.setattr("todoscope.scan.PARALLEL_MIN_FILES", len(files) + 1)
    pool_used.clear()
    scan_files(files, tmp_path, config)
    assert pool_used == []


def test_chunked_submission_limits_queue(tmp_path, monkeypatch) -> None:
    build_tree(tmp_path)
    files = files_of(tmp_path)
    config = load_config(tmp_path)
    submits: list[int] = []

    real_executor = __import__(
        "todoscope.scan", fromlist=["ProcessPoolExecutor"]
    ).ProcessPoolExecutor

    class SpyExecutor(real_executor):
        def submit(self, fn, *args, **kwargs):
            submits.append(len(args[0]))
            return super().submit(fn, *args, **kwargs)

    monkeypatch.setattr("todoscope.scan.ProcessPoolExecutor", SpyExecutor)
    scan_files(files, tmp_path, config, parallel=True, max_workers=2, chunk_size=5)
    assert submits
    assert all(size <= 5 for size in submits)
    assert sum(submits) == len(files)


def test_broken_pool_falls_back_to_serial(tmp_path, monkeypatch) -> None:
    build_tree(tmp_path)
    files = files_of(tmp_path)
    config = load_config(tmp_path)

    def crash(*args, **kwargs):
        raise BrokenProcessPool()

    monkeypatch.setattr("todoscope.scan._extract_parallel", crash)
    result, _ = scan_files(files, tmp_path, config, parallel=True)
    serial, _ = scan_files(files, tmp_path, config, parallel=False)
    assert [(i.id, i.finding) for i in result] == [(i.id, i.finding) for i in serial]


def test_failed_chunks_retry_serially_without_losing_findings(
    tmp_path, monkeypatch
) -> None:
    from concurrent.futures import Future

    build_tree(tmp_path)
    files = files_of(tmp_path)
    config = load_config(tmp_path)

    class ImmediatePool:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def submit(self, fn, *args):
            future = Future()
            future.set_running_or_notify_cancel()
            if args[0][0] == files[0].as_posix():
                future.set_exception(BrokenProcessPool())
            else:
                future.set_result(fn(*args))
            return future

    monkeypatch.setattr("todoscope.scan.ProcessPoolExecutor", ImmediatePool)
    result, retried = scan_files(files, tmp_path, config, parallel=True, chunk_size=1)
    serial, _ = scan_files(files, tmp_path, config, parallel=False)
    assert [(i.id, i.finding) for i in result] == [(i.id, i.finding) for i in serial]
    assert len(result) == len(serial) == 16
    assert retried == 1


def test_submission_window_is_bounded(tmp_path, monkeypatch) -> None:
    import threading
    import time
    from concurrent.futures import Future

    build_tree(tmp_path, dirs=2, files=8)
    files = files_of(tmp_path)
    config = load_config(tmp_path)

    class WindowPool:
        def __init__(self, **kwargs):
            self.inflight = 0
            self.max_inflight = 0

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def submit(self, fn, *args):
            self.inflight += 1
            self.max_inflight = max(self.max_inflight, self.inflight)
            future = Future()

            def run():
                time.sleep(0.01)
                try:
                    future.set_result(fn(*args))
                except BaseException as exc:  # noqa: BLE001
                    future.set_exception(exc)

            def done(_):
                self.inflight -= 1

            future.add_done_callback(done)
            threading.Thread(target=run, daemon=True).start()
            return future

    pool = WindowPool()
    monkeypatch.setattr("todoscope.scan.ProcessPoolExecutor", lambda **kw: pool)
    result, retried = scan_files(
        files, tmp_path, config, parallel=True, max_workers=2, chunk_size=1
    )
    serial, _ = scan_files(files, tmp_path, config, parallel=False)
    assert [(i.id, i.finding) for i in result] == [(i.id, i.finding) for i in serial]
    assert pool.max_inflight <= 4  # 2 x workers
    assert retried == 0


def test_worker_count_caps(monkeypatch) -> None:
    monkeypatch.setattr("todoscope.scan.os.cpu_count", lambda: 64)
    assert _worker_count() == MAX_PARALLEL_WORKERS
    monkeypatch.setattr("todoscope.scan.os.cpu_count", lambda: 4)
    assert _worker_count() == 4
    monkeypatch.setattr("todoscope.scan.os.cpu_count", lambda: None)
    assert _worker_count() == 1


def test_scan_files_with_empty_input(tmp_path) -> None:
    config = load_config(tmp_path)
    assert scan_files((), tmp_path, config) == ((), 0)
