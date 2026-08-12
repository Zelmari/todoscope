"""File discovery and exclusion engine (MS-4).

Produces the exact ordered set of permitted source files for a target, after
root ``.gitignore`` rules, custom exclusions, extension filtering, symlink
skipping, and unreadable-file handling.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import pathspec

from todoscope.config import Config

GITIGNORE_SOURCE = "gitignore"
CONFIG_SOURCE = "configuration"


class IgnoredTargetError(Exception):
    """The explicitly requested target is ignored by a rule."""

    def __init__(self, relative: str, source: str, ai_enabled: bool = False) -> None:
        super().__init__(relative)
        self.relative = relative
        self.source = source
        self.ai_enabled = ai_enabled


@dataclass(slots=True)
class ScanStats:
    """Skipped-entry counts for verbose output."""

    scanned: int = 0
    unsupported: int = 0
    ignored_by_gitignore: int = 0
    ignored_by_config: int = 0
    unreadable: int = 0
    symlinks: int = 0


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Allowed files in deterministic order plus scan statistics."""

    files: tuple[Path, ...]
    stats: ScanStats


@dataclass(frozen=True, slots=True)
class Override:
    """Blocking rules to disable for a confirmed explicitly requested target."""

    gitignore_pattern_ids: frozenset[int] = field(default_factory=frozenset)
    config_entries: frozenset[str] = field(default_factory=frozenset)


class ConfirmFn(Protocol):
    def __call__(self, relative: str, source: str, ai_enabled: bool) -> bool: ...


def relative_posix(path: Path, root: Path) -> str:
    """Project-root-relative path using ``/`` separators."""
    return path.relative_to(root).as_posix()


def load_gitignore_spec(project_root: Path) -> pathspec.PathSpec | None:
    gitignore = project_root / ".gitignore"
    if not gitignore.is_file():
        return None
    lines = gitignore.read_text(encoding="utf-8", errors="replace").splitlines()
    return pathspec.GitIgnoreSpec.from_lines(lines)


def _config_exclude_matches(rel: str, entry: str) -> bool:
    entry = entry.rstrip("/")
    return rel == entry or rel.startswith(entry + "/")


def blocking_config_entries(rel: str, entries: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(e for e in entries if _config_exclude_matches(rel, e))


def blocking_gitignore_pattern_ids(
    rel: str, spec: pathspec.PathSpec | None, is_dir: bool
) -> frozenset[int]:
    """Indices of ignore (include) patterns matching ``rel``.

    Negation patterns are never blockers; removing every matching ignore
    pattern is what an explicit-target override needs.
    """
    if spec is None:
        return frozenset()
    probe = rel + "/" if is_dir else rel
    return frozenset(
        index
        for index, pattern in enumerate(spec.patterns)
        if pattern.include and pattern.match_file(probe)
    )


def _gitignore_matches(rel: str, spec: pathspec.PathSpec | None, is_dir: bool) -> bool:
    if spec is None:
        return False
    return spec.match_file(rel + "/" if is_dir else rel)


def _reduced_gitignore_spec(
    spec: pathspec.PathSpec | None, override: Override | None
) -> pathspec.PathSpec | None:
    """Return ``spec`` with the overridden ignore patterns removed.

    Removing whole patterns keeps gitignore negation semantics correct for
    every descendant of the confirmed target.
    """
    if spec is None or override is None or not override.gitignore_pattern_ids:
        return spec
    kept = [
        pattern
        for index, pattern in enumerate(spec.patterns)
        if index not in override.gitignore_pattern_ids
    ]
    return pathspec.PathSpec(kept) if kept else None


def check_ignored(
    target: Path,
    project_root: Path,
    config: Config,
    *,
    spec: pathspec.PathSpec | None = None,
    ai_enabled: bool = False,
) -> IgnoredTargetError | None:
    """Return the blocking rule for an explicitly requested target, if any."""
    if spec is None:
        spec = load_gitignore_spec(project_root)
    rel = relative_posix(target, project_root)
    is_dir = target.is_dir()
    if _gitignore_matches(rel, spec, is_dir):
        return IgnoredTargetError(rel, GITIGNORE_SOURCE, ai_enabled)
    if blocking_config_entries(rel, config.exclude):
        return IgnoredTargetError(rel, CONFIG_SOURCE, ai_enabled)
    return None


def build_override(
    target: Path,
    project_root: Path,
    config: Config,
    *,
    spec: pathspec.PathSpec | None = None,
) -> Override:
    """Disable exactly the rules that blocked the confirmed target."""
    if spec is None:
        spec = load_gitignore_spec(project_root)
    rel = relative_posix(target, project_root)
    return Override(
        gitignore_pattern_ids=blocking_gitignore_pattern_ids(
            rel, spec, target.is_dir()
        ),
        config_entries=frozenset(blocking_config_entries(rel, config.exclude)),
    )


def _blocking_source(
    rel: str,
    is_dir: bool,
    spec: pathspec.PathSpec | None,
    config: Config,
    override: Override | None,
) -> str | None:
    """Return which rule blocks ``rel``.

    ``spec`` must already be the effective spec: reduced by the override.
    """
    if _gitignore_matches(rel, spec, is_dir):
        return GITIGNORE_SOURCE
    entries = blocking_config_entries(rel, config.exclude)
    if override is not None:
        entries = tuple(e for e in entries if e not in override.config_entries)
    if entries:
        return CONFIG_SOURCE
    return None


def discover_files(
    target: Path,
    project_root: Path,
    config: Config,
    *,
    spec: pathspec.PathSpec | None = None,
    override: Override | None = None,
) -> DiscoveryResult:
    """Walk ``target`` and return allowed source files plus stats."""
    if spec is None:
        spec = load_gitignore_spec(project_root)
    spec = _reduced_gitignore_spec(spec, override)

    files: list[Path] = []
    stats = ScanStats()

    def handle_file(path: Path) -> None:
        rel = relative_posix(path, project_root)
        if path.is_symlink():
            stats.symlinks += 1
            return
        source = _blocking_source(rel, False, spec, config, override)
        if source == GITIGNORE_SOURCE:
            stats.ignored_by_gitignore += 1
            return
        if source == CONFIG_SOURCE:
            stats.ignored_by_config += 1
            return
        if path.suffix not in config.extensions:
            stats.unsupported += 1
            return
        if not os.access(path, os.R_OK):
            stats.unreadable += 1
            return
        files.append(path)
        stats.scanned += 1

    if target.is_file():
        handle_file(target)
    else:
        for root, dirnames, filenames in os.walk(target, followlinks=False):
            dirnames.sort(key=str.casefold)
            kept_dirnames: list[str] = []
            for name in dirnames:
                path = Path(root) / name
                if path.is_symlink():
                    stats.symlinks += 1
                    continue
                rel = relative_posix(path, project_root)
                source = _blocking_source(rel, True, spec, config, override)
                if source is not None:
                    if source == GITIGNORE_SOURCE:
                        stats.ignored_by_gitignore += 1
                    else:
                        stats.ignored_by_config += 1
                    continue
                kept_dirnames.append(name)
            dirnames[:] = kept_dirnames
            for name in sorted(filenames, key=str.casefold):
                handle_file(Path(root) / name)

    files.sort(key=lambda p: relative_posix(p, project_root).casefold())
    return DiscoveryResult(files=tuple(files), stats=stats)
