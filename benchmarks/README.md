# Benchmarks

Honest measurements for the todoscope scan engine. Trees are generated, not
hand-written, so parsing work is realistic: every file contains real
maintenance comments plus trap content (markers inside strings, raw strings,
and text blocks) that parsers must correctly skip.

## Generating trees

```bash
uv run python benchmarks/gen_tree.py --name monorepo --files 2000 --max-depth 5
uv run python benchmarks/gen_tree.py --name few-large --files 8 --fixed-size 2000000
```

Trees land in `benchmarks/.trees/<name>/` (gitignored, on real disk — never
generate into /tmp, tmpfs would fake the numbers).

## Running

```bash
uv run python benchmarks/run.py --preset tiny
uv run python benchmarks/run.py --preset many-small --split
uv run python benchmarks/run.py --tree path/to/tree
uv run python benchmarks/run.py --cold   # prints drop-caches instructions
```

Each run times serial plus worker counts {2,4,8,16,32}: one warmup, then 5
timed runs, reporting median and min. Results are written as CSV plus a
machine-spec file to `benchmarks/.results/`.

## Reading the results

- **tiny / many-small**: whether pool startup overhead ever pays off on
  small-file repos (it does not — that is why the engine has a size
  threshold).
- **few-large**: scaling curve; the plateau shows the useful worker cap.
- **monorepo**: mixed real-world shape; the serial-vs-pool crossover
  informs `PARALLEL_SIZE_THRESHOLD`.
- **--split**: separates walk/read cost (discovery) from parse cost
  (extraction).

Decisions derived from these numbers are recorded in the project's
DECISIONS.md and reflected in the constants and docstrings in
`src/todoscope/scan.py`.

## Cold-cache runs

To measure with a cold page cache, run (as a human, on your machine):

```bash
sudo sysctl vm.drop_caches=3
uv run python benchmarks/run.py --preset few-large
```

The harness never runs sudo itself.
