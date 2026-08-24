"""Git blame attribution (MS-21).

Attribution is gathered per FILE with one ``git blame --porcelain`` call and
kept completely separate from ``Finding`` objects: blame data can never
cross the AI privacy boundary by construction (the payload builder only
reads findings).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from todoscope.scan import IndexedFinding

BLAME_TIMEOUT_SECONDS = 30.0
"""Per-file cap for a single ``git blame`` call."""

BLAME_TOTAL_BUDGET_SECONDS = 120.0
"""Aggregate cap across all blamed files in one scan. Typical files take
~50ms, so the budget is rarely hit; it exists so N files can never sum to
N x 30s. Files past the budget are reported as blame-unavailable."""

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

    @property
    def uncommitted(self) -> bool:
        return len(self.commit) in _OBJECT_ID_LENGTHS and set(self.commit) == {"0"}


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
            elif key == "author-time":
                try:
                    stamp = datetime.fromtimestamp(int(value), tz=UTC)
                    attrs["date"] = stamp.strftime("%Y-%m-%d")
                except (ValueError, OSError):
                    attrs["date"] = ""
            elif key == "committer-time":
                try:
                    stamp = datetime.fromtimestamp(int(value), tz=UTC)
                    attrs["committed_date"] = stamp.strftime("%Y-%m-%d")
                except (ValueError, OSError):
                    attrs["committed_date"] = ""
    finish()
    return result


def blame_for_file(
    path: Path,
    *,
    timeout: float = BLAME_TIMEOUT_SECONDS,
    git: str = "git",
    repo_root: Path | None = None,
) -> dict[int, BlameInfo]:
    """Blame one file with a single porcelain subprocess call.

    ``repo_root`` (the discovered project root) is preferred as the working
    directory so the path passed to git stays repository-root-relative,
    which behaves correctly across submodules and worktrees.
    """
    cwd = repo_root if repo_root is not None else path.parent
    try:
        arg = path.relative_to(cwd).as_posix() if repo_root is not None else path.name
    except ValueError as exc:
        raise BlameError(f"blame path is outside repository root: {path}") from exc
    try:
        completed = subprocess.run(
            [git, "blame", "--porcelain", "--", arg],
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
        info = blames.get(indexed.finding.path, {}).get(indexed.finding.line)
        days = age_days(info, today=today)
        if days is None:
            continue
        if min_age is not None and days < min_age:
            continue
        if max_age is not None and days > max_age:
            continue
        kept.append(indexed)
    return tuple(kept)
