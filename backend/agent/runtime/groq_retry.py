"""Groq 429 handling — parse retry-after and backoff."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import TypeVar

from openai import APIStatusError, RateLimitError

logger = logging.getLogger(__name__)

T = TypeVar("T")

_RETRY_AFTER_RE = re.compile(r"try again in ([\d.]+)s", re.I)


def parse_retry_seconds(exc: BaseException) -> float:
    text = str(exc)
    m = _RETRY_AFTER_RE.search(text)
    if m:
        return min(float(m.group(1)) + 1.0, 90.0)
    return 40.0


def call_with_groq_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 2,
    label: str = "Groq",
) -> T | None:
    """Call Groq API; on 429 wait and retry once (TPM limits are per-minute)."""
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except (RateLimitError, APIStatusError) as exc:
            last_exc = exc
            code = getattr(exc, "status_code", None)
            if code != 429 and not isinstance(exc, RateLimitError):
                logger.warning("%s API error: %s", label, exc)
                return None
            if attempt + 1 >= max_attempts:
                from agent.runtime.groq_rate_state import mark_rate_limited

                mark_rate_limited()
                logger.warning("%s rate limit — giving up after %s attempts: %s", label, max_attempts, exc)
                return None
            wait = parse_retry_seconds(exc)
            logger.warning("%s rate limit — waiting %.0fs then retrying…", label, wait)
            time.sleep(wait)
    if last_exc:
        logger.warning("%s failed: %s", label, last_exc)
    return None


