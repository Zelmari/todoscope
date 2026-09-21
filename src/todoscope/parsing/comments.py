"""Language-aware comment extraction.

Strategy (MS-2 decision, revised MS-17-fix):

- Python: standard-library ``tokenize``. It is lexical, understands raw and
  triple-quoted strings, and never reports string contents as comments. On
  lexical or indentation errors it raises ``TokenError`` or a ``SyntaxError``
  subclass; we stop and return the comments found so far rather than risking
  false positives.
- All other languages: Tree-sitter via the individual grammar packages
  (tree-sitter-javascript, -typescript, -rust, -java, -go, -c, -cpp,
  -c-sharp). Grammars are bundled inside the wheels, so no runtime download
  ever happens (the language-pack alternative fetched binaries from GitHub
  at first use, which broke CI and offline scans). Each grammar is imported
  the first time a file of that language is parsed, and one parser is reused
  for the rest of the process.
"""

from __future__ import annotations

import importlib
import io
import threading
import tokenize as pytokenize
from dataclasses import dataclass
from enum import Enum
from functools import cache
from typing import Literal

import tree_sitter

CommentKind = Literal["line", "block"]


class Language(Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    TSX = "tsx"
    RUST = "rust"
    JAVA = "java"
    GO = "go"
    C = "c"
    CPP = "cpp"
    CSHARP = "csharp"
    PHP = "php"
    RUBY = "ruby"
    KOTLIN = "kotlin"
    SWIFT = "swift"
    SHELL = "shell"
    SQL = "sql"
    LUA = "lua"
    ZIG = "zig"
    DART = "dart"
    SCALA = "scala"
    ELIXIR = "elixir"


@dataclass(frozen=True, slots=True)
class Comment:
    """One real code comment with its position."""

    kind: CommentKind
    text: str
    start_line: int
    end_line: int


_TREE_SITTER_COMMENT_TYPES = (
    "comment",
    "line_comment",
    "block_comment",
    "multiline_comment",
    "marginalia",
    "documentation_comment",
    "doc_comment",
)

# (module, attribute that returns the raw grammar pointer)
_GRAMMARS: dict[Language, tuple[str, str]] = {
    Language.JAVASCRIPT: ("tree_sitter_javascript", "language"),
    Language.TYPESCRIPT: ("tree_sitter_typescript", "language_typescript"),
    Language.TSX: ("tree_sitter_typescript", "language_tsx"),
    Language.RUST: ("tree_sitter_rust", "language"),
    Language.JAVA: ("tree_sitter_java", "language"),
    Language.GO: ("tree_sitter_go", "language"),
    Language.C: ("tree_sitter_c", "language"),
    Language.CPP: ("tree_sitter_cpp", "language"),
    Language.CSHARP: ("tree_sitter_c_sharp", "language"),
    Language.PHP: ("tree_sitter_php", "language_php"),
    Language.RUBY: ("tree_sitter_ruby", "language"),
    Language.KOTLIN: ("tree_sitter_kotlin", "language"),
    Language.SWIFT: ("tree_sitter_swift", "language"),
    Language.SHELL: ("tree_sitter_bash", "language"),
    Language.SQL: ("tree_sitter_sql", "language"),
    Language.LUA: ("tree_sitter_lua", "language"),
    Language.ZIG: ("tree_sitter_zig", "language"),
    Language.DART: ("tree_sitter_dart", "language"),
    Language.SCALA: ("tree_sitter_scala", "language"),
    Language.ELIXIR: ("tree_sitter_elixir", "language"),
}

_PARSE_LOCK = threading.Lock()


@cache
def _grammar(language: Language) -> tree_sitter.Language:
    module_name, attr = _GRAMMARS[language]
    module = importlib.import_module(module_name)
    return tree_sitter.Language(getattr(module, attr)())


@cache
def _parser_for(language: Language) -> tree_sitter.Parser:
    return tree_sitter.Parser(_grammar(language))


@cache
def _comment_query(language: Language) -> tree_sitter.Query | None:
    """Compiled query for the comment node types this grammar actually has."""
    grammar = _grammar(language)
    names = [
        name
        for name in _TREE_SITTER_COMMENT_TYPES
        if grammar.id_for_node_kind(name, True) is not None
    ]
    if not names:
        return None
    source = "\n".join(f"({name}) @comment" for name in names)
    return tree_sitter.Query(grammar, source)


def _decode(node_text: bytes) -> str:
    return node_text.decode("utf-8", errors="replace")


def extract_python_comments(source: str) -> list[Comment]:
    """Extract real comments from Python source using ``tokenize``."""
    comments: list[Comment] = []
    try:
        tokens = pytokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type == pytokenize.COMMENT:
                comments.append(
                    Comment(
                        kind="line",
                        text=token.string.rstrip("\r\n"),
                        start_line=token.start[0],
                        end_line=token.end[0],
                    )
                )
    except (pytokenize.TokenError, SyntaxError):
        # Lexically or structurally broken file: keep what was found and do
        # not guess.
        pass
    return comments


def _strip_trailing_newline(text: str) -> str:
    return text.rstrip("\r\n")


def _outermost(nodes: list[tree_sitter.Node]) -> list[tree_sitter.Node]:
    """Drop comment nodes nested inside another captured comment.

    Rust doc comments are a ``line_comment`` that contains a ``doc_comment``.
    Keeping both would report the same text twice.
    """
    ordered = sorted(
        nodes,
        key=lambda node: (node.start_byte, -(node.end_byte - node.start_byte)),
    )
    kept: list[tree_sitter.Node] = []
    for node in ordered:
        if any(
            earlier.start_byte <= node.start_byte and node.end_byte <= earlier.end_byte
            for earlier in kept
        ):
            continue
        kept.append(node)
    kept.sort(key=lambda node: node.start_byte)
    return kept


def _comment_from_node(node: tree_sitter.Node) -> Comment:
    text = _strip_trailing_newline(_decode(node.text or b""))
    is_block = text.startswith("/*") or text.startswith("--[")
    return Comment(
        kind="block" if is_block else "line",
        text=text,
        start_line=node.start_point.row + 1,
        end_line=node.end_point.row + 1,
    )


def extract_tree_sitter_comments(
    source: str, language: Language, data: bytes | None = None
) -> list[Comment]:
    """Extract real comments from non-Python source using Tree-sitter."""
    raw = data if data is not None else source.encode("utf-8")
    parser = _parser_for(language)
    with _PARSE_LOCK:
        tree = parser.parse(raw)
    query = _comment_query(language)
    if query is None:
        return []
    captured = tree_sitter.QueryCursor(query).captures(tree.root_node)
    nodes = captured.get("comment", [])
    return [_comment_from_node(node) for node in _outermost(nodes)]


def extract_comments(
    source: str, language: Language, data: bytes | None = None
) -> list[Comment]:
    """Extract all real comments from ``source`` for the given language."""
    if language is Language.PYTHON:
        return extract_python_comments(source)
    return extract_tree_sitter_comments(source, language, data)
