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
    _verify_ref(project_root, ref, git=git, timeout=timeout)
    return _diff_names(
        project_root,
        [
            git,
            "diff",
            "-z",
            "--name-only",
            "--no-renames",
            "--end-of-options",
            ref,
            "--",
        ],
        timeout,
    )


def staged_files(
    project_root: Path,
    *,
    git: str = "git",
    timeout: float = CHANGED_TIMEOUT_SECONDS,
) -> tuple[str, ...]:
    """Repository-root-relative paths of files staged for commit.

    Staged deletions are omitted: there is no index blob left to scan.
    """
    return _diff_names(
        project_root,
        [
            git,
            "diff",
            "--cached",
            "-z",
            "--name-only",
            "--no-renames",
            "--diff-filter=ACMR",
            "--",
        ],
        timeout,
    )


def read_index_blob(
    project_root: Path,
    relative: str,
    *,
    git: str = "git",
    timeout: float = CHANGED_TIMEOUT_SECONDS,
) -> str | None:
    """UTF-8 text of the staged blob, or None when it cannot be read."""
    try:
        completed = subprocess.run(
            [git, "cat-file", "blob", f":{relative}"],
            cwd=project_root,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", errors="replace")


def _verify_ref(project_root: Path, ref: str, *, git: str, timeout: float) -> None:
    """Fail with an unknown-ref error before git can treat ``ref`` as an option."""
    try:
        completed = subprocess.run(
            [git, "rev-parse", "--verify", "--quiet", "--end-of-options", ref],
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
        detail = completed.stderr.strip() or "not a revision"
        raise ChangedError(f"unknown ref {ref!r}: {detail}")


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
    return tuple(part for part in completed.stdout.split("\0") if part)
