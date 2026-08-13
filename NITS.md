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

- Status: **RESOLVED (2026-08-13, 0.9.4)** — `BLAME_TOTAL_BUDGET_SECONDS`
  (120s) caps the whole blame phase: once exceeded, remaining files are
  reported as blame-unavailable and verbose prints
  `Blame budget exceeded: yes`. Per-file timeout stays 30s.

## 5. Engine constants are not fully derivable from BENCHMARKS.md

- Status: **RESOLVED (2026-08-13, 0.9.3)** — sweep benchmarks
  (`benchmarks/sweep.py`) measured the file-count crossover (100/250/500/
  750/1000/1500/2000), a byte-size sweep, and chunk sizes
  (50/100/200/500/1000). Constants updated from the data: 500 confirmed as
  the first clear pool win; the 2 MB byte floor removed (pool wins even for
  100-byte files at qualifying counts); chunk size changed 200 -> 50.
  `docs/BENCHMARKS.md` now contains the sweep tables behind every
  constant.
