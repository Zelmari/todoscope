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
from datetime import UTC, datetime
from pathlib import Path

BLAME_TIMEOUT_SECONDS = 30.0
"""Per-file cap for a single ``git blame`` call."""

BLAME_TOTAL_BUDGET_SECONDS = 120.0
"""Aggregate cap across all blamed files in one scan. Typical files take
~50ms, so the budget is rarely hit; it exists so N files can never sum to
N x 30s. Files past the budget are reported as blame-unavailable."""

_HEADER_PATTERN = re.compile(r"^[0-9a-f]{40}\b")
_UNCOMMITTED = "0" * 40


class BlameError(Exception):
    """Blame could not be gathered for a file; the scan itself continues."""


@dataclass(frozen=True, slots=True)
class BlameInfo:
    """Who authored one line. Empty fields mean uncommitted/unknown."""

    commit: str
    author: str
    date: str

    @property
    def uncommitted(self) -> bool:
        return self.commit == _UNCOMMITTED


def parse_porcelain(text: str) -> dict[int, BlameInfo]:
    """Parse ``git blame --porcelain`` output into line -> BlameInfo.

    Attributes (author, author-time) belong to a commit and are repeated in
    the output only when the commit changes; later hunks of the same commit
    carry them forward.
    """
    lines = text.splitlines()
    result: dict[int, BlameInfo] = {}
    attrs: dict[str, str] = {}
    last_commit: str | None = None
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
        )
        for line in range(current_start, current_start + current_count):
            result[line] = info
        has_group = False

    for raw in lines:
        if _HEADER_PATTERN.match(raw):
            finish()
            parts = raw.split()
            commit = parts[0]
            if commit != last_commit:
                attrs = {"commit": commit}
                last_commit = commit
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
    arg = path.relative_to(cwd).as_posix() if repo_root is not None else path.name
    try:
        completed = subprocess.run(
            [git, "blame", "--porcelain", "--", arg],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        raise BlameError(f"blame failed for {arg}") from exc
    if completed.returncode != 0:
        raise BlameError(f"blame failed for {arg}: {completed.stderr.strip()}")
    return parse_porcelain(completed.stdout)
