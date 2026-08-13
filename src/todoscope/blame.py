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
    """Parse ``git blame --porcelain`` output into line -> BlameInfo."""
    lines = text.splitlines()
    result: dict[int, BlameInfo] = {}
    current: dict[str, str] | None = None
    current_start = 0
    current_count = 0

    def finish() -> None:
        nonlocal current
        if current is None:
            return
        info = BlameInfo(
            commit=current.get("commit", ""),
            author=current.get("author", ""),
            date=current.get("date", ""),
        )
        for line in range(current_start, current_start + current_count):
            result[line] = info
        current = None

    for raw in lines:
        if _HEADER_PATTERN.match(raw):
            finish()
            parts = raw.split()
            commit = parts[0]
            current_start = int(parts[2])
            current_count = int(parts[3]) if len(parts) > 3 else 1
            current = {"commit": commit}
        elif current is not None:
            key, _, value = raw.partition(" ")
            if key == "author":
                current["author"] = value
            elif key == "author-time":
                try:
                    stamp = datetime.fromtimestamp(int(value), tz=UTC)
                    current["date"] = stamp.strftime("%Y-%m-%d")
                except (ValueError, OSError):
                    current["date"] = ""
    finish()
    return result


def blame_for_file(
    path: Path,
    *,
    timeout: float = BLAME_TIMEOUT_SECONDS,
    git: str = "git",
) -> dict[int, BlameInfo]:
    """Blame one file with a single porcelain subprocess call."""
    try:
        completed = subprocess.run(
            [git, "blame", "--porcelain", "--", path.name],
            cwd=path.parent,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        raise BlameError(f"blame failed for {path.name}") from exc
    if completed.returncode != 0:
        raise BlameError(f"blame failed for {path.name}: {completed.stderr.strip()}")
    return parse_porcelain(completed.stdout)
