"""Changed-file discovery for --changed (MS-25).

One ``git diff --name-only <ref>`` call per scan returns the tracked files
whose content differs from the given ref (uncommitted changes included;
untracked files are not). Paths are repository-root-relative and are
intersected with the discovered file set, so ignore and extension rules
still apply.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

CHANGED_TIMEOUT_SECONDS = 30.0
"""Per-scan cap for the single ``git diff`` call."""


class ChangedError(Exception):
    """The changed-file set could not be determined."""


def changed_files(
    project_root: Path,
    ref: str,
    *,
    git: str = "git",
    timeout: float = CHANGED_TIMEOUT_SECONDS,
) -> tuple[str, ...]:
    """Repository-root-relative paths of tracked files differing from ``ref``."""
    try:
        return _diff_names(
            project_root, [git, "diff", "--name-only", ref, "--"], timeout
        )
    except ChangedError as exc:
        raise ChangedError(f"unknown ref {ref!r}: {exc}") from exc


def staged_files(
    project_root: Path,
    *,
    git: str = "git",
    timeout: float = CHANGED_TIMEOUT_SECONDS,
) -> tuple[str, ...]:
    """Repository-root-relative paths of files staged for commit."""
    return _diff_names(
        project_root,
        [git, "diff", "--cached", "--name-only", "--"],
        timeout,
    )


def _diff_names(
    project_root: Path, command: list[str], timeout: float
) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            command,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ChangedError("git diff timed out") from exc
    except (FileNotFoundError, OSError) as exc:
        raise ChangedError("git diff failed to run") from exc
    if completed.returncode != 0:
        raise ChangedError(f"git diff failed: {completed.stderr.strip()}")
    return tuple(line for line in completed.stdout.splitlines() if line)
