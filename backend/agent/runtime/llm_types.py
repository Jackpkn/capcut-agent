"""Normalized LLM response shape (Groq Responses API + Gemini)."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import uuid4


@dataclass
class ModelResponse:
    """Compatible with parsers that read response.output and response.output_text."""

    output: list = field(default_factory=list)
    output_text: str = ""
    provider: str = ""


def new_call_id() -> str:
    return f"call_{uuid4().hex[:12]}"


def make_function_call(name: str, arguments: str, *, call_id: str | None = None) -> SimpleNamespace:
    cid = call_id or new_call_id()
    return SimpleNamespace(
        type="function_call",
        name=name,
        arguments=arguments,
        call_id=cid,
        id=cid,
    )


def make_message(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="message",
        content=[SimpleNamespace(type="output_text", text=text)],
    )
