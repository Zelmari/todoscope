# Changelog

## 0.1.0 (2026-08-13)

First public release. Published on PyPI as `todoscope`.

### Added

- Local maintenance-comment scanner for Python, JavaScript, TypeScript,
  JSX/TSX, and Rust with language-aware comment extraction (strings, template
  literals, JSX text, and raw strings are never mistaken for comments).
- `.todoscope.json` configuration: markers, extensions, exact exclusions,
  AI model, and a lower AI payload limit.
- Project-root discovery inside and outside Git; root `.gitignore` support;
  confirmation flow for explicitly requested ignored targets.
- Deterministic findings (directory depth, case-normalised path, line).
- Standard, `--no-ai`, `--quiet`, and `--verbose` output modes with
  meaningful exit codes.
- Optional OpenAI analysis: one request carrying only comment IDs, markers,
  and extracted text; structured response validation; estimated priorities;
  overall summary; required privacy disclaimer.
- Key loading with shell-over-`.env` precedence, `.env`-safety refusal,
  optional confirmed secondary-key retry, fixed timeout, no automatic
  retries, and a non-polluting stderr status indicator.
- Hard AI payload ceiling of 100,000 characters (frozen for 1.0).
- Packaging: `uv` project, `uv_build` backend, wheel and source distribution,
  MIT license.

### Known limitations

- Nested `.gitignore` files are not applied yet.
- No structured JSON output; no secret detection inside comments.
