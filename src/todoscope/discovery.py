"""File discovery and exclusion engine (MS-4/14).

Produces the exact ordered set of permitted source files for a target,
applying every ``.gitignore`` from the project root down to each directory
(git semantics: deeper files override earlier ones, patterns are relative to
their own directory), custom exclusions, extension filtering, symlink
skipping, and unreadable-file handling.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import pathspec

from todoscope.config import Config, ConfigError

GITIGNORE_SOURCE = "gitignore"
CONFIG_SOURCE = "configuration"

_MISSING = object()


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
    serial_retry_chunks: int = 0
    """Chunks re-run serially because a pool worker crashed."""


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Allowed files in deterministic order plus scan statistics."""

    files: tuple[Path, ...]
    stats: ScanStats


@dataclass(frozen=True, slots=True)
class IgnoreSource:
    """One .gitignore file and the directory its patterns are relative to."""

    base: Path
    spec: pathspec.PathSpec


@dataclass(frozen=True, slots=True)
class Override:
    """Blocking rules to disable for a confirmed explicitly requested target."""

    gitignore_keys: frozenset[tuple[str, int]] = field(default_factory=frozenset)
    config_entries: frozenset[str] = field(default_factory=frozenset)


class ConfirmFn(Protocol):
    def __call__(self, relative: str, source: str, ai_enabled: bool) -> bool: ...


def relative_posix(path: Path, root: Path) -> str:
    """Project-root-relative path using ``/`` separators."""
    return path.relative_to(root).as_posix()


def load_gitignore_spec(directory: Path) -> pathspec.PathSpec | None:
    gitignore = directory / ".gitignore"
    try:
        lines = gitignore.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ConfigError(f"Cannot read {gitignore}: {exc}") from exc
    return pathspec.GitIgnoreSpec.from_lines(lines)


def target_has_symlink_component(target: Path, project_root: Path) -> bool:
    """True when the requested path crosses a symlink below its project root."""
    try:
        relative = target.relative_to(project_root)
    except ValueError:
        return True
    current = project_root
    if current.is_symlink():
        return True
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _chain_for(
    project_root: Path,
    directory: Path,
    root_spec: pathspec.PathSpec | None,
    cache: dict[Path, object],
) -> tuple[IgnoreSource, ...]:
    """Ignore sources from the project root down to ``directory`` inclusive."""
    chain: list[IgnoreSource] = []
    if root_spec is not None:
        chain.append(IgnoreSource(project_root, root_spec))
    current = project_root
    for part in directory.relative_to(project_root).parts:
        current = current / part
        spec = cache.get(current, _MISSING)
        if spec is _MISSING:
            spec = load_gitignore_spec(current)
            cache[current] = spec
        if spec is not None:
            chain.append(IgnoreSource(current, spec))
    return tuple(chain)


def _matching_include_keys(
    chain: tuple[IgnoreSource, ...], path: Path, is_dir: bool
) -> frozenset[tuple[str, int]]:
    """All ignore (include) patterns matching ``path`` across the chain."""
    keys: set[tuple[str, int]] = set()
    for source in chain:
        rel = path.relative_to(source.base).as_posix()
        probe = rel + "/" if is_dir else rel
        for index, pattern in enumerate(source.spec.patterns):
            if pattern.include and pattern.match_file(probe):
                keys.add((source.base.as_posix(), index))
    return frozenset(keys)


def _is_ignored(
    chain: tuple[IgnoreSource, ...],
    path: Path,
    is_dir: bool,
    override: Override | None,
) -> bool:
    """Git algorithm: deeper sources override; last match within a source wins."""
    ignored = False
    for source in chain:
        rel = path.relative_to(source.base).as_posix()
        probe = rel + "/" if is_dir else rel
        last_match = None
        for index, pattern in enumerate(source.spec.patterns):
            if (
                override is not None
                and (source.base.as_posix(), index) in override.gitignore_keys
            ):
                continue
            if pattern.match_file(probe):
                last_match = pattern
        if last_match is not None:
            ignored = last_match.include
    return ignored


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
    parent = target.parent
    if not parent.is_relative_to(project_root):
        parent = project_root
    chain = _chain_for(project_root, parent, spec, {})
    rel = relative_posix(target, project_root)
    if _is_ignored(chain, target, target.is_dir(), None):
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
    parent = target.parent
    if not parent.is_relative_to(project_root):
        parent = project_root
    chain = _chain_for(project_root, parent, spec, {})
    rel = relative_posix(target, project_root)
    return Override(
        gitignore_keys=_matching_include_keys(chain, target, target.is_dir()),
        config_entries=frozenset(blocking_config_entries(rel, config.exclude)),
    )


def _config_exclude_matches(rel: str, entry: str) -> bool:
    entry = entry.rstrip("/")
    return rel == entry or rel.startswith(entry + "/")


def blocking_config_entries(rel: str, entries: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(e for e in entries if _config_exclude_matches(rel, e))


def _blocking_source(
    rel: str,
    chain: tuple[IgnoreSource, ...],
    path: Path,
    is_dir: bool,
    config: Config,
    override: Override | None,
) -> str | None:
    """Return which rule blocks ``rel``; chain must end at its directory."""
    if _is_ignored(chain, path, is_dir, override):
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
    files: list[Path] = []
    stats = ScanStats()
    if target_has_symlink_component(target, project_root):
        stats.symlinks = 1
        return DiscoveryResult(files=(), stats=stats)

    if spec is None:
        spec = load_gitignore_spec(project_root)
    spec_cache: dict[Path, object] = {}

    def handle_file(path: Path, chain: tuple[IgnoreSource, ...]) -> None:
        rel = relative_posix(path, project_root)
        if path.is_symlink():
            stats.symlinks += 1
            return
        source = _blocking_source(rel, chain, path, False, config, override)
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
        parent_chain = _chain_for(project_root, target.parent, spec, spec_cache)
        handle_file(target, parent_chain)
    else:
        root_chain = _chain_for(project_root, target, spec, spec_cache)
        stack: list[tuple[Path, tuple[IgnoreSource, ...]]] = [(target, root_chain)]
        while stack:
            directory, chain = stack.pop()
            try:
                entries = list(os.scandir(directory))
            except OSError:
                stats.unreadable += 1
                continue
            subdirs: list[tuple[Path, tuple[IgnoreSource, ...]]] = []
            for entry in entries:
                if entry.is_symlink():
                    stats.symlinks += 1
                    continue
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    rel = relative_posix(path, project_root)
                    source = _blocking_source(rel, chain, path, True, config, override)
                    if source is not None:
                        if source == GITIGNORE_SOURCE:
                            stats.ignored_by_gitignore += 1
                        else:
                            stats.ignored_by_config += 1
                        continue
                    child_spec = spec_cache.get(path, _MISSING)
                    if child_spec is _MISSING:
                        child_spec = load_gitignore_spec(path)
                        spec_cache[path] = child_spec
                    if child_spec is not None:
                        subdirs.append(
                            (path, chain + (IgnoreSource(path, child_spec),))
                        )
                    else:
                        subdirs.append((path, chain))
                else:
                    handle_file(path, chain)
            for sub in sorted(subdirs, key=lambda t: (t[0].name.casefold(), t[0].name)):
                stack.append(sub)

    files.sort(
        key=lambda p: (
            relative_posix(p, project_root).casefold(),
            relative_posix(p, project_root),
        )
    )
    return DiscoveryResult(files=tuple(files), stats=stats)
