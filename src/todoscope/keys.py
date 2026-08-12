"""API key loading and ``.env`` safety (MS-7)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pathspec

PRIMARY_ENV_VAR = "TODOSCOPE_API_KEY"
SECONDARY_ENV_VAR = "TODOSCOPE_SECONDARY_API_KEY"
ENV_FILENAME = ".env"

KeySource = Literal["shell", "env_file", "none"]


@dataclass(frozen=True, slots=True)
class KeyInfo:
    """Loaded keys with their sources; values never printed."""

    primary: str | None
    primary_source: KeySource
    secondary: str | None
    secondary_source: KeySource

    @property
    def uses_env_file(self) -> bool:
        return self.primary_source == "env_file" or self.secondary_source == "env_file"


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse a minimal ``.env`` subset: KEY=VALUE lines only."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def _read_env_file(project_root: Path) -> dict[str, str]:
    env_path = project_root / ENV_FILENAME
    if not env_path.is_file():
        return {}
    try:
        return parse_dotenv(env_path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}


def load_keys(
    project_root: Path,
    spec: pathspec.PathSpec | None,
    environ: dict[str, str] | None = None,
) -> KeyInfo:
    """Load keys: shell environment wins; project ``.env`` fills missing."""
    if environ is None:
        import os

        environ = dict(os.environ)
    env_values = _read_env_file(project_root)

    primary = environ.get(PRIMARY_ENV_VAR)
    primary_source: KeySource = "shell" if primary else "none"
    if primary is None and PRIMARY_ENV_VAR in env_values:
        primary = env_values[PRIMARY_ENV_VAR]
        primary_source = "env_file"

    secondary = environ.get(SECONDARY_ENV_VAR)
    secondary_source: KeySource = "shell" if secondary else "none"
    if secondary is None and SECONDARY_ENV_VAR in env_values:
        secondary = env_values[SECONDARY_ENV_VAR]
        secondary_source = "env_file"

    return KeyInfo(
        primary=primary,
        primary_source=primary_source,
        secondary=secondary,
        secondary_source=secondary_source,
    )


def env_file_is_ignored(project_root: Path, spec: pathspec.PathSpec | None) -> bool:
    """True when the project ``.env`` is ignored by the root ``.gitignore``."""
    if spec is None:
        return False
    return spec.match_file(ENV_FILENAME)
