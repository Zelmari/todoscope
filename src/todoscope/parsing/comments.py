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
  at first use, which broke CI and offline scans).
"""

from __future__ import annotations

import io
import tokenize as pytokenize
from dataclasses import dataclass
from enum import Enum
from typing import Literal

import tree_sitter
import tree_sitter_c as _c
import tree_sitter_c_sharp as _c_sharp
import tree_sitter_cpp as _cpp
import tree_sitter_go as _go
import tree_sitter_java as _java
import tree_sitter_javascript as _javascript
import tree_sitter_rust as _rust
import tree_sitter_typescript as _typescript

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


@dataclass(frozen=True, slots=True)
class Comment:
    """One real code comment with its position."""

    kind: CommentKind
    text: str
    start_line: int
    end_line: int


_TREE_SITTER_COMMENT_TYPES = ("comment", "line_comment", "block_comment")

_LANGUAGE_FACTORIES = {
    Language.JAVASCRIPT: _javascript.language,
    Language.TYPESCRIPT: _typescript.language_typescript,
    Language.TSX: _typescript.language_tsx,
    Language.RUST: _rust.language,
    Language.JAVA: _java.language,
    Language.GO: _go.language,
    Language.C: _c.language,
    Language.CPP: _cpp.language,
    Language.CSHARP: _c_sharp.language,
}


def _parser_for(language: Language) -> tree_sitter.Parser:
    grammar = tree_sitter.Language(_LANGUAGE_FACTORIES[language]())
    return tree_sitter.Parser(grammar)


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


def extract_tree_sitter_comments(source: str, language: Language) -> list[Comment]:
    """Extract real comments from non-Python source using Tree-sitter."""
    parser = _parser_for(language)
    tree = parser.parse(source.encode("utf-8"))

    comments: list[Comment] = []
    stack: list = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in _TREE_SITTER_COMMENT_TYPES:
            text = _decode(node.text)
            text = _strip_trailing_newline(text)
            comments.append(
                Comment(
                    kind="block" if text.startswith("/*") else "line",
                    text=text,
                    start_line=node.start_point.row + 1,
                    end_line=node.end_point.row + 1,
                )
            )
        else:
            stack.extend(reversed(node.children))
    return comments


def extract_comments(source: str, language: Language) -> list[Comment]:
    """Extract all real comments from ``source`` for the given language."""
    if language is Language.PYTHON:
        return extract_python_comments(source)
    return extract_tree_sitter_comments(source, language)
