"""Command-line interface for TodoScope."""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import version
from pathlib import Path

from todoscope.config import Config, ConfigError, discover_project_root, load_config
from todoscope.discovery import (
    GITIGNORE_SOURCE,
    build_override,
    check_ignored,
    discover_files,
    load_gitignore_spec,
    relative_posix,
)

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


def _rule_description(source: str) -> str:
    if source == GITIGNORE_SOURCE:
        return "is ignored by .gitignore."
    return "is excluded by .todoscope.json."


def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _prompt_override(relative: str, source: str, ai_enabled: bool) -> bool:
    print()
    print(f"'{relative}' {_rule_description(source)}")
    if ai_enabled:
        print("Extracted comments may be sent to OpenAI.")
    print()
    answer = input("Scan it anyway? [y/N] ")
    return answer.strip().lower() in {"y", "yes"}


def main(
    argv: list[str] | None = None,
    *,
    interactive: bool | None = None,
    confirm=None,
) -> int:
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

    spec = load_gitignore_spec(root)
    ignored = check_ignored(target, root, config, spec=spec)
    override = None
    if ignored is not None:
        if interactive is None:
            interactive = _is_interactive()
        if not interactive:
            print(
                f"Error: '{ignored.relative}' {_rule_description(ignored.source)} "
                "Cannot scan it without confirmation in non-interactive mode.",
                file=sys.stderr,
            )
            return 2
        if confirm is None:
            confirm = _prompt_override
        if not confirm(ignored.relative, ignored.source, ignored.ai_enabled):
            return 0
        override = build_override(target, root, config, spec=spec)

    result = discover_files(target, root, config, spec=spec, override=override)

    print(f"Target: {args.path}")
    print(f"Project root: {root}")
    _describe(config)
    print()
    if result.files:
        print(f"Files to scan ({result.stats.scanned}):")
        for path in result.files:
            print(f"  {relative_posix(path, root)}")
    else:
        print("Files to scan (0)")
    stats = result.stats
    skipped = (
        f"{stats.ignored_by_gitignore} ignored by .gitignore, "
        f"{stats.ignored_by_config} excluded by configuration, "
        f"{stats.unsupported} unsupported, {stats.unreadable} unreadable, "
        f"{stats.symlinks} symlinks"
    )
    print(f"Skipped: {skipped}")
    return 0


def entrypoint() -> None:
    """Console entry point: convert main's exit code into process status."""
    raise SystemExit(main())
