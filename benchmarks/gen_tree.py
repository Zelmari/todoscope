"""Generate synthetic repository trees for todoscope benchmarks.

Seeded and deterministic. Content is realistic multi-language source: every
file mixes real maintenance comments, code, and trap content (markers inside
strings/raw strings/text blocks) so parsing work is honest.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

EXTENSIONS = (".py", ".js", ".ts", ".tsx", ".rs", ".java", ".go", ".c", ".cpp", ".cs")

_BLOCKS: dict[str, list[str]] = {
    ".py": [
        "# TODO: fix module @N@",
        's@N@ = "# TODO: trap @N@"',
        "def f@N@():",
        "    return @N@",
    ],
    ".js": [
        "// TODO: fix @N@",
        'const s@N@ = "// TODO: trap";',
        "function f@N@() { return @N@; }",
    ],
    ".ts": [
        "// TODO: fix @N@",
        "const s@N@: string = `// TODO: trap`;",
        "export function f@N@(): number { return @N@; }",
    ],
    ".tsx": [
        "// TODO: fix @N@",
        "const el@N@ = <span>{/* TODO: jsx trap */}@N@</span>;",
        "export const C@N@ = () => el@N@;",
    ],
    ".rs": [
        "// TODO: fix @N@",
        'let s@N@ = r#"// TODO: trap"#;',
        "fn f@N@() -> u32 { @N@ }",
    ],
    ".java": [
        "// TODO: fix @N@",
        'String s@N@ = "// TODO: trap";',
        "int f@N@() { return @N@; }",
    ],
    ".go": [
        "// TODO: fix @N@",
        's@N@ := "// TODO: trap"',
        "func f@N@() int { return @N@ }",
    ],
    ".c": [
        "// TODO: fix @N@",
        'const char *s@N@ = "// TODO: trap";',
        "int f@N@(void) { return @N@; }",
    ],
    ".cpp": [
        "// TODO: fix @N@",
        'auto s@N@ = R"(// TODO: trap)";',
        "int f@N@() { return @N@; }",
    ],
    ".cs": [
        "// TODO: fix @N@",
        'string s@N@ = @"// TODO: trap";',
        "int F@N@() => @N@;",
    ],
}

MAX_FILE_SIZE = 2_000_000
MIN_FILE_SIZE = 100
MEDIAN_SIZE = 2_000

_PAD_TEMPLATE = "\n".join(
    [
        "/*" + "-" * 78,
        " * padding block {p}",
        " *" + " filler line {q}" * 1,
        " *" + "-" * 78,
        " */",
        'const pad{p} = "filler filler filler filler filler filler";',
    ]
)

_PAD_COMMENT_LINES = "\n".join(
    ["// filler documentation line {q} lorem ipsum dolor sit amet"] * 200
)


def _padding_block(extension: str, n: int) -> str:
    """Realistic bulk: big comment blocks and long strings, not scope storms."""
    if extension == ".py":
        comment = "# filler documentation line {q} lorem ipsum dolor sit amet\n" * 200
    else:
        comment = _PAD_COMMENT_LINES.format(q=n) + "\n"
    code = _PAD_TEMPLATE.format(p=n, q=n)
    return comment + code + "\n"


def _content(extension: str, rng: random.Random, target: int) -> str:
    blocks = _BLOCKS[extension]
    parts: list[str] = []
    size = 0
    n = 0
    while size < target:
        lines = [line.replace("@N@", str(n)) for line in blocks]
        block = "\n".join(lines) + "\n\n"
        parts.append(block)
        size += len(block)
        n += 1
        if target > 200_000 and size < target:
            pad = _padding_block(extension, n)
            parts.append(pad)
            size += len(pad)
    return "".join(parts)


def generate(
    out_dir: Path,
    files: int,
    max_depth: int,
    seed: int,
    fixed_size: int | None = None,
) -> None:
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    for index in range(files):
        depth = rng.randint(1, max_depth)
        parts = [f"d{rng.randint(0, max_depth)}" for _ in range(depth)]
        extension = EXTENSIONS[index % len(EXTENSIONS)]
        path = out_dir.joinpath(*parts) / f"mod{index:05d}{extension}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if fixed_size is not None:
            target = fixed_size
        else:
            target = min(
                max(int(rng.lognormvariate(7.3, 0.9)), MIN_FILE_SIZE),
                MAX_FILE_SIZE,
            )
        path.write_text(_content(extension, rng, target), encoding="utf-8")

    for depth in (2, max_depth):
        gitignore = out_dir.joinpath(*[f"d{d}" for d in range(depth)]) / ".gitignore"
        if gitignore.parent.exists():
            gitignore.write_text("*.tmp\n", encoding="utf-8")

    total = sum(p.stat().st_size for p in out_dir.rglob("*") if p.is_file())
    print(f"generated {files} files, {total / 1024 / 1024:.1f} MiB in {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="workload name")
    parser.add_argument("--files", type=int, default=2000)
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--fixed-size",
        type=int,
        default=None,
        help="give every file exactly this many bytes",
    )
    args = parser.parse_args()
    out_dir = Path(__file__).resolve().parent / ".trees" / args.name
    generate(out_dir, args.files, args.max_depth, args.seed, args.fixed_size)


if __name__ == "__main__":
    main()
