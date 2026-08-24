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
- Can show how long each finding's current line has been committed using Git
  history.
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
todoscope src/ --ai --no-cache  # bypass the local AI result cache
todoscope src/ --check-secrets  # list comments that look like credentials
todoscope src/ --blame        # add who-authored-each-finding via git blame
todoscope src/ --age          # add time since each finding was committed
todoscope src/ --age --blame  # show both age and attribution
todoscope src/ --min-age 90   # keep only findings at least 90 days old
todoscope src/ --max-age 0    # keep only uncommitted findings
todoscope src/ --changed main # scan only files differing from the main branch
todoscope src/ --staged       # scan only files staged for commit
todoscope --install-hook      # install a pre-commit hook that gates staged findings
todoscope --uninstall-hook    # remove the hook installed by todoscope
todoscope src/ --quiet        # one numbered finding per line, nothing else
todoscope src/ --verbose      # extra details on stderr
todoscope src/ --format json  # machine-readable JSON report on stdout
todoscope src/ --format sarif # SARIF 2.1.0 report for code-scanning tools
todoscope src/ --format github-actions  # inline PR annotations in GitHub Actions
```

That's it. Findings are sorted by folder depth, then path, then line, and
every text mode uses the same canonical line:

```text
1. src/auth/session.py:84: TODO: Handle expired refresh tokens
```

Scanning is local by default — `--ai` is opt-in and never runs when
`--quiet` is given (the combination prints a note and behaves like plain
`--quiet`). `--blame` requires a Git repository and adds one attribution line
per finding. `--age` also requires Git and shows the number of days since the
finding's current marker line was committed. Uncommitted lines are identified
as such, while unavailable history is reported without failing the scan. Both
options are rejected with `--quiet`; when combined, they share a single
`git blame --porcelain` call per file. Git history data never reaches the AI.

`--min-age DAYS` and `--max-age DAYS` filter the report — and any AI
analysis — to findings whose committed age falls in the range. Uncommitted
lines count as age 0, so `--max-age 0` shows only uncommitted work; lines
with unavailable history are excluded while a filter is active. Both require
Git, are rejected with `--quiet`, and JSON reports include an `age_filter`
object with the bounds and the number of removed findings.

`--format json` prints a deterministic JSON document to stdout (scan
metadata, findings, skipped counts, optional blame and age data, and the AI
section with a machine-readable status/reason). Age entries include a status,
an exact day count, and the commit date; uncommitted or unavailable entries
use `null` for values that do not apply. Without `--ai`, the AI section is
`null`. `--format sarif` prints a deterministic SARIF 2.1.0 document with one
rule per configured marker; AI priorities map to SARIF levels (High →
`error`, Medium → `warning`, Low/Unclear → `note`), and blame and age data
are attached as result properties when requested. Verbose details and errors
always go to stderr. Neither format ever contains API keys or environment
values.

`--changed REF` restricts the scan to tracked files whose content differs
from the given git ref (uncommitted changes are included; untracked files
are not). Ignore and extension rules still apply, and the option composes
with `--blame`, `--age`, and the age filters. JSON reports include a
`changed_ref` field. Requires a valid git ref and a Git repository; unknown
refs fail with exit code 2. `--staged` does the same for files staged for
commit (JSON reports set `"staged": true`), and cannot be combined with
`--changed`.

## Pre-commit

TodoScope can block commits that touch files containing findings:

```bash
cd your-project
todoscope --install-hook        # writes .git/hooks/pre-commit
```

The hook runs `todoscope . --staged --quiet --fail` before every commit:
any staged finding exits 4 and blocks the commit. `--uninstall-hook`
removes it (refusing to touch a hook it did not install). Worktrees are not
supported yet. The repository also ships a
[`.pre-commit-hooks.yaml`](.pre-commit-hooks.yaml), so projects using the
pre-commit framework can add:

```yaml
- repo: https://github.com/Zelmari/todoscope
  rev: v0.21.0
  hooks:
    - id: todoscope
```

(`language: system` — todoscope must be installed, e.g. via pipx.)

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
| `exclude` | Skips exact project-root-relative paths or directory prefixes. Entries containing glob characters (`*`, `?`, `[`) match like `.gitignore` patterns instead. |
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

Results are cached locally (XDG cache directory, `~/.cache/todoscope` on
Linux): repeat runs with identical comment text cost no API budget. The
cache stores only comment hashes plus interpretations and priorities —
never paths, line numbers, or source — and is best-effort: a broken or
unwritable cache never fails a scan. Entries older than 180 days are pruned
and the cache is capped at 20,000 entries. Pass `--no-cache` to bypass it.

> Priorities are estimated from comment text only. No source code was
> provided to the AI.

Payloads above the configured limit are sent in multiple requests, each
within `max_ai_characters` (comments are grouped greedily; one request per
chunk, results merged in finding order, and the overview comes from the
first chunk). A single comment larger than the limit still skips AI
analysis rather than being truncated. The cache is keyed per comment, so
unchanged chunks keep hitting it across runs.

Before any request, comment text is screened for likely credentials (API
keys, tokens, private-key headers, credential assignments). If any finding
looks like a secret, the AI request is refused and the suspicious findings
are listed locally — the local report is unaffected. Detection is
conservative: it flags unambiguous secret shapes, never prose.

`--check-secrets` runs this screening on any scan, with or without AI: it
appends a `Possible credentials in comments` section listing each flagged
finding with the matched rule names, adds a `secrets` array to JSON reports
(`null` without the flag), and emits `credential-in-comment` error results
in SARIF. It is rejected together with `--quiet`.

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
marker, and extracted comment text. Everything else stays local. Before any
request, comment text is screened for likely credentials and the request is
refused if any are found. Comments are
treated as untrusted data — instructions written inside a comment can never
change TodoScope's behaviour. **Never put credentials or secrets in code
comments**, because comment text may be sent to the AI.

## Exit codes

- `0` — scan finished (including local-only results after any AI problem)
- `1` — unexpected failure
- `2` — bad path/usage, or an ignored target refused in non-interactive mode
- `3` — configuration error
- `4` — the opt-in `--fail`/`--fail-count` gate was tripped (only when one of
  those flags is given; finding TODOs is never an error by default)

## Use in CI

TodoScope is CI-friendly: finding TODOs is **not** an error, so scans never
fail a pipeline just because comments exist. Common patterns:

- Log findings: `todoscope . --quiet` (one line per finding).
- Machine-readable reports: `todoscope . --format json` and upload or parse
  the JSON in later steps.
- Code-scanning alerts: `todoscope . --format sarif > todoscope.sarif` and
  upload the file with `github/codeql-action/upload-sarif` (or another
  SARIF consumer) to surface findings as alerts in the Security tab.
- Inline PR annotations: `todoscope . --format github-actions` emits
  `::warning`/`::error`/`::notice` workflow commands, so every finding
  appears directly in the pull request — no extra tooling (see
  `examples/ci/scan-annotations.yml`).
- Enforce a threshold: `todoscope . --quiet --fail-count 10` exits with
  code 4 when more than 10 findings remain (or `--fail` for any findings),
  so a pipeline can fail on policy while the default stays non-failing
  (see `examples/ci/scan-enforce.yml`). The gate counts the final filtered
  report, so it composes with `--min-age`, `--max-age`, and `--changed`.
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
