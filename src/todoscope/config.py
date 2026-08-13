"""Project-root discovery and ``.todoscope.json`` configuration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from todoscope.parsing.comments import Language

CONFIG_FILENAME = ".todoscope.json"
ENV_FILENAME = ".env"

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
    start = target if target.is_dir() else target.parent

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
    if not isinstance(value, str) or not value:
        raise ConfigError("'model' must be a non-empty string.")
    return value


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


def load_config(project_root: Path) -> Config:
    """Load configuration from the project root, or return defaults."""
    config_path = project_root / CONFIG_FILENAME
    if not config_path.exists():
        return Config(path=None)
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read {config_path}: {exc}") from exc
    return parse_config_text(text, config_path)
