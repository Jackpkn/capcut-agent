"""Shared FFmpeg analysis cache (main + agent brain)."""

from __future__ import annotations

_cache: dict[str, dict] = {}


def get_cached(project_path: str) -> dict | None:
    return _cache.get(project_path)


def set_cached(project_path: str, analysis: dict) -> None:
    _cache[project_path] = analysis
