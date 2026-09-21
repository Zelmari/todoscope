"""Git blame attribution (MS-21).

Attribution is gathered per FILE with one ``git blame --porcelain`` call and
kept completely separate from ``Finding`` objects: blame data can never
cross the AI privacy boundary by construction (the payload builder only
reads findings).
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path

from todoscope.scan import IndexedFinding

BLAME_TIMEOUT_SECONDS = 30.0
"""Per-file cap for a single ``git blame`` call."""

BLAME_TOTAL_BUDGET_SECONDS = 120.0
"""Aggregate cap across all blamed files in one scan. Typical files take
~50ms, so the budget is rarely hit; it exists so N files can never sum to
N x 30s. Files past the budget are reported as blame-unavailable."""

BLAME_WORKERS = 4
"""Concurrent ``git blame`` processes. Blame is git-bound, so a small pool
fits more files into the wall-clock budget than a serial walk."""

_HEADER_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})(?=\s)")
_OBJECT_ID_LENGTHS = (40, 64)


class BlameError(Exception):
    """Blame could not be gathered for a file; the scan itself continues."""


class BlameTimeoutError(BlameError):
    """Git blame exceeded the timeout assigned to this file."""


@dataclass(frozen=True, slots=True)
class BlameInfo:
    """Who authored one line. Empty fields mean uncommitted/unknown."""

    commit: str
    author: str
    date: str
    committed_date: str
    author_mail: str = ""

    @property
    def uncommitted(self) -> bool:
        return len(self.commit) in _OBJECT_ID_LENGTHS and set(self.commit) == {"0"}


def _local_calendar_date(raw: str) -> str:
    """Calendar date of a git timestamp in the machine's local timezone.

    Age is compared with ``date.today()``, which is local. Storing the UTC
    date instead shifts ``--min-age`` and ``--max-age`` by a day around
    midnight.
    """
    try:
        moment = datetime.fromtimestamp(int(raw), tz=UTC)
    except (ValueError, OSError, OverflowError):
        return ""
    return moment.astimezone().date().isoformat()


def parse_porcelain(text: str) -> dict[int, BlameInfo]:
    """Parse ``git blame --porcelain`` output into line -> BlameInfo.

    Attributes (author, author-time) belong to a commit and are normally
    emitted only on its first appearance. Later hunks reuse a parse-local
    cache, including when other commits appear between them.
    """
    lines = text.splitlines()
    result: dict[int, BlameInfo] = {}
    attrs: dict[str, str] = {}
    commit_attrs: dict[str, dict[str, str]] = {}
    current_start = 0
    current_count = 0
    has_group = False

    def finish() -> None:
        nonlocal has_group
        if not has_group:
            return
        info = BlameInfo(
            commit=attrs.get("commit", ""),
            author=attrs.get("author", ""),
            date=attrs.get("date", ""),
            committed_date=attrs.get("committed_date", ""),
            author_mail=attrs.get("author_mail", ""),
        )
        for line in range(current_start, current_start + current_count):
            result[line] = info
        has_group = False

    for raw in lines:
        if _HEADER_PATTERN.match(raw):
            finish()
            parts = raw.split()
            commit = parts[0]
            attrs = commit_attrs.setdefault(commit, {"commit": commit})
            current_start = int(parts[2])
            current_count = int(parts[3]) if len(parts) > 3 else 1
            has_group = True
        elif has_group:
            key, _, value = raw.partition(" ")
            if key == "author":
                attrs["author"] = value
            elif key == "author-mail":
                attrs["author_mail"] = value.strip("<>")
            elif key == "author-time":
                attrs["date"] = _local_calendar_date(value)
            elif key == "committer-time":
                attrs["committed_date"] = _local_calendar_date(value)
    finish()
    return result


def _line_ranges(lines: Iterable[int]) -> list[tuple[int, int]]:
    """Collapse finding lines into inclusive ``git blame -L`` ranges."""
    ordered = sorted({line for line in lines if line > 0})
    if not ordered:
        return []
    ranges: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for line in ordered[1:]:
        if line == previous + 1:
            previous = line
            continue
        ranges.append((start, previous))
        start = previous = line
    ranges.append((start, previous))
    return ranges


@lru_cache(maxsize=256)
def _git_toplevel(directory: str, git: str) -> str:
    """``git rev-parse --show-toplevel`` for ``directory``, or ``""`` on failure."""
    try:
        completed = subprocess.run(
            [git, "-C", directory, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=BLAME_TIMEOUT_SECONDS,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _blame_location(path: Path, repo_root: Path | None, git: str) -> tuple[Path, str]:
    """Working directory and path argument for ``git blame``.

    A file inside a submodule is blamed from that submodule. Blaming it from
    the parent repository fails, and an age filter then drops the finding.
    """
    if repo_root is None:
        return path.parent, path.name
    try:
        relative = path.relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise BlameError(f"blame path is outside repository root: {path}") from exc
    if path.parent != repo_root:
        top = _git_toplevel(str(path.parent), git)
        if top:
            nested = Path(top)
            if nested != repo_root:
                try:
                    return nested, path.relative_to(nested).as_posix()
                except ValueError:
                    pass
    return repo_root, relative


def blame_for_file(
    path: Path,
    *,
    timeout: float = BLAME_TIMEOUT_SECONDS,
    git: str = "git",
    repo_root: Path | None = None,
    lines: Iterable[int] | None = None,
) -> dict[int, BlameInfo]:
    """Blame one file with a single porcelain subprocess call.

    ``repo_root`` (the discovered project root) is preferred as the working
    directory so the path passed to git stays repository-root-relative.
    Files inside a submodule are blamed from that repository instead.

    ``lines`` limits the call to ``git blame -L`` ranges. Omit it to blame
    the whole file.
    """
    if lines is not None:
        ranges = _line_ranges(lines)
        if not ranges:
            return {}
    else:
        ranges = []
    cwd, arg = _blame_location(path, repo_root, git)
    command = [git, "blame", "--porcelain"]
    for start, end in ranges:
        command.extend(["-L", f"{start},{end}"])
    command.extend(["--", arg])
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BlameTimeoutError(f"blame timed out for {arg}") from exc
    except (FileNotFoundError, OSError) as exc:
        raise BlameError(f"blame failed for {arg}") from exc
    if completed.returncode != 0:
        raise BlameError(f"blame failed for {arg}: {completed.stderr.strip()}")
    return parse_porcelain(completed.stdout)


UNTRACKED = BlameInfo(commit="0" * 40, author="", date="", committed_date="")
"""Stand-in for a line in a file git has never tracked. Age is 0."""


def untracked_paths(repo_root: Path, paths: list[str], *, git: str = "git") -> set[str]:
    """Paths among ``paths`` that are not in the index.

    One ``git ls-files -z`` call. A failure yields an empty set so callers
    keep the previous "blame unavailable" behaviour.
    """
    if not paths:
        return set()
    try:
        completed = subprocess.run(
            [git, "ls-files", "-z", "--", *paths],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=BLAME_TIMEOUT_SECONDS,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return set()
    if completed.returncode != 0:
        return set()
    tracked = {line for line in completed.stdout.split("\0") if line}
    return {path for path in paths if path not in tracked}


def age_days(info: BlameInfo | None, *, today: date | None = None) -> int | None:
    """Days since the line was committed; 0 when uncommitted, None if unknown."""
    if info is None or (not info.uncommitted and not info.committed_date):
        return None
    if info.uncommitted:
        return 0
    if today is None:
        today = date.today()
    committed = date.fromisoformat(info.committed_date)
    return max((today - committed).days, 0)


def filter_by_age(
    findings: tuple[IndexedFinding, ...],
    blames: dict[str, dict[int, BlameInfo]],
    *,
    min_age: int | None,
    max_age: int | None,
    today: date | None = None,
) -> tuple[IndexedFinding, ...]:
    """Keep findings whose committed age satisfies the range.

    Uncommitted lines count as age 0; lines with unavailable history carry
    no age and are excluded whenever a filter is active.
    """
    if min_age is None and max_age is None:
        return findings
    kept: list[IndexedFinding] = []
    for indexed in findings:
        info = blames.get(indexed.finding.path, {}).get(indexed.finding.history_line)
        days = age_days(info, today=today)
        if days is None:
            continue
        if min_age is not None and days < min_age:
            continue
        if max_age is not None and days > max_age:
            continue
        kept.append(indexed)
    return tuple(kept)


def filter_by_author(
    findings: tuple[IndexedFinding, ...],
    blames: dict[str, dict[int, BlameInfo]],
    author_query: str,
) -> tuple[IndexedFinding, ...]:
    """Keep findings whose commit author name or email matches ``author_query``."""
    if not author_query:
        return findings
    query = author_query.lower()
    kept: list[IndexedFinding] = []
    for indexed in findings:
        info = blames.get(indexed.finding.path, {}).get(indexed.finding.history_line)
        if info is None:
            continue
        if query in info.author.lower() or query in info.author_mail.lower():
            kept.append(indexed)
    return tuple(kept)
