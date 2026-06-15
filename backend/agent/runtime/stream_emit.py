"""Wire live Ollama stream chunks → SSE events for the frontend."""

from __future__ import annotations

from agent.runtime.ollama_provider import extract_visible_reply_from_thinking
from agent.streaming import (
    EventEmitter,
    emit_text_chunks,
    model_thinking_delta,
    model_thinking_end,
    model_thinking_start,
    response_start,
    text_delta,
)

# Event types that must reach the browser immediately (never batch/filter).
LIVE_SSE_TYPES = frozenset({
    "model_thinking",
    "model_thinking_start",
    "model_thinking_end",
    "text_delta",
    "response_start",
    "agent_message",
    "tool_call",
    "tool_result",
    "proposal",
})


def is_live_sse_event(event: dict) -> bool:
    return event.get("type") in LIVE_SSE_TYPES


# Agents that may stream thinking to the UI but must never emit user-visible reply text.
_SUPPRESS_REPLY_AGENTS = frozenset({
    "orchestrator", "director", "scene_planner", "planner", "qa", "specialist",
})


def make_chunk_emitter(
    emit: EventEmitter | None,
    *,
    agent: str = "",
) -> tuple[object | None, object]:
    """Return (on_chunk, finalize) for call_model / call_ollama streaming."""
    if not emit:
        return None, lambda: None

    state = {"thinking": False, "answer": False}
    thinking_buf: list[str] = []

    suppress_reply = agent in _SUPPRESS_REPLY_AGENTS

    def on_chunk(channel: str, text: str) -> None:
        if not text:
            return
        if channel == "thinking":
            thinking_buf.append(text)
            if not state["thinking"]:
                model_thinking_start(emit, agent=agent)
                state["thinking"] = True
            model_thinking_delta(emit, text)
            return
        if suppress_reply:
            return
        if state["thinking"] and not state["answer"]:
            model_thinking_end(emit)
            state["thinking"] = False
        if not state["answer"]:
            response_start(emit)
            state["answer"] = True
        text_delta(emit, text)

    def finalize(*, thinking_fallback: str = "") -> None:
        if state["thinking"] and not state["answer"]:
            model_thinking_end(emit)
            state["thinking"] = False
        if not state["thinking"] and thinking_fallback.strip() and emit:
            from agent.streaming import emit_thinking_chunks

            emit_thinking_chunks(emit, thinking_fallback.strip(), agent=agent or None)
            state["thinking"] = True
            model_thinking_end(emit)
        if suppress_reply or state["answer"]:
            return
        extracted = extract_visible_reply_from_thinking("".join(thinking_buf))
        if extracted:
            emit_text_chunks(emit, extracted, chunk_chars=10)
            state["answer"] = True

    return on_chunk, finalize
