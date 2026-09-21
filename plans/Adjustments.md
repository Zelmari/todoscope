# TodoScope adjustments

Static review of the tree as of 2026-09-21. No code was changed for this note.

TodoScope is a local scanner for maintenance comments (`TODO`, `FIXME`, and whatever markers you configure). It walks a project, respects `.gitignore` and `.todoscope.json`, and prints text, JSON, SARIF, or GitHub Actions annotations. Optional pieces are AI ranking of the comment text only, git blame and age, secret-shaped comments, a pre-commit gate, and a `--diff` baseline.

The findings are from the source and tests. The suite was not executed.

## Bugs

### 1. `--sort age` does not sort by age

The history map is passed into the text report only when `--blame` or `--age` is also set. `order_findings` reads the blame argument, so `--sort age` alone sorts by path and line. The test named `test_sort_age_orders_oldest_first` still passes because the older TODO in that fixture is already on the earlier line.

```800:814:src/todoscope/cli.py
        report = standard_report(
            findings,
            ...
            blames if args.blame else None,
            blames if args.age else None,
            ...
            sort=args.sort,
```

When blame data is present, the key is ascending day count, so newer lines come first. The README says oldest first, unavailable last.

`--quiet --sort age` never loads blame (`do_history` is turned off in quiet mode), so that combination is also path order, with exit code 0. `--format json --sort age` still requires a git repo and blames every file, then throws the order away because JSON stays in scan order.

Proposed fix: pass the blame map into `order_findings` whenever the sort is `age`, and only for text output. Sort with unavailable last and known ages descending. Apply the same map on the quiet path. Ignore `--sort` for JSON, SARIF, and GitHub Actions. Replace the age test with two findings whose line order is the opposite of their age.

### 2. `--staged` and the pre-commit hook read the working tree, not the index

`staged_files` only returns paths from `git diff --cached --name-only`. Extraction then calls `Path.read_text` on those paths. A TODO that is staged, then removed in an unstaged edit, does not block the commit. A TODO that exists only in the working tree, on a file that is otherwise staged, does block it. The hook is `todoscope . --staged --quiet --fail`, so this is the commit gate.

Proposed fix: for `--staged`, extract from the index blob (`git show :path`), and skip paths that are staged deletions. Keep the working-tree read for a normal scan and for `--changed`.

### 3. `--diff` stores a partial baseline when the scan is already narrowed

The baseline is taken from whatever `scan()` returned. `--changed` and `--staged` restrict that set first. The README says the baseline always covers the complete scan and that `--changed` does not affect it. One `todoscope . --changed main --diff` replaces the saved fingerprint with only those files. The next full `--diff` reports every other finding as new.

Proposed fix: when `--diff` is set, fingerprint the unrestricted scan, and apply `--changed` or `--staged` only to what is printed. If a narrowed scan must stay cheap, refuse to update the baseline and say so on stderr.

### 4. Quiet mode warns about filters, then ignores them

`--quiet` combined with `--min-age`, `--max-age`, `--author`, `--blame`, `--age`, or `--check-secrets` prints a conflict line and continues with exit code 0. History and those filters are disabled because `do_history` requires “not quiet”. `--fail` still counts the unfiltered findings. `todoscope . --quiet --min-age 90 --fail-count 10` in CI enforces the total TODO count, not the 90-day count. `--group-by` with `--quiet` is a real `parser.error`; these other flags are not.

Proposed fix: reject those combinations with exit code 2 before scanning, the same way `--group-by` is rejected. Update the tests that currently expect exit code 0.

### 5. `--max-age 0` drops untracked files

Age 0 is defined as “uncommitted”. `git blame` on a never-added file fails, the error is swallowed, and an active age filter excludes lines with no history. New files, which are the uncommitted work, disappear from `--max-age 0`.

Proposed fix: if the path is untracked, treat every finding in it as age 0 with author unknown. Classify with `git ls-files --error-unmatch` or `git status --porcelain`, rather than treating every blame failure as “no age”.

