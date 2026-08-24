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
    oversized_item,
    payload_characters,
)
from todoscope.blame import (
    BLAME_TIMEOUT_SECONDS,
    BLAME_TOTAL_BUDGET_SECONDS,
    BlameError,
    BlameInfo,
    BlameTimeoutError,
    blame_for_file,
    filter_by_age,
)
from todoscope.cache import cache_path, load_cache, run_chunked_analysis, save_cache
from todoscope.changed import ChangedError, changed_files, staged_files
from todoscope.config import Config, ConfigError, discover_project_root, load_config
from todoscope.diffstate import (
    diff_sets,
    finding_key,
    finding_keys,
    load_state,
    previous_keys,
    prune_state,
    save_state,
    state_path,
    store_project,
)
from todoscope.discovery import (
    GITIGNORE_SOURCE,
    ConfirmFn,
    build_override,
    check_ignored,
    load_gitignore_spec,
    target_has_symlink_component,
)
from todoscope.extraction import suppressed_by_directive
from todoscope.gha import gha_report
from todoscope.keys import env_file_is_ignored, load_keys
from todoscope.openai_client import (
    AiOutcomeKind,
    ConfirmSecondaryFn,
    StatusFactory,
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
    SecretEntries,
    json_report,
    payload_too_large_message,
    quiet_report,
    secrets_skip_line,
    standard_report,
    verbose_report,
)
from todoscope.sarif import sarif_report
from todoscope.scan import IndexedFinding, scan
from todoscope.secrets import findings_with_secrets, secret_entries
from todoscope.status import StatusContext

PROG = "todoscope"
DESCRIPTION = "Find maintenance comments in source code."

