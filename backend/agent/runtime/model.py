"""LLM entrypoint — Groq + Gemini with automatic fallback."""

from __future__ import annotations

from agent.runtime.llm import (
    call_model,
    gemini_available,
    groq_available,
    llm_available,
    ollama_available,
    provider_order,
    stream_model_text,
)
from agent.runtime.ollama_provider import list_ollama_models, resolve_ollama_model

__all__ = [
    "call_model",
    "stream_model_text",
    "groq_available",
    "gemini_available",
    "ollama_available",
    "llm_available",
    "provider_order",
    "list_ollama_models",
    "resolve_ollama_model",
]
