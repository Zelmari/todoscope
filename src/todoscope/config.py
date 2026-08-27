"""Project-root discovery and ``.todoscope.json`` configuration."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from todoscope.parsing.comments import Language

CONFIG_FILENAME = ".todoscope.json"

HARD_MAX_AI_CHARACTERS = 100_000
"""Provisional ceiling; frozen and documented before version 1.0 (MS-7/MS-10)."""

DEFAULT_MARKERS: tuple[str, ...] = ("TODO",)
DEFAULT_EXTENSIONS: tuple[str, ...] = (".py", ".js", ".jsx", ".ts", ".tsx", ".rs")

EXTENSION_LANGUAGES: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".js": Language.JAVASCRIPT,
    ".jsx": Language.JAVASCRIPT,
    ".ts": Language.TYPESCRIPT,
    ".tsx": Language.TSX,
    ".rs": Language.RUST,
    ".java": Language.JAVA,
    ".go": Language.GO,
    ".c": Language.C,
    ".h": Language.C,
    ".cpp": Language.CPP,
    ".cc": Language.CPP,
    ".cxx": Language.CPP,
    ".hpp": Language.CPP,
    ".cs": Language.CSHARP,
    ".php": Language.PHP,
    ".rb": Language.RUBY,
    ".kt": Language.KOTLIN,
    ".swift": Language.SWIFT,
    ".sh": Language.SHELL,
    ".bash": Language.SHELL,
    ".sql": Language.SQL,
    ".lua": Language.LUA,
    ".zig": Language.ZIG,
    ".dart": Language.DART,
    ".scala": Language.SCALA,
    ".sc": Language.SCALA,
    ".ex": Language.ELIXIR,
    ".exs": Language.ELIXIR,
}

_MARKER_PATTERN = re.compile(r"^[A-Za-z0-9_-]+\Z")


class ConfigError(Exception):
    """Invalid or unusable project configuration."""


@dataclass(frozen=True, slots=True)
class Config:
    """Effective project configuration for one run."""

    path: Path | None
    markers: tuple[str, ...] = DEFAULT_MARKERS
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS
    exclude: tuple[str, ...] = ()
    model: str | None = None
    max_ai_characters: int | None = None


def discover_project_root(target: Path) -> Path:
    """Return the project root for ``target`` (Overarching section 12)."""
    target = Path(os.path.abspath(target))
    start = (
        target.parent
        if target.is_symlink()
        else (target if target.is_dir() else target.parent)
    )

    git_root: Path | None = None
    config_root: Path | None = None
    candidate = start
    while True:
        if (candidate / ".git").exists() and git_root is None:
            git_root = candidate
        if config_root is None and (
            (candidate / CONFIG_FILENAME).exists()
            or (candidate / ".gitignore").exists()
        ):
            config_root = candidate
        if candidate.parent == candidate:
            break
        candidate = candidate.parent

    if git_root is not None:
        return git_root
    if config_root is not None:
        return config_root
    return start


def _validate_markers(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(m, str) for m in value):
        raise ConfigError("'markers' must be a list of strings.")
    for marker in value:
        if not marker:
            raise ConfigError("'markers' contains an empty marker.")
        if not _MARKER_PATTERN.match(marker):
            raise ConfigError(
                f"Invalid marker {marker!r}: markers may contain only letters, "
                "numbers, underscores, or hyphens."
            )
    return tuple(value)


def _validate_extensions(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(e, str) for e in value):
        raise ConfigError("'extensions' must be a list of strings.")
    for extension in value:
        if extension not in EXTENSION_LANGUAGES:
            supported = ", ".join(sorted(EXTENSION_LANGUAGES))
            raise ConfigError(
                f"Extension {extension!r} has no supported parser in this version. "
                f"Supported extensions: {supported}"
            )
    return tuple(value)


def _validate_exclude(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(e, str) for e in value):
        raise ConfigError("'exclude' must be a list of strings.")
    if any(not entry for entry in value):
        raise ConfigError("'exclude' contains an empty entry.")
    return tuple(value)


def _validate_model(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("'model' must be a non-empty string.")
    return value.strip()


def _validate_max_ai_characters(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError("'max_ai_characters' must be a positive integer.")
    if value > HARD_MAX_AI_CHARACTERS:
        raise ConfigError(
            f"'max_ai_characters' ({value}) exceeds the hard ceiling of "
            f"{HARD_MAX_AI_CHARACTERS}."
        )
    return value


def parse_config_text(text: str, path: Path) -> Config:
    """Parse and validate configuration JSON; raise ConfigError on problems."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path.name} contains invalid JSON.") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} must contain a JSON object.")

    markers = DEFAULT_MARKERS
    extensions = DEFAULT_EXTENSIONS
    exclude: tuple[str, ...] = ()
    model: str | None = None
    max_ai_characters: int | None = None

    for key, value in data.items():
        if key == "markers":
            markers = _validate_markers(value)
        elif key == "extensions":
            extensions = _validate_extensions(value)
        elif key == "exclude":
            exclude = _validate_exclude(value)
        elif key == "model":
            model = _validate_model(value)
        elif key == "max_ai_characters":
            max_ai_characters = _validate_max_ai_characters(value)
        else:
            raise ConfigError(f"Unknown configuration key {key!r}.")

    return Config(
        path=path,
        markers=markers,
        extensions=extensions,
        exclude=exclude,
        model=model,
        max_ai_characters=max_ai_characters,
    )


def apply_cli_overrides(
    config: Config,
    *,
    markers: list[str] | None = None,
    extensions: list[str] | None = None,
    exclude: list[str] | None = None,
) -> Config:
    """Apply command-line overrides to an existing Config."""
    new_markers = config.markers
    if markers is not None:
        flat_markers: list[str] = []
        for m in markers:
            for item in m.split(","):
                flat_markers.append(item.strip())
        new_markers = _validate_markers(flat_markers)

    new_extensions = config.extensions
    if extensions is not None:
        flat_exts: list[str] = []
        for e in extensions:
            for item in e.split(","):
                flat_exts.append(item.strip())
        new_extensions = _validate_extensions(flat_exts)

    new_exclude = config.exclude
    if exclude is not None:
        flat_exclude: list[str] = list(config.exclude)
        for ex in exclude:
            for item in ex.split(","):
                flat_exclude.append(item.strip())
        new_exclude = _validate_exclude(flat_exclude)

    return Config(
        path=config.path,
        markers=new_markers,
        extensions=new_extensions,
        exclude=new_exclude,
        model=config.model,
        max_ai_characters=config.max_ai_characters,
    )


def load_config(
    project_root: Path,
    config_file: Path | None = None,
) -> Config:
    """Load configuration from config_file, project root, or defaults."""
    if config_file is not None:
        if not config_file.exists():
            raise ConfigError(f"Configuration file {config_file} does not exist.")
        if config_file.is_dir():
            raise ConfigError(f"Configuration path is a directory: {config_file}")
        try:
            text = config_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ConfigError(f"Cannot read {config_file}: {exc}") from exc
        return parse_config_text(text, config_file)

    config_path = project_root / CONFIG_FILENAME
    if not config_path.exists():
        return Config(path=None)
    try:
        text = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Cannot read {config_path}: {exc}") from exc
    return parse_config_text(text, config_path)
