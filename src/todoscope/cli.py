"""Command-line interface for TodoScope."""

from __future__ import annotations

import argparse
import sys
import time
from importlib.metadata import version
from pathlib import Path

from todoscope.ai import (
    AiEligibility,
    AiSkipReason,
    ai_eligibility,
    build_ai_items,
    effective_limit,
    payload_characters,
)
from todoscope.config import ConfigError, discover_project_root, load_config
from todoscope.discovery import (
    GITIGNORE_SOURCE,
    build_override,
    check_ignored,
    load_gitignore_spec,
)
from todoscope.keys import env_file_is_ignored, load_keys
from todoscope.openai_client import AiRequestError, analyze
from todoscope.report import (
    AI_SKIPPED_NO_AI_FLAG,
    AI_SKIPPED_NO_KEY,
    AI_SKIPPED_NO_MODEL,
    AI_SKIPPED_REQUEST_FAILED,
    AI_SKIPPED_UNSAFE_ENV,
    payload_too_large_message,
    quiet_report,
    standard_report,
    verbose_report,
)
from todoscope.scan import scan

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
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="skip AI analysis and print the local report",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print one finding per line without headings or AI",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print extra scan details to standard error",
    )
    return parser


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


def _ai_skip_line(reason: AiSkipReason, config) -> str | None:
    if reason is AiSkipReason.DISABLED:
        return AI_SKIPPED_NO_AI_FLAG
    if reason is AiSkipReason.NO_MODEL:
        return AI_SKIPPED_NO_MODEL
    if reason is AiSkipReason.UNSAFE_ENV:
        return AI_SKIPPED_UNSAFE_ENV
    if reason is AiSkipReason.PAYLOAD_TOO_LARGE:
        return payload_too_large_message(config)
    if reason is AiSkipReason.NO_KEY:
        return AI_SKIPPED_NO_KEY
    if reason is AiSkipReason.REQUEST_FAILED:
        return AI_SKIPPED_REQUEST_FAILED
    return None


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

    keys = load_keys(root, spec)
    env_ignored = env_file_is_ignored(root, spec)

    started = time.perf_counter()
    findings, stats = scan(target, root, config, spec=spec, override=override)
    duration = time.perf_counter() - started

    eligibility = ai_eligibility(
        config,
        keys,
        len(findings),
        no_ai=args.no_ai,
        quiet=args.quiet,
        env_ignored=env_ignored,
    )
    ai_payload_chars: int | None = None
    items = None
    if eligibility.reason is AiSkipReason.ELIGIBLE:
        items = build_ai_items(findings)
        ai_payload_chars = payload_characters(items)
        if ai_payload_chars > effective_limit(config):
            eligibility = AiEligibility(
                reason=AiSkipReason.PAYLOAD_TOO_LARGE,
                payload_characters=ai_payload_chars,
            )

    ai_result = None
    if eligibility.reason is AiSkipReason.ELIGIBLE:
        try:
            ai_result = analyze(items, config.model, keys.primary)
        except AiRequestError:
            eligibility = AiEligibility(
                reason=AiSkipReason.REQUEST_FAILED,
                payload_characters=ai_payload_chars or 0,
            )

    if args.verbose:
        gitignore = root / ".gitignore"
        gitignore_path = gitignore if gitignore.is_file() else None
        print(
            verbose_report(
                args.path,
                root,
                config,
                stats,
                duration,
                gitignore_path,
                secondary_key_configured=keys.secondary is not None,
                ai_payload_characters=ai_payload_chars,
            ),
            file=sys.stderr,
        )

    if args.quiet:
        report = quiet_report(findings)
    else:
        report = standard_report(
            findings,
            stats.scanned,
            args.path,
            config,
            _ai_skip_line(eligibility.reason, config),
            ai_result,
        )
    print(report)
    return 0


def entrypoint() -> None:
    """Console entry point: convert main's exit code into process status."""
    raise SystemExit(main())
