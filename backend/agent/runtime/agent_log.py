"""Terminal-friendly agent logging — grep for [AGENT] or [LLM] in uvicorn output."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator

LOG = logging.getLogger("capcut.agent")


def configure_logging(level: str | None = None) -> None:
    """Call once at startup from main.py."""
    import os

    lvl = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    numeric = getattr(logging, lvl, logging.INFO)
    if not logging.root.handlers:
        logging.basicConfig(
            level=numeric,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
        )
    else:
        logging.root.setLevel(numeric)
    for noisy in ("httpx", "httpcore", "openai", "google", "google_genai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def agent(msg: str, **fields: object) -> None:
    suffix = _fields(fields)
    LOG.info("[AGENT] %s%s", msg, suffix)


def llm(msg: str, **fields: object) -> None:
    suffix = _fields(fields)
    LOG.info("[LLM] %s%s", msg, suffix)


def warn(msg: str, **fields: object) -> None:
    suffix = _fields(fields)
    LOG.warning("[AGENT] %s%s", msg, suffix)


def _fields(fields: dict) -> str:
    if not fields:
        return ""
    parts = [f"{k}={v}" for k, v in fields.items() if v is not None and v != ""]
    return " | " + " | ".join(parts) if parts else ""


@contextmanager
def llm_timer(provider: str, model: str, *, agent: str = "", tools: int = 0) -> Iterator[None]:
    llm("→ call", provider=provider, model=model, agent=agent or None, tools=tools or None)
    t0 = time.monotonic()
    try:
        yield
    except Exception as exc:
        llm("✗ failed", provider=provider, model=model, agent=agent or None, error=str(exc)[:120])
        raise
    else:
        llm("✓ done", provider=provider, model=model, agent=agent or None, elapsed=f"{time.monotonic() - t0:.1f}s")
