"""Comment normalisation and marker matching (MS-5).

Turns raw extracted comments (MS-2) into ``Finding`` objects: delimiters and
block decoration are removed, comments are matched against configured markers
with case-sensitive longest-prefix semantics, and adjacent continuation lines
are combined into single findings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from todoscope.config import EXTENSION_LANGUAGES
from todoscope.parsing.comments import Comment, Language, extract_comments

_HASH_DELIMITER_LANGUAGES = frozenset(
    {Language.PYTHON, Language.RUBY, Language.SHELL, Language.ELIXIR}
)
_DASH_DELIMITER_LANGUAGES = frozenset({Language.LUA, Language.SQL})

_LUA_BLOCK_OPEN = re.compile(r"^--\[=*\[")
_LUA_BLOCK_CLOSE = re.compile(r"\]=*\]$")

IGNORE_DIRECTIVE = "@ignore"


def suppressed_by_directive(text: str) -> bool:
    """True when the comment text carries a standalone ``@ignore`` token.

    The token must be a whole word: ``@ignore`` suppresses a finding, while
    ``x@ignore`` or ``@ignore,`` do not.
    """
    return IGNORE_DIRECTIVE in text.split()


@dataclass(frozen=True, slots=True)
class Finding:
    """One maintenance comment finding."""

    marker: str
    text: str
    path: str
    line: int


def marker_prefix(normalised: str, markers: tuple[str, ...]) -> str | None:
    """Return the longest configured marker that prefixes ``normalised``."""
    for marker in sorted(markers, key=len, reverse=True):
        if normalised.startswith(marker):
            return marker
    return None


def strip_marker(normalised: str, marker: str) -> str:
    """Remove the matched marker and any following ``:``/whitespace."""
    remainder = normalised[len(marker) :].strip()
    return remainder.lstrip(":").strip()


def normalise_line_comment(language: Language, raw: str) -> str:
    """Remove line-comment delimiters and leading whitespace."""
    text = raw
    if language is Language.PHP:
        stripped = text.lstrip()
        if stripped.startswith("#"):
            text = stripped.lstrip("#")
        else:
            text = stripped.lstrip("/")
            if text.startswith("!"):
                text = text[1:]
    elif language in _HASH_DELIMITER_LANGUAGES:
        text = text.lstrip("#")
    elif language in _DASH_DELIMITER_LANGUAGES:
        text = text.lstrip("-")
    else:
        text = text.lstrip("/")
        if text.startswith("!"):
            text = text[1:]
    return text.lstrip()


def normalise_block_comment(raw: str) -> str:
    """Remove block delimiters and per-line ``*`` decoration."""
    if raw.startswith("--["):
        interior = _LUA_BLOCK_OPEN.sub("", raw)
        interior = _LUA_BLOCK_CLOSE.sub("", interior).strip()
    else:
        interior = raw[2:-2].strip() if raw.endswith("*/") else raw[2:].strip()
    lines: list[str] = []
    for line in interior.splitlines():
        stripped = line.strip()
        if stripped and set(stripped) == {"*"}:
            continue
        star_count = len(stripped) - len(stripped.lstrip("*"))
        if star_count:
            remainder = stripped[star_count:]
            if remainder[:1].isspace():
                stripped = remainder.lstrip()
            else:
                stripped = stripped[1:].lstrip()
        if stripped:
            lines.append(stripped)
    return " ".join(lines)


def findings_for_comments(
    comments: list[Comment],
    language: Language,
    markers: tuple[str, ...],
    rel_path: str,
) -> list[Finding]:
    """Build findings from extracted comments in source order.

    A marker line starts a group; directly adjacent non-marker line comments
    extend it; a new marker line or a non-adjacent comment closes it. Block
    comments are always standalone findings.
    """
    findings: list[Finding] = []
    open_marker: str | None = None
    open_parts: list[str] = []
    open_line = 0
    open_end_line = 0

    def close_group() -> None:
        nonlocal open_marker, open_parts, open_line, open_end_line
        if open_marker is not None:
            findings.append(
                Finding(
                    marker=open_marker,
                    text=" ".join(open_parts),
                    path=rel_path,
                    line=open_line,
                )
            )
        open_marker = None
        open_parts = []
        open_line = 0
        open_end_line = 0

    for comment in comments:
        if comment.kind == "block":
            close_group()
            text = normalise_block_comment(comment.text)
            marker = marker_prefix(text, markers)
            if marker is not None:
                findings.append(
                    Finding(
                        marker=marker,
                        text=strip_marker(text, marker),
                        path=rel_path,
                        line=comment.start_line,
                    )
                )
            continue

        normalised = normalise_line_comment(language, comment.text)
        marker = marker_prefix(normalised, markers)
        if marker is not None:
            close_group()
            open_marker = marker
            initial = strip_marker(normalised, marker)
            open_parts = [initial] if initial else []
            open_line = comment.start_line
            open_end_line = comment.end_line
        elif open_marker is not None and comment.start_line == open_end_line + 1:
            continuation = normalised.strip()
            if continuation:
                open_parts.append(continuation)
            open_end_line = comment.end_line
        else:
            close_group()
            open_end_line = comment.end_line

    close_group()
    return findings


def findings_for_file(
    path: Path, project_root: Path, markers: tuple[str, ...]
) -> list[Finding]:
    """Read one source file and return its findings in source order."""
    language = EXTENSION_LANGUAGES.get(path.suffix)
    if language is None:
        return []
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rel_path = path.relative_to(project_root).as_posix()
    comments = extract_comments(source, language)
    return findings_for_comments(comments, language, markers, rel_path)
