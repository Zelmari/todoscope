"""Command-line interface for TodoScope."""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import version
from pathlib import Path

from todoscope.config import Config, ConfigError, discover_project_root, load_config

PROG = "todoscope"
DESCRIPTION = "Find maintenance comments in source code."


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser without executing product logic."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=DESCRIPTION,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('todoscope')}",
    )
    parser.add_argument(
        "path",
        help="file or directory to scan",
    )
    return parser


def _describe(config: Config) -> None:
    markers = ", ".join(config.markers) if config.markers else "(none)"
    extensions = ", ".join(config.extensions) if config.extensions else "(none)"
    exclude = ", ".join(config.exclude) if config.exclude else "(none)"
    model = config.model if config.model is not None else "(not configured)"
    limit = (
        config.max_ai_characters
        if config.max_ai_characters is not None
        else "(default hard ceiling)"
    )
    print(f"Configuration: {config.path if config.path else 'defaults'}")
    print(f"  markers: {markers}")
    print(f"  extensions: {extensions}")
    print(f"  exclude: {exclude}")
    print(f"  model: {model}")
    print(f"  max_ai_characters: {limit}")


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and return a numeric exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    target = Path(args.path)
    if not target.exists():
        print(f"Error: '{args.path}' does not exist.", file=sys.stderr)
        return 2

    root = discover_project_root(target)
    try:
        config = load_config(root)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3

    print(f"Target: {args.path}")
    print(f"Project root: {root}")
    _describe(config)
    return 0


def entrypoint() -> None:
    """Console entry point: convert main's exit code into process status."""
    raise SystemExit(main())
