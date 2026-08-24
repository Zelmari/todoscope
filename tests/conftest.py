"""Shared test fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_ai_cache(tmp_path, monkeypatch) -> None:
    """Point the AI result cache at a per-test directory."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
