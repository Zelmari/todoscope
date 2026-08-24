"""Command-line interface for TodoScope."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import shutil
import sys
import time
from importlib.metadata import version
from pathlib import Path

from todoscope.ai import (
    AiEligibility,
    AiSkipReason,
    AnalysisResult,
    ai_eligibility,
    build_ai_items,
    effective_limit,
    payload_characters,
)
from todoscope.blame import (
    BLAME_TIMEOUT_SECONDS,
    BLAME_TOTAL_BUDGET_SECONDS,
    BlameError,
    BlameInfo,
    BlameTimeoutError,
    blame_for_file,
)
from todoscope.config import Config, ConfigError, discover_project_root, load_config
from todoscope.discovery import (
    GITIGNORE_SOURCE,
    ConfirmFn,
    build_override,
    check_ignored,
    load_gitignore_spec,
    target_has_symlink_component,
)
from todoscope.keys import env_file_is_ignored, load_keys
from todoscope.openai_client import (
    AiOutcomeKind,
    ConfirmSecondaryFn,
    StatusFactory,
    run_ai_analysis,
)
from todoscope.report import (
    AI_SKIPPED_NO_KEY,
    AI_SKIPPED_NO_MODEL,
    AI_SKIPPED_NONINTERACTIVE,
    AI_SKIPPED_REQUEST_FAILED,
    AI_SKIPPED_SECONDARY_FAILED,
    AI_SKIPPED_SECRETS,
    AI_SKIPPED_UNSAFE_ENV,
    QUIET_AI_CONFLICT,
    json_report,
    payload_too_large_message,
    quiet_report,
    secrets_skip_line,
    standard_report,
    verbose_report,
)
from todoscope.sarif import sarif_report
from todoscope.scan import scan
from todoscope.secrets import findings_with_secrets
from todoscope.status import StatusContext

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
        "--ai",
        action="store_true",
        help="interpret findings with the configured AI model",
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
    parser.add_argument(
        "--format",
        choices=("text", "json", "sarif"),
        default="text",
        help="output format (default: text)",
    )
    parser.add_argument(
        "--blame",
        action="store_true",
        help="show who authored each finding via git blame",
    )
    parser.add_argument(
        "--age",
        action="store_true",
        help="show time since each finding's line was committed",
    )
    return parser


def _rule_description(source: str) -> str:
    if source == GITIGNORE_SOURCE:
        return "is ignored by .gitignore."
    return "is excluded by .todoscope.json."


def _is_interactive() -> bool:
    try:
        stdin_tty = getattr(sys.stdin, "isatty", lambda: False)()
        stdout_tty = getattr(sys.stdout, "isatty", lambda: False)()
    except (OSError, ValueError):
        return False
    return bool(stdin_tty and stdout_tty)


def _prompt_override(relative: str, source: str, ai_enabled: bool) -> bool:
    print()
    print(f"'{relative}' {_rule_description(source)}")
    if ai_enabled:
        print("Extracted comments may be sent to OpenAI.")
    print()
    answer = input("Scan it anyway? [y/N] ")
    return answer.strip().lower() in {"y", "yes"}


def _prompt_secondary() -> bool:
    print()
    print("The primary AI request failed.")
    print()
    answer = input("Try the configured secondary API key? [y/N] ")
    return answer.strip().lower() in {"y", "yes"}


def _ai_skip_line(reason: AiSkipReason, config: Config) -> str | None:
    if reason is AiSkipReason.NO_MODEL:
        return AI_SKIPPED_NO_MODEL
    if reason is AiSkipReason.UNSAFE_ENV:
        return AI_SKIPPED_UNSAFE_ENV
    if reason is AiSkipReason.PAYLOAD_TOO_LARGE:
        return payload_too_large_message(config)
    if reason is AiSkipReason.NO_KEY:
        return AI_SKIPPED_NO_KEY
    if reason is AiSkipReason.SECRETS_FOUND:
        return AI_SKIPPED_SECRETS
    return None


def _outcome_skip_line(kind: AiOutcomeKind) -> str:
    if kind is AiOutcomeKind.NONINTERACTIVE:
        return AI_SKIPPED_NONINTERACTIVE
    if kind is AiOutcomeKind.SECONDARY_FAILED:
        return AI_SKIPPED_SECONDARY_FAILED
    return AI_SKIPPED_REQUEST_FAILED


def _json_ai_state(
    reason: AiSkipReason,
    outcome_kind: AiOutcomeKind | None,
    ai_result: AnalysisResult | None,
) -> tuple[str | None, str | None]:
    """Map AI outcome to JSON status/reason, never exposing keys."""
    if ai_result is not None:
        return None, None
    if outcome_kind is not None:
        if outcome_kind is AiOutcomeKind.SUCCESS:
            return None, None
        return "failed", outcome_kind.value
    if reason is AiSkipReason.NOT_REQUESTED or reason is AiSkipReason.ELIGIBLE:
        return None, None
    return "skipped", reason.value


def main(
    argv: list[str] | None = None,
    *,
    interactive: bool | None = None,
    confirm: ConfirmFn | None = None,
    confirm_secondary: ConfirmSecondaryFn | None = None,
    status: StatusFactory | None = None,
) -> int:
    """Parse arguments and return a numeric exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    target = Path(os.path.abspath(args.path))
    if not target.exists():
        print(f"Error: '{args.path}' does not exist.", file=sys.stderr)
        return 2

    root = discover_project_root(target)
    try:
        config = load_config(root)
        symlink_target = target_has_symlink_component(target, root)
        spec = None if symlink_target else load_gitignore_spec(root)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3

    if interactive is None:
        interactive = _is_interactive()
    ignored = (
        None
        if symlink_target
        else check_ignored(
            target,
            root,
            config,
            spec=spec,
            ai_enabled=args.ai and not args.quiet,
        )
    )
    override = None
    if ignored is not None:
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
    try:
        findings, stats = scan(target, root, config, spec=spec, override=override)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3
    duration = time.perf_counter() - started

    if args.quiet and args.ai:
        print(QUIET_AI_CONFLICT, file=sys.stderr)
    if args.quiet and args.blame:
        print("--quiet and --blame cannot be used together.", file=sys.stderr)
    if args.quiet and args.age:
        print("--quiet and --age cannot be used together.", file=sys.stderr)

    do_history = (args.blame or args.age) and not args.quiet
    if do_history:
        option = "--blame" if args.blame else "--age"
        if not (root / ".git").exists():
            print(f"Error: {option} requires a Git repository.", file=sys.stderr)
            return 2
        if shutil.which("git") is None:
            print(f"Error: {option} requires the git executable.", file=sys.stderr)
            return 2

    eligibility = ai_eligibility(
        config,
        keys,
        len(findings),
        ai_requested=args.ai and not args.quiet,
        env_ignored=env_ignored,
    )
    ai_payload_chars: int | None = None
    items = None
    secrets_found_line: str | None = None
    if eligibility.reason is AiSkipReason.ELIGIBLE:
        secret_findings = findings_with_secrets(findings)
        if secret_findings:
            eligibility = AiEligibility(reason=AiSkipReason.SECRETS_FOUND)
            secrets_found_line = secrets_skip_line(secret_findings)
        else:
            items = build_ai_items(findings)
            ai_payload_chars = payload_characters(items)
            if ai_payload_chars > effective_limit(config):
                eligibility = AiEligibility(
                    reason=AiSkipReason.PAYLOAD_TOO_LARGE,
                    payload_characters=ai_payload_chars,
                )

    ai_result = None
    ai_failure_line: str | None = None
    outcome_kind: AiOutcomeKind | None = None
    if eligibility.reason is AiSkipReason.ELIGIBLE:
        assert items is not None
        assert config.model is not None
        if status is None:
            status = StatusContext
        if confirm_secondary is None:
            confirm_secondary = _prompt_secondary
        outcome = run_ai_analysis(
            items,
            config.model,
            keys,
            interactive=interactive,
            confirm_secondary=confirm_secondary,
            status=status,
        )
        outcome_kind = outcome.kind
        if outcome.kind is AiOutcomeKind.SUCCESS:
            ai_result = outcome.result
        else:
            ai_failure_line = _outcome_skip_line(outcome.kind)

    blames: dict[str, dict[int, BlameInfo]] | None = None
    blame_missing = 0
    blame_budget_exceeded = False
    if do_history:
        blames = {}
        paths = sorted({indexed.finding.path for indexed in findings})
        blame_started = time.monotonic()
        for index, rel_path in enumerate(paths):
            elapsed = time.monotonic() - blame_started
            remaining = BLAME_TOTAL_BUDGET_SECONDS - elapsed
            if remaining <= 0:
                blame_budget_exceeded = True
                break
            timeout = min(BLAME_TIMEOUT_SECONDS, remaining)
            budget_limited = remaining <= BLAME_TIMEOUT_SECONDS
            try:
                blames[rel_path] = blame_for_file(
                    root / rel_path,
                    repo_root=root,
                    timeout=timeout,
                )
            except BlameTimeoutError:
                if budget_limited:
                    blame_budget_exceeded = True
                    break
            except BlameError:
                pass
            if (
                index < len(paths) - 1
                and time.monotonic() - blame_started >= BLAME_TOTAL_BUDGET_SECONDS
            ):
                blame_budget_exceeded = True
                break
        blame_missing = len(paths) - len(blames)

    if args.verbose:
        gitignore = root / ".gitignore"
        gitignore_path = gitignore if gitignore.is_file() else None
        blame_kwargs = (
            {
                "blame_files": len(blames),
                "blame_unavailable": blame_missing,
                "blame_budget_exceeded": blame_budget_exceeded,
            }
            if blames is not None
            else {}
        )
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
                serial_retried_chunks=stats.serial_retry_chunks,
                **blame_kwargs,
            ),
            file=sys.stderr,
        )

    if args.quiet:
        report = quiet_report(findings)
    else:
        skip_line = (
            ai_failure_line
            or secrets_found_line
            or _ai_skip_line(eligibility.reason, config)
        )
        report = standard_report(
            findings,
            stats.scanned,
            args.path,
            config,
            skip_line,
            ai_result,
            blames if args.blame else None,
            blames if args.age else None,
        )

    if args.format == "json":
        ai_status, ai_reason = _json_ai_state(
            eligibility.reason, outcome_kind, ai_result
        )
        data = json_report(
            findings,
            stats.scanned,
            args.path,
            root,
            config,
            stats,
            ai_result,
            ai_status,
            ai_reason,
            blames if args.blame else None,
            blames if args.age else None,
        )
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    if args.format == "sarif":
        data = sarif_report(
            findings,
            config,
            files_scanned=stats.scanned,
            ai_result=ai_result,
            blames=blames if args.blame else None,
            ages=blames if args.age else None,
        )
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    print(report)
    return 0


def entrypoint() -> None:
    """Console entry point: convert main's exit code into process status."""
    multiprocessing.freeze_support()
    raise SystemExit(main())
