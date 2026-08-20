# Changelog

## 0.10.2 (2026-08-20)

### Fixed

- Corrected the public `scan_files` return annotation and tightened the
  internal AI, history, reporting, and discovery-cache type contracts.
- AI analysis now fails cleanly without attempting a request when invoked
  without a primary API key.

### Changed

- Pyright now checks application code in CI and before tagged publication.
- The parsing directory is an explicit Python subpackage, and stale or
  deprecated package metadata has been removed.


## 0.10.1 (2026-08-20)

### Fixed

- Project discovery now behaves consistently for relative targets, rejects
  symlink target escapes, and fails closed when ignore files cannot be read.
- Configuration and credential boundaries are stricter: malformed UTF-8 is
  reported cleanly, whitespace-only models are rejected, and an explicitly
  blank shell API key cannot silently fall through to a `.env` credential.
- Comment parsing tolerates malformed Python token streams, preserves pointer
  text in block comments, removes decorative star banners, and keeps grouped
  comment text free of stray whitespace and separators.
- Finding and traversal order is deterministic even when paths differ only by
  case, while findings on the same source line retain their source order.
- Git history supports SHA-1 and SHA-256 object IDs, correctly reuses metadata
  for interleaved porcelain hunks, and enforces the aggregate timeout on the
  final in-flight blame call.
- AI failures now handle invalid keys, client construction errors, and empty
  responses without crashing; validated AI items are emitted in finding order.
- Non-interactive stream detection and incomplete blame metadata now degrade
  to safe, readable output instead of raising exceptions.


## 0.10.0 (2026-08-16)

### Added

- `--age`: shows how many days have passed since each finding's current line
  was committed. It uses Git's committer date, distinguishes uncommitted and
  unavailable history, and adds structured age data to JSON reports.
- `--age` and `--blame` share the same single `git blame --porcelain` call per
  file when used together.


## 0.9.4 (2026-08-13)

### Fixed

- Worker-crash serial retries are now visible: verbose reports
  "Chunks retried serially after worker crash: N" instead of degrading
  silently.
- Benchmarks report physical cores separately from threads (16 cores / 32
  threads on the reference machine); BENCHMARKS.md corrected.
- Blame gained a 120s aggregate budget: past the cap, remaining files
  render "Blame unavailable" and verbose says so, so N files can never
  stall a scan for N x 30s.
- Pool fill loop simplified to track only the newly submitted future.


## 0.9.3 (2026-08-13)

### Changed

- Engine constants are now sweep-derived: the pool gate stays at 500 files
  (measured crossover), the 2 MB byte floor is removed (pools win even for
  100-byte files at qualifying counts), and the submission chunk size drops
  from 200 to 50 (sweep-measured). docs/BENCHMARKS.md carries the sweep
  tables behind every constant.


## 0.9.2 (2026-08-13)

### Changed

- True bounded pool submission: at most 2x workers chunks are in flight at
  once (windowed submission replaces eager chunk queueing).
- Blame invokes git from the project root with a repository-root-relative
  path (correct across submodules and worktrees).
- Benchmark trees enable all ten languages (earlier trees silently skipped
  the five non-default ones); committed docs/BENCHMARKS.md with the
  measured tables, methodology, and decisions.


## 0.9.1 (2026-08-13)

### Fixed

- `--blame` attribution was empty for lines in later hunks of the same
  commit: git repeats porcelain group headers without repeating the author
  attributes, and the parser reset them. Attributes now carry forward.


## 0.9.0 (2026-08-13)

### Added

- `--blame`: adds a `Authored by <author> · <date> · <commit>` line under
  each finding (one `git blame --porcelain` call per file, 30s timeout,
  failures isolated per file). Requires a Git repository; rejected together
  with `--quiet`; JSON gains per-finding `"blame"`; verbose gains blame
  stats. Blame data is structurally separate from findings and can never
  enter the AI payload (privacy-tested).


## 0.8.3 (2026-08-13)

### Changed

- Parallel engine tuned with benchmark data (32-core machine, warm cache):
  the pool now requires at least 500 files in addition to the 2 MB size
  floor (few-large workloads lose in a pool — chunk-result serialisation
  dominates), and the 8-worker cap is confirmed by the plateau at 8.
- Crashed worker chunks now retry serially on their own instead of falling
  back for the whole scan.
- tree-sitter pinned to >=0.25.2,<0.26 after 0.26.0 proved to corrupt the
  heap with current grammar wheels (canary regression test added).
- Added the benchmark harness (benchmarks/) used to derive the constants.


## 0.8.2 (2026-08-13)

### Fixed

- Parallel engine hardening: chunked pool submission (backpressure on huge
  repositories), serial fallback when a worker process crashes, and a
  worker cap that respects the machine's CPU count.
- Windows support: multiprocessing freeze_support in the entry point and a
  windows-latest CI job verifying the spawn-based pool end to end.
- README releasing example now uses a placeholder tag.


## 0.8.1 (2026-08-13)

### Fixed

- Replaced tree-sitter-language-pack (which downloaded parser binaries from
  GitHub at first use, breaking CI and offline scans) with the individual
  tree-sitter grammar packages, whose wheels bundle the grammars. Scanning
  now needs no network access at all.


## 0.8.0 (2026-08-13)

### Changed (breaking)

- AI is now opt-in: plain `todoscope` scans locally with no AI request and
  no AI output; pass `--ai` to add interpretations and priorities.
- `--no-ai` removed (local-only is the default).
- Unified finding format across text modes: one canonical numbered line
  (`1. path:line: MARKER: text`) in standard and quiet output; quiet drops
  only headers and summaries.
- `--quiet` and `--ai` together are rejected with a note on stderr and
  behave as plain `--quiet` (no AI request).
- `--format json` without `--ai` now reports `"ai": null`.


## 0.7.0 (2026-08-13)

### Added

- GitHub Actions integration guide: CI usage section in the README and
  ready-made example workflows in examples/ci (JSON artifact upload and a
  log-only variant). Findings never fail CI runs.


## 0.6.0 (2026-08-13)

### Added

- Support for Java, Go, C, C++, and C# (.java .go .c .h .cpp .cc .cxx .hpp
  .cs). Grammar-aware extraction correctly ignores strings, char literals,
  Java text blocks, Go raw strings, C preprocessor lines, C++ raw strings,
  and C# verbatim/interpolated verbatim strings. Default scanned extensions
  are unchanged; enable the new ones via `extensions` in `.todoscope.json`.


## 0.5.0 (2026-08-13)

### Added

- Nested `.gitignore` support with git semantics: patterns are relative to
  their own directory, deeper files override earlier ones, and excluded
  directories stay pruned. Explicit-target confirmation now covers rules
  from nested files too.


## 0.4.0 (2026-08-13)

### Added

- Adaptive parallel scanning: large workloads (2 MB+ across multiple files)
  are extracted in a process pool (up to 8 workers); smaller scans stay
  serial. Results and ordering are identical either way.


## 0.3.0 (2026-08-13)

### Added

- `--format json`: deterministic machine-readable report on stdout (scan
  metadata, findings, skipped counts, AI status with machine-readable
  reason). Never contains API keys or environment values.


## 0.2.0 (2026-08-13)

### Added

- GitHub Actions CI (tests, lint, format, build on push and pull requests,
  Python 3.12 and 3.13).
- Publish-on-tag workflow: gates, build, PyPI upload via the `PYPI_TOKEN`
  repository secret, and an automatic GitHub release.

## 0.1.1 (2026-08-13)

## Changed

- Simplified README for end users.

### Known limitations

- No structured JSON output; no secret detection inside comments.