### 6. Age is off by a day around midnight

Commit timestamps are stored as UTC dates. The comparison uses `date.today()`, which is local. A commit late in the local evening can already be “1 day” old, and a commit just after UTC midnight can show as 0 days while it is still “today” locally. That changes `--min-age` and `--max-age` results.

Proposed fix: convert the committer timestamp to a local date and compare that with `date.today()`.

### 7. `--install-hook` overwrites an existing hook

Uninstall refuses to delete a hook it did not install. Install always `write_text`s `.git/hooks/pre-commit`. A foreign or hand-written hook is replaced, and uninstall cannot bring it back.

Proposed fix: if the file exists and does not contain the todoscope marker, exit 2 and leave it alone. Write the absolute path of the `todoscope` executable into the script. Git hooks often run with a minimal `PATH`, so `exec todoscope` fails for GUI commits even when the terminal works.

### 8. Hooks ignore `core.hooksPath` except in worktrees

A normal repo always uses `.git/hooks/pre-commit`. `git rev-parse --git-path hooks` is used only when `.git` is a file. With a global hooks path, the installed hook never runs.

Proposed fix: always resolve the hooks directory with `git rev-parse --git-path hooks`.

### 9. `--changed` and `--staged` mis-parse git pathnames

Names are taken from `git diff --name-only` line splitting. With the default `core.quotePath=true`, non-ASCII and unusual paths come back quoted (`"caf\303\251.py"`) and then fail the intersection with discovered files, so those files are silently skipped. Any `ChangedError`, including a timeout, is re-raised as `unknown ref`.

Proposed fix: `git diff -z --name-only --no-renames`, split on NUL, and keep the original error text. Verify the ref with `git rev-parse --verify --end-of-options` before diff so a value like `--output=...` cannot be interpreted as a git option.

### 10. `.jsx` is not parsed as JSX

`.tsx` uses the TSX grammar, which is what the tests use to ignore JSX text and attribute strings. `.jsx` uses the plain JavaScript grammar. In a `.jsx` file, `<span>text // TODO: note</span>` can be reported as a real comment. The README says JSX text is ignored, and `.jsx` is one of the default extensions.

Proposed fix: point `.jsx` at `language_tsx` (or a JSX grammar) and add the TSX fixture as a `.jsx` extraction test.

### 11. A multi-chunk AI run is reported as cached if any chunk was cached

`used_cache = used_cache or chunk_cached`. One chunk served from disk and another sent to the API still sets `"cached": true` and prints “Interpretations served from the local cache.” The parallel path also updates the shared cache dict from several threads with no lock.

Proposed fix: set the flag only when every chunk was a full cache hit. Guard cache reads and writes with a lock, and write the cache file via a temporary file plus `os.replace` so two concurrent scans cannot truncate it.

### 12. GitHub Actions annotations do not escape property delimiters

`_escape` handles `%`, CR, and LF. Workflow-command properties also need `:` (`%3A`) and `,` (`%2C`). A path such as `src/a,title=other.py` splits the `file` property and overwrites `title`. The message body is escaped well enough that a newline cannot start a second command.

Proposed fix: escape colon and comma in `file` and `title` only. Add a test whose path contains both.

### 13. Blame and age stop at the first line of a finding, and submodules get neither

Merged continuation lines and block comments are reported on the marker’s start line, so blame and age follow that line even when the text was committed later. Files inside a submodule are blamed from the parent repo, `git blame` fails, and the finding is “unavailable”. Under an age filter, unavailable means removed.

Proposed fix: record the line that actually contains the marker, and run blame with that repo’s root when a path is inside a nested gitlink. Surface a stderr warning when the blame budget drops files while an age or author filter is active, because those findings are then deleted from the report with no message unless `--verbose` is on.

## Performance

