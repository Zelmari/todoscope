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
import time
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
CACHE_MAX_ENTRIES = 20_000
"""Hard cap on cached item entries; the newest entries win."""
CACHE_MAX_AGE_DAYS = 180
"""Entries and run overviews older than this are pruned on load."""


def cache_path(*, environ: dict[str, str] | None = None) -> Path:
    """User-level cache file: XDG, else LOCALAPPDATA on Windows, else ~/.cache."""
    if environ is None:
        environ = dict(os.environ)
    return _cache_base_dir(environ) / "todoscope" / CACHE_FILENAME


def _cache_base_dir(environ: dict[str, str], *, on_windows: bool | None = None) -> Path:
    """Cache base directory; ``on_windows`` overrides os.name for tests."""
    if on_windows is None:
        on_windows = os.name == "nt"
    xdg = environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg)
    if on_windows:
        local = environ.get("LOCALAPPDATA")
        if local:
            return Path(local)
    return Path.home() / ".cache"


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
    prune_cache(data)
    return data


def prune_cache(data: dict[str, Any], *, now: float | None = None) -> None:
    """Drop entries and overviews past the age limit, and cap entry count."""
    if now is None:
        now = time.time()
    cutoff = now - CACHE_MAX_AGE_DAYS * 86400

    items = data.get("items")
    if isinstance(items, dict):
        stale = [
            key
            for key, entry in items.items()
            if isinstance(entry, dict) and entry.get("ts", now) < cutoff
        ]
        for key in stale:
            del items[key]
        if len(items) > CACHE_MAX_ENTRIES:
            ordered = sorted(
                items.items(),
                key=lambda kv: kv[1].get("ts", 0) if isinstance(kv[1], dict) else 0,
                reverse=True,
            )
            for key, _ in ordered[CACHE_MAX_ENTRIES:]:
                del items[key]

    runs = data.get("runs")
    if isinstance(runs, dict):
        stale = [
            key
            for key, entry in runs.items()
            if isinstance(entry, dict) and entry.get("ts", now) < cutoff
        ]
        for key in stale:
            del runs[key]


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
        stamp = time.time()
        for item in outcome.result.items:
            store[item_keys[item.id]] = {
                "interpretation": item.interpretation,
                "priority": item.priority,
                "ts": stamp,
            }
        runs[overview_key] = {"overview": outcome.result.overview, "ts": stamp}
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
