# TodoScope

> **Working name:** `TodoScope` is temporary. A final package and command name
> will be selected before publication.

TodoScope is a fast Python command-line tool for finding maintenance comments
in source code. It scans real code comments for configurable markers such as
`TODO` and prints a structured report. Deterministic scanning happens locally;
an optional OpenAI step interprets only the extracted comment text — source
code never leaves your machine.

```bash
todoscope src/
```

## Features

- Real comment detection for Python, JavaScript, TypeScript, JSX/TSX, and
  Rust — markers inside strings, template literals, JSX text, and raw strings
  are ignored (language-aware parsers, not text search).
- Configurable markers (`TODO` by default), extensions, and exact-path or
  directory-prefix exclusions via `.todoscope.json`.
- Respects the project-root `.gitignore`; asks for confirmation before
  scanning an explicitly requested ignored target.
- Deterministic finding order (directory depth, path, line).
- Local-first: the scanner is fully useful without any API key.
- Optional AI analysis: one short interpretation and one estimated priority
  per finding plus one overall summary, using only the extracted comment
  text (ID, marker, text — nothing else).

## Installation

Requires Python 3.12+. Recommended:

```bash
pipx install todoscope
```

Alternative:

```bash
python3 -m pip install todoscope
```

Then run:

```bash
todoscope src/
```

## Usage

```bash
todoscope src/                 # scan a directory recursively
todoscope src/main.py          # scan one file
todoscope .                    # scan the repository root
todoscope src/ --no-ai         # normal report, skip the AI request
todoscope src/ --quiet         # one finding per line, no headings or AI
todoscope src/ --verbose       # extra scan details on stderr
```

Exit codes: `0` success (including local-only completion after any AI
problem), `1` unexpected failure, `2` invalid path/usage or an unconfirmed
ignored target in non-interactive mode, `3` configuration error.

## Configuration

All configuration lives in a `.todoscope.json` in the project root:

```json
{
  "markers": ["TODO", "FIXME", "HELP", "LATER"],
  "extensions": [".py", ".js", ".jsx", ".ts", ".tsx", ".rs"],
  "exclude": ["tests/fixtures/", "generated/", "src/legacy/example.py"],
  "model": "your-openai-model-id",
  "max_ai_characters": 20000
}
```

- `markers` replaces the default list (`["TODO"]`). Matching is case-sensitive
  and prefix-based (`TODO` matches `TODOLIST`); the longest matching marker
  wins. Markers may contain only letters, numbers, underscores, or hyphens.
- `extensions` replaces the default list. An extension without a supported
  parser is a configuration error.
- `exclude` lists exact project-root-relative paths or directory prefixes.
  No wildcards.
- `model` is required for AI analysis. **There is no default model.**
- `max_ai_characters` may lower the hard payload ceiling (see below), never
  raise it. The hard ceiling is 100,000 characters and is not overridable.

The file contains no secrets and may be committed.

## API keys

AI analysis uses the OpenAI API. Keys are read from the process environment
first, then from a `.env` file in the project root:

```dotenv
TODOSCOPE_API_KEY=...
TODOSCOPE_SECONDARY_API_KEY=...
```

- Shell environment variables win; `.env` only fills missing values.
- A key loaded from `.env` is only used when `.env` is ignored by the
  project-root `.gitignore`; otherwise AI analysis is refused and the local
  report is printed.
- Keys are never printed, logged, sent to the AI, or written into
  `.todoscope.json`. Copy `.env.example` and fill it in.

If the primary request fails and a secondary key is configured, an
interactive terminal offers exactly one retry with the secondary key and the
same model. The secondary key is never used silently, and never in
non-interactive runs.

## Privacy boundary

The only repository-derived data sent to the AI is each finding's scan-local
ID, its marker, and its extracted comment text. The request also contains
fixed TodoScope instructions and the expected response shape.

Never sent: source code, surrounding lines, file names, paths, line numbers,
repository structure, Git data, configuration, environment values, or keys.

Comments are untrusted data: instructions written inside a TODO can never
change TodoScope's behaviour. **Never place credentials or other secrets in
source comments** — comment text may be sent to the AI.

## AI limitations

Priorities and interpretations are estimated from comment text only. The
model never sees source code, so its output can be wrong or generic. Empty
or vague comments normally receive an "Unclear" priority.

## Development

Development uses [uv](https://docs.astral.sh/uv/) (an installed project
manager, not a repository file) and Python 3.12.

```bash
uv sync                      # create/update the local environment
uv run todoscope --help      # run the command
uv run pytest                # tests
uv run ruff check .          # lint
uv run ruff format --check . # format check
uv build                     # build wheel + sdist into dist/
```

## Documentation

- [Product end goal](docs/PRODUCT_END_GOAL.md) — complete specification.
- [Roadmap](docs/ROADMAP.md) — ten-milestone plan with status.
- [Changelog](CHANGELOG.md) — release notes.

Planned after 1.0: nested `.gitignore` support, more languages, structured
JSON output, secret-pattern detection inside comments, and an explicit
non-interactive ignored-target override flag.