**Reuse parsers inside a process.** `_parser_for` builds a new `tree_sitter.Language` and `Parser` for every file. Cache one parser per language per process (`lru_cache` or a worker-local dict). That applies to the serial path and to each pool worker.

**Stop importing every grammar on startup.** `parsing/comments.py` imports all twenty tree-sitter packages even for `todoscope --help` or a Python-only tree. Import the grammar for a language the first time a file needs it. Default scans pay Python’s `tokenize` plus discovery, and the process pool’s 500-file threshold can drop because worker startup gets cheaper, especially on Windows where the pool uses spawn rather than fork.

**Query comments instead of walking the whole syntax tree.** `extract_tree_sitter_comments` visits every node. A compiled query for `comment`, `line_comment`, `block_comment`, and the documentation node types does the same job with less Python overhead. Read the file as bytes once and hand those bytes to tree-sitter; `read_text` plus `encode` copies every source file.

**Do less work for `--changed` and `--staged`.** Discovery still walks the whole tree, then intersects with the git path list. Start from that path list, and stat only those files, when the user asked for a narrowed scan. Skip the full blame pass when the output format ignores `--sort age`.

**Blame in parallel, and only the lines you need.** Blame is one sequential `git blame --porcelain` per file, capped at 120 seconds total, after which later files become “unavailable” and fall out of age and author filters. A small pool of blame processes (4 is enough; blame is git-bound) fits more files in the budget. For a file with few findings, `git blame -L start,end --porcelain` avoids blaming tens of thousands of unrelated lines.

**Use pathspec’s matcher when there is no override.** Every file and directory walks every gitignore pattern in Python so that a confirmed override can disable specific pattern indexes. The common case has no override. Use `GitIgnoreSpec`’s compiled match there, and keep the slow walk for the override path.

**Screen secrets once.** `secret_entries` runs every regex, then runs them again to decide whether to keep the row. Match once and keep the rule names.

## Worth adding

- **Reject or skip one oversized comment instead of dropping AI for the whole scan.** One comment above `max_ai_characters` sets `PAYLOAD_TOO_LARGE` for every finding. Report that comment as skipped and send the chunks that fit.
- **Give findings an end line.** Continuations are merged into one finding, but SARIF and `::warning` set `endLine` to the first line, so the annotation does not cover the comment the user wrote.
- **Make `--diff` identity survive line shifts.** The fingerprint is `path:line:marker:text`. Inserting a line above a TODO marks it removed and new. Key on path, marker, text, and occurrence index within the file.
- **Redact secret text in CI formats.** `--check-secrets` plus SARIF or GitHub Actions uploads the comment, which is the credential, into logs and code scanning. Keep the path, line, and rule name, and mask the matched span.
- **Say when a symlink target was skipped.** An explicit symlink is intentionally not followed, and the scan exits 0 with no findings. The only counter is `Symlinks skipped` in `--verbose`. A stderr line would stop that from looking like a clean tree.
- **Cap file size.** There is no limit before `read_text`. A multi-gigabyte file with a scanned extension will be loaded whole. Skip or warn above something like 10 MB.
- **Parse `.h` as C++ when the header is C++.** `.h` always uses the C grammar, so a C++ raw string in a `.h` file can be reported as a comment. `.hpp` is already C++. A config switch, or trying the C++ grammar when the C parse is wrong, covers the common header layout.
- **Case-insensitive extensions.** `path.suffix` is case-sensitive, so `File.PY` is “unsupported” on case-insensitive filesystems. Compare `suffix.casefold()` against the extension map.
- **Publish workflow.** A manual run whose `ref` input is left blank publishes the branch tip. The release step only runs when `github.ref` is a tag, so a dispatched tag publish can upload to PyPI and skip the GitHub release. Require a `v*` ref on `workflow_dispatch`, and point the release action at that tag. The README’s pre-commit example still pins `rev: v0.21.0` while the package is 0.27.0.
