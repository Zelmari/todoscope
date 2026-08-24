"""Local cache for AI interpretations (MS-26).

Interpretations and priorities are keyed by a hash of (marker, text, model)
so repeat runs with identical comments cost no API budget. The cache stores
only interpretation/priority/overview text plus hashes — never paths, line
numbers, or source — and is best-effort: unreadable or unwritable cache
files fail open with a warning, never failing the scan.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from todoscope.ai import AnalysisItem, AnalysisResult
from todoscope.keys import KeyInfo
from todoscope.openai_client import (
    AiOutcome,
    AiOutcomeKind,
    ConfirmSecondaryFn,
    StatusFactory,
    run_ai_analysis,
)

CACHE_SCHEMA_VERSION = 1
CACHE_FILENAME = "ai-cache.json"


def cache_path(*, environ: dict[str, str] | None = None) -> Path:
    """User-level cache file: XDG_CACHE_HOME/todoscope, else ~/.cache."""
    if environ is None:
        environ = dict(os.environ)
    base = environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "todoscope" / CACHE_FILENAME


def item_key(marker: str, text: str, model: str) -> str:
    """Stable cache key: comment content plus the model that analysed it."""
    digest = hashlib.sha256()
    for part in (marker, text, model):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    digest.update(str(CACHE_SCHEMA_VERSION).encode("ascii"))
    return digest.hexdigest()


def run_key(item_keys: tuple[str, ...]) -> str:
    """Cache key for a run's overview; independent of item order."""
    digest = hashlib.sha256()
    for key in sorted(item_keys):
        digest.update(key.encode("ascii"))
        digest.update(b"\x00")
    return digest.hexdigest()


def load_cache(path: Path) -> dict[str, Any]:
    """Read the cache; any problem yields an empty cache."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_cache(path: Path, data: dict[str, Any]) -> bool:
    """Write the cache; failures are reported, never fatal."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return True
    except OSError:
        return False


def run_cached_analysis(
    items: list[dict[str, Any]],
    model: str,
    keys: KeyInfo,
    *,
    cache: dict[str, Any] | None,
    interactive: bool,
    confirm_secondary: ConfirmSecondaryFn | None = None,
    status: StatusFactory | None = None,
) -> tuple[AiOutcome, bool]:
    """Run AI analysis, using and updating ``cache`` when available.

    Returns the outcome plus whether it was served entirely from cache.
    ``cache`` is the mutable in-memory store; pass None to disable caching.
    A partial cache sends only the missing items; a full cache with a
    matching overview makes no request at all.
    """
    if cache is None:
        outcome = run_ai_analysis(
            items,
            model,
            keys,
            interactive=interactive,
            confirm_secondary=confirm_secondary,
            status=status,
        )
        return outcome, False

    store = cache.setdefault("items", {})
    runs = cache.setdefault("runs", {})
    item_keys = {
        item["id"]: item_key(item["marker"], item["text"], model) for item in items
    }
    cached: dict[int, dict[str, Any]] = {}
    missing: list[dict[str, Any]] = []
    for item in items:
        entry = store.get(item_keys[item["id"]])
        if (
            isinstance(entry, dict)
            and entry.get("interpretation")
            and entry.get("priority")
        ):
            cached[item["id"]] = entry
        else:
            missing.append(item)

    overview_key = run_key(tuple(item_keys.values()))
    if not missing and isinstance(runs.get(overview_key), dict):
        overview = runs[overview_key].get("overview")
        if isinstance(overview, str):
            merged = AnalysisResult(
                items=tuple(
                    AnalysisItem(
                        id=item_id,
                        interpretation=cached[item_id]["interpretation"],
                        priority=cached[item_id]["priority"],
                    )
                    for item_id in item_keys
                ),
                overview=overview,
            )
            return AiOutcome(AiOutcomeKind.SUCCESS, merged), True

    outcome = run_ai_analysis(
        missing if missing else items,
        model,
        keys,
        interactive=interactive,
        confirm_secondary=confirm_secondary,
        status=status,
    )
    if outcome.kind is AiOutcomeKind.SUCCESS and outcome.result is not None:
        for item in outcome.result.items:
            store[item_keys[item.id]] = {
                "interpretation": item.interpretation,
                "priority": item.priority,
            }
        runs[overview_key] = {"overview": outcome.result.overview}
        if missing:
            fresh = {item.id: item for item in outcome.result.items}
            merged = AnalysisResult(
                items=tuple(
                    fresh.get(item_id)
                    or AnalysisItem(
                        id=item_id,
                        interpretation=cached[item_id]["interpretation"],
                        priority=cached[item_id]["priority"],
                    )
                    for item_id in item_keys
                ),
                overview=outcome.result.overview,
            )
            return AiOutcome(AiOutcomeKind.SUCCESS, merged), False
    return outcome, False
