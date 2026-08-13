# Nits and deferrals

Small known issues that are deliberately not fixed yet. Each entry says what,
where, and why it matters, so it can be resolved deliberately later.

## 1. Redundant `pending.update(future_to_index)` in the pool fill loop

- Where: `src/todoscope/scan.py`, `_extract_parallel` fill loop.
- What: `pending.update(future_to_index)` re-adds futures that are already in
  `pending`; only `pending.add(future)` is needed. Harmless, but a reviewer
  will ask "why?" when they see it.
- Fix: simplify to add just the newly submitted future.
- Status: deferred.

## 2. BENCHMARKS.md claims "32 cores"

- Status: **RESOLVED (2026-08-13, 0.9.4)** — machine_spec now reports
  physical cores separately from threads (`cpu: N cores / M threads`),
  detected via /proc/cpuinfo on Linux with a thread-count fallback, and
  BENCHMARKS.md reads "16 physical cores / 32 threads (Ryzen 395)".

## 3. Silent degradation when crashed chunks retry serially

- Where: `src/todoscope/scan.py`, `_extract_parallel` BrokenProcessPool path.
- What: when a worker crashes, unfinished chunks are re-run serially, but
  nothing reports it. The scan stays correct but observability is missing.
- Fix: count retried chunks and surface one line in `--verbose`
  (e.g. `Chunks retried serially after worker crash: N`), plus a unit test.
- Status: deferred.

## 4. Blame has no aggregate timeout budget

- Where: `src/todoscope/blame.py` (`BLAME_TIMEOUT_SECONDS = 30`) and the CLI
  blame loop.
- What: the 30s timeout is per file; N files-with-findings can total N × 30s
  in the worst case. Fine in practice (small sets, git is fast), but the
  bound is undocumented.
- Fix options (later): keep per-file 30s and add an aggregate budget with
  graceful cutoff, or document the per-file-only bound explicitly as a
  product decision.
- Status: deferred (documented here in the meantime).

## 5. Engine constants are not fully derivable from BENCHMARKS.md

- Status: **RESOLVED (2026-08-13, 0.9.3)** — sweep benchmarks
  (`benchmarks/sweep.py`) measured the file-count crossover (100/250/500/
  750/1000/1500/2000), a byte-size sweep, and chunk sizes
  (50/100/200/500/1000). Constants updated from the data: 500 confirmed as
  the first clear pool win; the 2 MB byte floor removed (pool wins even for
  100-byte files at qualifying counts); chunk size changed 200 -> 50.
  `docs/BENCHMARKS.md` now contains the sweep tables behind every
  constant.