FINDINGS_GATE_EXIT_CODE = 4
"""Exit code when the opt-in --fail/--fail-count gate is tripped."""


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
        nargs="?",
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
        choices=("text", "json", "sarif", "github-actions"),
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
    parser.add_argument(
        "--min-age",
        type=int,
        metavar="DAYS",
        help="keep only findings at least this many days old",
    )
    parser.add_argument(
        "--max-age",
        type=int,
        metavar="DAYS",
        help="keep only findings at most this many days old",
    )
    parser.add_argument(
        "--changed",
        metavar="REF",
        help="scan only tracked files whose content differs from this git ref",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="scan only files staged for commit",
    )
    parser.add_argument(
        "--install-hook",
        action="store_true",
        help="install a pre-commit hook that gates staged findings",
    )
    parser.add_argument(
        "--uninstall-hook",
        action="store_true",
        help="remove the pre-commit hook installed by todoscope",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="report findings added since the last scan",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="ignore the local AI result cache",
    )
    parser.add_argument(
        "--check-secrets",
        action="store_true",
        help="list findings whose comment text looks like a credential",
    )
    parser.add_argument(
        "--fail",
        action="store_true",
        help="exit with code 4 when any findings remain",
    )
    parser.add_argument(
        "--fail-count",
        type=int,
        metavar="N",
        help="exit with code 4 when more than N findings remain",
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


HOOK_MARKER = "# installed by todoscope"
HOOK_SCRIPT = f"""#!/bin/sh
{HOOK_MARKER}
exec todoscope . --staged --quiet --fail
"""


def _hook_path(root: Path) -> Path | None:
    git_dir = root / ".git"
    if not git_dir.is_dir():
        return None
    return git_dir / "hooks" / "pre-commit"


def _install_hook(root: Path) -> int:
    hook = _hook_path(root)
    if hook is None:
        print(
            "Error: --install-hook requires a regular Git repository "
            "(worktrees are not supported).",
            file=sys.stderr,
        )
        return 2
    try:
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(HOOK_SCRIPT, encoding="utf-8")
        hook.chmod(0o755)
    except OSError as exc:
        print(f"Error: could not write the pre-commit hook: {exc}", file=sys.stderr)
        return 1
    print(f"Installed pre-commit hook at {hook}")
    return 0


def _uninstall_hook(root: Path) -> int:
    hook = _hook_path(root)
    if hook is None:
        print(
            "Error: --uninstall-hook requires a regular Git repository "
            "(worktrees are not supported).",
            file=sys.stderr,
        )
        return 2
    if not hook.exists():
        print("No todoscope pre-commit hook is installed.")
        return 0
    try:
        content = hook.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error: cannot read {hook}: {exc}", file=sys.stderr)
        return 1
    if HOOK_MARKER not in content:
        print(
            f"Error: {hook} is not a todoscope hook; refusing to remove it.",
            file=sys.stderr,
        )
        return 2
    try:
        hook.unlink()
    except OSError as exc:
        print(f"Error: could not remove the pre-commit hook: {exc}", file=sys.stderr)
        return 1
    print(f"Removed pre-commit hook at {hook}")
    return 0


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

    if args.fail and args.fail_count is not None:
        parser.error("--fail and --fail-count cannot be used together.")
    if args.fail_count is not None and args.fail_count < 0:
        print("Error: --fail-count must be a non-negative integer.", file=sys.stderr)
        return 2
    if args.install_hook and args.uninstall_hook:
        parser.error("--install-hook and --uninstall-hook cannot be used together.")
    if args.install_hook or args.uninstall_hook:
        root = discover_project_root(Path.cwd())
        if args.install_hook:
            return _install_hook(root)
        return _uninstall_hook(root)
    if args.path is None:
        parser.error("the following arguments are required: path")

    for option, value in (("--min-age", args.min_age), ("--max-age", args.max_age)):
        if value is not None and value < 0:
            print(
                f"Error: {option} must be a non-negative number of days.",
                file=sys.stderr,
            )
            return 2

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

    if args.staged and args.changed is not None:
        parser.error("--staged and --changed cannot be used together.")
    changed_set: set[str] | None = None
    if args.staged or args.changed is not None:
        option = "--staged" if args.staged else "--changed"
        if not (root / ".git").exists():
            print(f"Error: {option} requires a Git repository.", file=sys.stderr)
            return 2
        if shutil.which("git") is None:
            print(f"Error: {option} requires the git executable.", file=sys.stderr)
            return 2
        try:
            if args.staged:
                changed_set = set(staged_files(root))
            else:
                assert args.changed is not None
                changed_set = set(changed_files(root, args.changed))
        except ChangedError as exc:
            print(f"Error: {option} failed: {exc}", file=sys.stderr)
            return 2

    started = time.perf_counter()
    try:
        findings, stats = scan(
            target,
            root,
            config,
            spec=spec,
            override=override,
            changed=changed_set,
        )
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3
    duration = time.perf_counter() - started
    all_findings = findings

    findings = tuple(
        indexed
        for indexed in all_findings
        if not suppressed_by_directive(indexed.finding.text)
    )
    stats.ignored_by_directive = len(all_findings) - len(findings)
    baseline_findings = findings

    if args.quiet and args.ai:
        print(QUIET_AI_CONFLICT, file=sys.stderr)
    if args.quiet and args.blame:
        print("--quiet and --blame cannot be used together.", file=sys.stderr)
    if args.quiet and args.age:
        print("--quiet and --age cannot be used together.", file=sys.stderr)
    if args.quiet and args.min_age is not None:
        print("--quiet and --min-age cannot be used together.", file=sys.stderr)
    if args.quiet and args.max_age is not None:
        print("--quiet and --max-age cannot be used together.", file=sys.stderr)
    if args.quiet and args.check_secrets:
        print("--quiet and --check-secrets cannot be used together.", file=sys.stderr)

    age_filtering = args.min_age is not None or args.max_age is not None
    do_history = (args.blame or args.age or age_filtering) and not args.quiet
    if do_history:
        option = (
            "--blame"
            if args.blame
            else "--age"
            if args.age
            else "--min-age"
            if args.min_age is not None
            else "--max-age"
        )
        if not (root / ".git").exists():
            print(f"Error: {option} requires a Git repository.", file=sys.stderr)
            return 2
        if shutil.which("git") is None:
            print(f"Error: {option} requires the git executable.", file=sys.stderr)
            return 2

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

    removed_by_age = 0
    if age_filtering and blames is not None:
        filtered = filter_by_age(
            findings, blames, min_age=args.min_age, max_age=args.max_age
        )
        removed_by_age = len(findings) - len(filtered)
        findings = filtered

    secrets_found: SecretEntries | None = None
    if args.check_secrets and not args.quiet:
        secrets_found = secret_entries(all_findings)

    gate_failed = False
    if args.fail:
        gate_failed = len(findings) > 0
    elif args.fail_count is not None:
        gate_failed = len(findings) > args.fail_count
    gate_exit = FINDINGS_GATE_EXIT_CODE if gate_failed else 0

    diff_new: tuple[IndexedFinding, ...] = ()
    diff_removed: tuple[str, ...] = ()
    if args.diff:
        state_file = state_path(root)
        state = load_state(state_file)
        current_keys = finding_keys(baseline_findings)
        new_keys, removed_keys = diff_sets(previous_keys(state, root), current_keys)
        diff_new = tuple(
            indexed for indexed in baseline_findings if finding_key(indexed) in new_keys
        )
        diff_removed = tuple(sorted(removed_keys))
        store_project(state, root, current_keys)
        prune_state(state)
        if not save_state(state_file, state):
            print("Warning: could not write the diff state.", file=sys.stderr)

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
            limit = effective_limit(config)
            if ai_payload_chars > limit and oversized_item(items, limit) is not None:
                eligibility = AiEligibility(
                    reason=AiSkipReason.PAYLOAD_TOO_LARGE,
                    payload_characters=ai_payload_chars,
                )

    ai_result = None
    ai_failure_line: str | None = None
    outcome_kind: AiOutcomeKind | None = None
    ai_from_cache = False
    if eligibility.reason is AiSkipReason.ELIGIBLE:
        assert items is not None
        assert config.model is not None
        if status is None:
            status = StatusContext
        if confirm_secondary is None:
            confirm_secondary = _prompt_secondary
        cache_file = None if args.no_cache else cache_path()
        cache_data = None if cache_file is None else load_cache(cache_file)
        outcome, ai_from_cache = run_chunked_analysis(
            items,
            config.model,
            keys,
            cache=cache_data,
            max_chars=effective_limit(config),
            interactive=interactive,
            confirm_secondary=confirm_secondary,
            status=status,
        )
        if outcome.kind is AiOutcomeKind.SUCCESS and cache_file is not None:
            assert cache_data is not None
            if not save_cache(cache_file, cache_data):
                print("Warning: could not write the AI cache.", file=sys.stderr)
        outcome_kind = outcome.kind
        if outcome.kind is AiOutcomeKind.SUCCESS:
            ai_result = outcome.result
        else:
            ai_failure_line = _outcome_skip_line(outcome.kind)

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
                age_filter_removed=removed_by_age if age_filtering else None,
                changed_files=(len(changed_set) if changed_set is not None else None),
                ai_from_cache=(
                    ai_from_cache
                    if eligibility.reason is AiSkipReason.ELIGIBLE
                    else None
                ),
                secrets_detected=(
                    len(secrets_found) if secrets_found is not None else None
                ),
                gate_enabled=args.fail or args.fail_count is not None,
                gate_threshold=args.fail_count,
                gate_failed=gate_failed,
                diff_new_count=len(diff_new) if args.diff else None,
                diff_removed_count=len(diff_removed) if args.diff else None,
                **blame_kwargs,
            ),
            file=sys.stderr,
        )

    if args.quiet:
        report = quiet_report(diff_new if args.diff else findings)
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
            ai_from_cache=ai_from_cache,
            secret_entries=secrets_found,
            diff_new=diff_new if args.diff else None,
            diff_removed=len(diff_removed),
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
            age_filter=(
                {
                    "min_age": args.min_age,
                    "max_age": args.max_age,
                    "removed": removed_by_age,
                }
                if age_filtering
                else None
            ),
            changed_ref=args.changed,
            staged=args.staged,
            ai_from_cache=ai_from_cache,
            secret_entries=secrets_found,
            gate=(
                {
                    "enabled": True,
                    "threshold": args.fail_count,
                    "count": len(findings),
                    "failed": gate_failed,
                }
                if args.fail or args.fail_count is not None
                else None
            ),
            diff_new=diff_new if args.diff else None,
            diff_removed=diff_removed if args.diff else None,
        )
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return gate_exit

    if args.format == "sarif":
        data = sarif_report(
            findings,
            config,
            files_scanned=stats.scanned,
            ai_result=ai_result,
            blames=blames if args.blame else None,
            ages=blames if args.age else None,
            secret_entries=secrets_found,
        )
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return gate_exit

    if args.format == "github-actions":
        print(gha_report(findings, ai_result))
        return gate_exit

    print(report)
    return gate_exit


def entrypoint() -> None:
    """Console entry point: convert main's exit code into process status."""
    multiprocessing.freeze_support()
    raise SystemExit(main())
