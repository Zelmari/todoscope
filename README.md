# TodoScope

TodoScope finds maintenance comments (`TODO`, `FIXME`, ...) in your code and
prints a clean report. Optionally, it asks an AI to interpret each comment and
estimate its priority — **without ever sending your source code anywhere**.

```bash
todoscope src/
```

## What it does

- Scans Python, JavaScript, TypeScript, JSX/TSX, Rust, Java, Go, C, C++,
  and C# files for comments that start with your markers (`TODO` by
  default). The default enabled set is `.py .js .jsx .ts .tsx .rs`; enable
  more extensions (`.java .go .c .h .cpp .cc .cxx .hpp .cs`) through
  `extensions` in `.todoscope.json`.
- Only real comments count: `TODO` inside strings, template literals, JSX
  text, or raw strings is ignored.
- Respects every `.gitignore` in the tree (root and nested, with git's
  override semantics) and an optional exclusion list.
- Works fully offline — the AI part is optional.
- When AI is on, it sends only each comment's ID, marker, and text. No file
  names, no paths, no line numbers, no code.

## Install

Requires Python 3.12+.

```bash
pipx install todoscope        # recommended
# or
uv tool install todoscope     # if you use uv
# or
python3 -m pip install todoscope
```

## Use

```bash
todoscope src/                # scan a folder recursively (local only)
todoscope src/main.py         # scan one file
todoscope .                   # scan the whole project
todoscope src/ --ai           # add AI interpretations and priorities
todoscope src/ --blame        # add who-authored-each-finding via git blame
todoscope src/ --quiet        # one numbered finding per line, nothing else
todoscope src/ --verbose      # extra details on stderr
todoscope src/ --format json  # machine-readable JSON report on stdout
```

That's it. Findings are sorted by folder depth, then path, then line, and
every text mode uses the same canonical line:

```text
1. src/auth/session.py:84: TODO: Handle expired refresh tokens
```

Scanning is local by default — `--ai` is opt-in and never runs when
`--quiet` is given (the combination prints a note and behaves like plain
`--quiet`). `--blame` requires a Git repository, adds one attribution line
per finding (from a single `git blame --porcelain` call per file), and is
likewise rejected with `--quiet`. Blame data never reaches the AI.

`--format json` prints a deterministic JSON document to stdout (scan
metadata, findings, skipped counts, and the AI section with a machine-
readable status/reason). Without `--ai`, the AI section is `null`. Verbose
details and errors always go to stderr. JSON never contains API keys or
environment values.

## Configuration

Everything optional lives in a `.todoscope.json` in your project root:

```json
{
  "markers": ["TODO", "FIXME"],
  "extensions": [".py", ".js", ".jsx", ".ts", ".tsx", ".rs"],
  "exclude": ["tests/fixtures/", "generated/"],
  "model": "your-ai-model-id",
  "max_ai_characters": 20000
}
```

| Key | What it does |
|---|---|
| `markers` | Replaces the default marker list (`["TODO"]`). Matching is case-sensitive and prefix-based; the longest matching marker wins. |
| `extensions` | Replaces the default scanned extensions. |
| `exclude` | Skips exact project-root-relative paths or directory prefixes. |
| `model` | Required for AI analysis. There is **no default model**. |
| `max_ai_characters` | Lower AI payload limit (hard ceiling: 100,000). |

Invalid configuration stops with a clear error (exit code 3).

## AI analysis

AI is opt-in: pass `--ai` to request it. To enable it you need both:

1. An API key — from your shell (`TODOSCOPE_API_KEY`) or a `.env` file in the
   project root:

   ```dotenv
   TODOSCOPE_API_KEY=...
   TODOSCOPE_SECONDARY_API_KEY=...
   ```

   Shell values win over `.env`. If a key comes from `.env`, that file must
   be ignored by your `.gitignore`, otherwise AI is refused for safety.

2. A `model` in `.todoscope.json`.

When enabled, TodoScope makes **one** request and then prints one complete
report: per finding you get a short interpretation and an estimated priority
(High / Medium / Low / Unclear), plus an overall summary. If the request
fails and a secondary key is configured, an interactive terminal offers one
retry with it — the secondary key is never used silently.

> Priorities are estimated from comment text only. No source code was
> provided to the AI.

### Using DeepSeek (or another OpenAI-compatible provider)

The OpenAI SDK reads `OPENAI_BASE_URL` from your environment. For DeepSeek:

```bash
export OPENAI_BASE_URL=https://api.deepseek.com
todoscope .
```

or as a permanent alias in `~/.zshrc`:

```zsh
alias todoscope="OPENAI_BASE_URL=https://api.deepseek.com /home/$USER/.local/bin/todoscope"
```

## Privacy

The only data from your repository that reaches the AI is each finding's ID,
marker, and extracted comment text. Everything else stays local. Comments are
treated as untrusted data — instructions written inside a comment can never
change TodoScope's behaviour. **Never put credentials or secrets in code
comments**, because comment text may be sent to the AI.

## Exit codes

- `0` — scan finished (including local-only results after any AI problem)
- `1` — unexpected failure
- `2` — bad path/usage, or an ignored target refused in non-interactive mode
- `3` — configuration error

## Use in CI

TodoScope is CI-friendly: finding TODOs is **not** an error, so scans never
fail a pipeline just because comments exist. Common patterns:

- Log findings: `todoscope . --quiet` (one line per finding).
- Machine-readable reports: `todoscope . --format json` and upload or parse
  the JSON in later steps.
- AI in CI: set `TODOSCOPE_API_KEY` as a repository secret and a `model` in
  `.todoscope.json`; non-interactive runs skip the secondary key safely.

Ready-made examples live in [`examples/ci/`](examples/ci/):

- `scan-pr.yml` — scan on pull requests, print findings, upload the JSON
  report as an artifact.
- `scan-quiet.yml` — minimal log-only variant.

## Development

```bash
uv sync                       # set up the environment
uv run pytest                 # tests
uv run ruff check .           # lint
uv run ruff format --check .  # format check
uv build                      # wheel + sdist
```

Continuous integration runs these same checks on every push and pull
request (Python 3.12 and 3.13).

## Releasing

1. Bump `version` in `pyproject.toml` (minor for features, patch for fixes).
2. Add a `CHANGELOG.md` entry for the new version.
3. Commit, then tag and push the tag:

```bash
git tag vX.Y.Z          # e.g. git tag v0.8.2
git push
git push --tags
```

The publish workflow verifies everything, uploads to PyPI using the
`PYPI_TOKEN` repository secret, and creates a GitHub release automatically.

To re-publish an older tag (for example, backfilling a version that never
made it to PyPI), run the workflow manually: Actions → Publish → Run
workflow, and set the `ref` input to the tag name (e.g. `v0.5.0`).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
