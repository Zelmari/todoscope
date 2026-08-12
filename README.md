# TodoScope

`TodoScope` is a fast Python command-line tool for finding maintenance comments in
source code. It scans real code comments for configurable markers such as `TODO` and
shows them in a structured terminal report. Deterministic scanning happens locally;
an optional OpenAI step interprets only the extracted comment text, never source code.

> **Working name:** `TodoScope` is temporary. A final package and command name will be
> chosen before publication.

## Status

Project foundation complete. The scanner is **not implemented yet** — the CLI currently
supports only `--help` and `--version`.

## Development prerequisites

- [uv](https://docs.astral.sh/uv/) — an installed project manager and command runner.
  It is a program on your machine, not a file inside this repository. On Linux, install
  it via your package manager (e.g. `sudo pacman -S uv`) or the official standalone
  installer (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
- Python 3.12 (uv fetches it automatically when missing).

## Setup

```bash
uv sync
```

## Run

```bash
uv run todoscope --help
uv run todoscope --version
uv run python -m todoscope --help
```

## Test, lint, format

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Format in place with:

```bash
uv run ruff format .
```

## Build

```bash
uv build
```

Produces a wheel and a source distribution in `dist/` (not committed).

## Product specification

The complete product definition is documented in
[docs/PRODUCT_END_GOAL.md](docs/PRODUCT_END_GOAL.md) and the milestone roadmap in
[docs/ROADMAP.md](docs/ROADMAP.md).
