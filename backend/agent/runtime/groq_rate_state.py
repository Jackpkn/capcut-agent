"""Lightweight Groq rate-limit flag for user-facing messages."""

from __future__ import annotations

import time

_last_rate_limit_at: float = 0.0


def mark_rate_limited() -> None:
    global _last_rate_limit_at
    _last_rate_limit_at = time.time()


def rate_limit_hint() -> str | None:
    if time.time() - _last_rate_limit_at < 120:
        return "Model rate limit — wait ~60s or the app will try the other provider (Groq/Gemini)."
    return None
