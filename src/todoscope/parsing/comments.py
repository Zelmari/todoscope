"""Language-aware comment extraction.

Strategy (MS-2 decision):

- Python: standard-library ``tokenize``. It is lexical, understands raw and
  triple-quoted strings, and never reports string contents as comments. On
  lexical errors (e.g. an unterminated multiline string) it raises
  ``TokenError``; we stop and return the comments found so far rather than
  risking false positives.
- JavaScript, TypeScript, TSX, Rust: Tree-sitter via
  ``tree-sitter-language-pack``. Grammar-aware parsing correctly separates
  comments from template literals, JSX text, and raw strings, and tolerates
  syntax errors.
"""

from __future__ import annotations

import io
import tokenize as pytokenize
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from tree_sitter_language_pack import get_parser

CommentKind = Literal["line", "block"]


class Language(Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    TSX = "tsx"
    RUST = "rust"


@dataclass(frozen=True, slots=True)
class Comment:
    """One real code comment with its position."""

    kind: CommentKind
    text: str
    start_line: int
    end_line: int


_TREE_SITTER_COMMENT_TYPES = ("comment", "line_comment", "block_comment")


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
    except pytokenize.TokenError:
        # Lexically broken file (e.g. unterminated string): keep what was
        # found and do not guess.
        pass
    return comments


def _strip_trailing_newline(text: str) -> str:
    return text.rstrip("\r\n")


def extract_tree_sitter_comments(source: str, language: Language) -> list[Comment]:
    """Extract real comments from JS/TS/TSX/Rust source using Tree-sitter."""
    parser = get_parser(language.value)
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
