"""Command-line interface for TodoScope."""

from __future__ import annotations

import argparse
from importlib.metadata import version

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
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and return a numeric exit code."""
    parser = build_parser()
    parser.parse_args(argv)
    return 0


def entrypoint() -> None:
    """Console entry point: convert main's exit code into process status."""
    raise SystemExit(main())
