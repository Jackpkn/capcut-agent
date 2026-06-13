"""LLM entrypoint — Groq + Gemini with automatic fallback."""

from __future__ import annotations

from agent.runtime.llm import (
    call_model,
    gemini_available,
    groq_available,
    llm_available,
    provider_order,
    stream_model_text,
)

__all__ = [
    "call_model",
    "stream_model_text",
    "groq_available",
    "gemini_available",
    "llm_available",
    "provider_order",
]
