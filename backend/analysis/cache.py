"""Shared FFmpeg analysis cache (main + agent brain)."""

from __future__ import annotations

_cache: dict[str, dict] = {}


def get_cached(project_path: str) -> dict | None:
    return _cache.get(project_path)


def set_cached(project_path: str, analysis: dict) -> None:
    _cache[project_path] = analysis


def message_needs_audio_analysis(message: str) -> bool:
    lower = message.lower()
    return any(k in lower for k in ("quiet", "fix quiet", "quiet audio", "louder"))
