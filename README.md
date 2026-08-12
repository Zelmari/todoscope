# TodoScope

TodoScope finds maintenance comments (`TODO`, `FIXME`, ...) in your code and
prints a clean report. Optionally, it asks an AI to interpret each comment and
estimate its priority — **without ever sending your source code anywhere**.

```bash
todoscope src/
```

## What it does

- Scans Python, JavaScript, TypeScript, JSX/TSX, and Rust files for comments
  that start with your markers (`TODO` by default).
- Only real comments count: `TODO` inside strings, template literals, JSX
  text, or raw strings is ignored.
- Respects your `.gitignore` and an optional exclusion list.
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
todoscope src/                # scan a folder recursively
todoscope src/main.py         # scan one file
todoscope .                   # scan the whole project
todoscope src/ --no-ai        # normal report, skip AI
todoscope src/ --quiet        # one line per finding, no headings, no AI
todoscope src/ --verbose      # extra details on stderr
```

That's it. Findings are sorted by folder depth, then path, then line.

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

To enable it you need both:

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

## Development

```bash
uv sync                       # set up the environment
uv run pytest                 # tests
uv run ruff check .           # lint
uv run ruff format --check .  # format check
uv build                      # wheel + sdist
```

## Docs

- [Product specification](docs/PRODUCT_END_GOAL.md)
- [Milestone roadmap](docs/ROADMAP.md)
- [Changelog](CHANGELOG.md)
