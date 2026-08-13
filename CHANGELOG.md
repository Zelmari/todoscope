# Changelog

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

- Nested `.gitignore` files are not applied yet.
- No structured JSON output; no secret detection inside comments.
