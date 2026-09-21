"""Comment normalisation and marker matching (MS-5).

Turns raw extracted comments (MS-2) into ``Finding`` objects: delimiters and
block decoration are removed, comments are matched against configured markers
with case-sensitive longest-prefix semantics, and adjacent continuation lines
are combined into single findings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from todoscope.config import language_for_suffix
from todoscope.parsing.comments import Comment, Language, extract_comments

_HASH_DELIMITER_LANGUAGES = frozenset(
    {Language.PYTHON, Language.RUBY, Language.SHELL, Language.ELIXIR}
)
_DASH_DELIMITER_LANGUAGES = frozenset({Language.LUA, Language.SQL})

_LUA_BLOCK_OPEN = re.compile(r"^--\[=*\[")
_LUA_BLOCK_CLOSE = re.compile(r"\]=*\]$")

IGNORE_DIRECTIVE = "@ignore"

_CPP_IN_HEADER = re.compile(
    r"\b(?:constexpr|nullptr|namespace|template|co_await|concept)\b|R\""
)


def suppressed_by_directive(text: str) -> bool:
    """True when the comment text carries a standalone ``@ignore`` token.

    The token must be a whole word: ``@ignore`` suppresses a finding, while
    ``x@ignore`` or ``@ignore,`` do not.
    """
    return IGNORE_DIRECTIVE in text.split()


@dataclass(frozen=True, slots=True)
class Finding:
    """One maintenance comment finding.

    ``line`` is the first line of the comment, which is what text reports
    show. ``marker_line`` is the line that contains the marker token, used
    for blame and age. ``end_line`` is the last line of the comment, used by
    SARIF and GitHub Actions. Both extra fields are excluded from equality so
    existing comparisons of marker, text, path, and start line stay stable.
    """

    marker: str
    text: str
    path: str
    line: int
    end_line: int = field(default=0, compare=False)
    marker_line: int = field(default=0, compare=False)

    @property
    def history_line(self) -> int:
        """Line blame and age should attribute. Falls back to ``line``."""
        return self.marker_line or self.line

    @property
    def span_end(self) -> int:
        """Last line of the comment. Falls back to ``line``."""
        return self.end_line or self.line


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


def _decorated_line(line: str) -> str:
    """One block-comment line with leading ``*`` decoration removed."""
    stripped = line.strip()
    star_count = len(stripped) - len(stripped.lstrip("*"))
    if not star_count:
        return stripped
    remainder = stripped[star_count:]
    if remainder[:1].isspace():
        return remainder.lstrip()
    return stripped[1:].lstrip()


def block_marker_line(raw: str, start_line: int, marker: str) -> int:
    """Source line of ``marker`` inside a block comment.

    The finding is still displayed on the comment's first line. Blame has to
    follow the marker, which may sit below the opening delimiter.
    """
    body = raw
    if body.startswith("--["):
        body = _LUA_BLOCK_OPEN.sub("", body, count=1)
        body = _LUA_BLOCK_CLOSE.sub("", body)
    elif body.startswith("/*"):
        body = body[2:]
        if body.endswith("*/"):
            body = body[:-2]
    lines = body.splitlines() or [""]
    for offset, line in enumerate(lines):
        if _decorated_line(line).startswith(marker):
            return start_line + offset
    return start_line


def language_for_source(path: Path, source: str) -> Language | None:
    """Parser for ``path``. ``.h`` files that look like C++ use the C++ grammar."""
    language = language_for_suffix(path.suffix)
    if (
        language is Language.C
        and path.suffix.casefold() == ".h"
        and _CPP_IN_HEADER.search(source)
    ):
        return Language.CPP
    return language


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
                    end_line=open_end_line,
                    marker_line=open_line,
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
                        end_line=comment.end_line,
                        marker_line=block_marker_line(
                            comment.text, comment.start_line, marker
                        ),
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


def findings_for_source(
    source: str,
    path: Path,
    project_root: Path,
    markers: tuple[str, ...],
    data: bytes | None = None,
) -> list[Finding]:
    """Return findings for already-loaded source text.

    ``data`` is the original file bytes when the caller already read them.
    Tree-sitter parses those bytes directly instead of encoding ``source`` again.
    """
    language = language_for_source(path, source)
    if language is None:
        return []
    rel_path = path.relative_to(project_root).as_posix()
    comments = extract_comments(source, language, data)
    return findings_for_comments(comments, language, markers, rel_path)


def findings_for_file(
    path: Path, project_root: Path, markers: tuple[str, ...]
) -> list[Finding]:
    """Read one source file and return its findings in source order."""
    try:
        data = path.read_bytes()
    except OSError:
        return []
    source = data.decode("utf-8", errors="replace")
    return findings_for_source(source, path, project_root, markers, data)
