# Changelog

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
