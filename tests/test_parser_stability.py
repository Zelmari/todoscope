"""Grammar-runtime stability regression test (MS-19 discovery).

tree-sitter core 0.26.0 heap-corrupts when grammars built against older
runtimes parse the same large source repeatedly (free(): invalid pointer /
SIGSEGV). Pinned to core >=0.25.2,<0.26. This test is the canary: it fails
with a crash on the broken combination.
"""

from __future__ import annotations

from todoscope.parsing.comments import Language, extract_comments

_BLOCK = (
    "// TODO: fix @N@\n"
    "const s: string = `// TODO: trap`;\n"
    "export function f@N@(): number { return 1; }\n\n"
)


def _source(blocks: int = 20000) -> str:
    return "".join(_BLOCK.replace("@N@", str(i)) for i in range(blocks))


def test_repeated_parses_of_large_source_do_not_crash() -> None:
    source = _source()
    for _ in range(5):
        comments = extract_comments(source, Language.TYPESCRIPT)
        assert len(comments) == 20000
