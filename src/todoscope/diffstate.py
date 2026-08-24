"""New-findings diff baseline (MS-34).

``--diff`` compares the current scan's findings against the fingerprint of
the last scan that also used ``--diff``. The baseline lives in the user
cache directory (never inside the repository), keyed by a hash of the
project root, and is best-effort: unreadable or unwritable state files fail
open and never fail the scan. The baseline always covers the complete scan
— filters such as ``--min-age`` do not affect it.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from todoscope.cache import _cache_base_dir
from todoscope.scan import IndexedFinding

STATE_FILENAME = "findings-state.json"
MAX_PROJECTS = 100
"""Project entries kept before the oldest are pruned."""


def state_path(project_root: Path, *, environ: dict[str, str] | None = None) -> Path:
    """User-level state file for the given project's diff baseline."""
    if environ is None:
        environ = dict(os.environ)
    return _cache_base_dir(environ) / "todoscope" / STATE_FILENAME


def project_key(project_root: Path) -> str:
    """Stable per-project key: hash of the resolved project root."""
    digest = hashlib.sha256()
    digest.update(str(project_root.resolve()).encode("utf-8"))
    return digest.hexdigest()


def finding_key(indexed: IndexedFinding) -> str:
    """Stable identity of one finding, independent of its scan ID."""
    finding = indexed.finding
    return f"{finding.path}:{finding.line}:{finding.marker}:{finding.text}"


def finding_keys(findings: tuple[IndexedFinding, ...]) -> tuple[str, ...]:
    """Sorted finding identities; order-independent and deterministic."""
    return tuple(sorted(finding_key(f) for f in findings))


def diff_sets(
    previous: set[str], current: tuple[str, ...]
) -> tuple[set[str], set[str]]:
    """(new keys, removed keys) between the previous and current scans."""
    current_set = set(current)
    return current_set - previous, previous - current_set


def load_state(path: Path) -> dict[str, Any]:
    """Read the state; any problem yields an empty state."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_state(path: Path, data: dict[str, Any]) -> bool:
    """Write the state; failures are reported, never fatal."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return True
    except OSError:
        return False


def prune_state(data: dict[str, Any], *, max_projects: int = MAX_PROJECTS) -> None:
    """Cap the number of tracked projects, keeping the newest by timestamp."""
    if len(data) <= max_projects:
        return
    ordered = sorted(
        data.items(),
        key=lambda kv: kv[1].get("ts", 0) if isinstance(kv[1], dict) else 0,
        reverse=True,
    )
    for key, _ in ordered[max_projects:]:
        del data[key]


def store_project(
    data: dict[str, Any],
    project_root: Path,
    keys: tuple[str, ...],
    *,
    now: float | None = None,
) -> None:
    """Record the scan fingerprint for a project in the state dict."""
    if now is None:
        now = time.time()
    data[project_key(project_root)] = {"findings": list(keys), "ts": now}


def previous_keys(data: dict[str, Any], project_root: Path) -> set[str]:
    """The stored fingerprint for a project, or an empty set."""
    entry = data.get(project_key(project_root))
    if not isinstance(entry, dict):
        return set()
    keys = entry.get("findings")
    if not isinstance(keys, list):
        return set()
    return set(k for k in keys if isinstance(k, str))
