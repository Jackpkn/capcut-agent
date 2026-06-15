"""Agent event helpers for real-time SSE streaming."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

EventEmitter = Callable[[dict[str, Any]], None]


def step(
    emit: EventEmitter | None,
    step_id: str,
    label: str,
    status: str = "running",
    detail: str | None = None,
) -> None:
    if not emit:
        return
    emit({
        "type": "step",
        "id": step_id,
        "status": status,
        "label": label,
        "detail": detail,
    })


def tool_call(
    emit: EventEmitter | None,
    name: str,
    args: dict,
    status: str = "running",
) -> None:
    if not emit:
        return
    emit({
        "type": "tool_call",
        "name": name,
        "args": args,
        "status": status,
    })


def tool_result(emit: EventEmitter | None, name: str, summary: str) -> None:
    if not emit:
        return
    emit({
        "type": "tool_result",
        "name": name,
        "summary": summary,
    })


def proposal(
    emit: EventEmitter | None,
    description: str,
    action: str,
    *,
    anchor: dict | None = None,
    agent: str | None = None,
) -> None:
    if not emit:
        return
    payload: dict[str, Any] = {
        "type": "proposal",
        "description": description,
        "action": action,
    }
    if anchor:
        payload["anchor"] = anchor
    if agent:
        payload["agent"] = agent
    emit(payload)


def agent_activity(
    emit: EventEmitter | None,
    *,
    agent: str,
    phase: str,
    detail: str | None = None,
    anchor: dict | None = None,
    index: int | None = None,
    total: int | None = None,
) -> None:
    """Structured team/specialist activity for the chat trace."""
    if not emit:
        return
    emit({
        "type": "agent_activity",
        "agent": agent,
        "phase": phase,
        "detail": detail,
        "anchor": anchor,
        "index": index,
        "total": total,
    })


def text_delta(emit: EventEmitter | None, content: str) -> None:
    if not emit:
        return
    emit({"type": "text_delta", "content": content})


def model_thinking_start(emit: EventEmitter | None, *, agent: str | None = None) -> None:
    if not emit:
        return
    payload: dict[str, Any] = {"type": "model_thinking_start"}
    if agent:
        payload["agent"] = agent
    emit(payload)


def model_thinking_delta(emit: EventEmitter | None, content: str) -> None:
    if not emit:
        return
    emit({"type": "model_thinking", "content": content})


def model_thinking_end(emit: EventEmitter | None) -> None:
    if not emit:
        return
    emit({"type": "model_thinking_end"})


def emit_thinking_chunks(
    emit: EventEmitter | None,
    text: str,
    *,
    agent: str | None = None,
    chunk_chars: int = 28,
) -> None:
    """Stream captured model reasoning to the UI."""
    if not emit or not text.strip():
        return
    model_thinking_start(emit, agent=agent)
    for i in range(0, len(text), chunk_chars):
        model_thinking_delta(emit, text[i : i + chunk_chars])
    model_thinking_end(emit)


def response_start(emit: EventEmitter | None) -> None:
    if not emit:
        return
    emit({"type": "response_start"})


def emit_text_chunks(emit: EventEmitter | None, text: str, *, chunk_chars: int = 12) -> None:
    """Stream pre-built text to the UI in small chunks (fast-path replies)."""
    if not emit or not text:
        return
    response_start(emit)
    for i in range(0, len(text), chunk_chars):
        text_delta(emit, text[i : i + chunk_chars])


def summarize_tool_output(name: str, output: str) -> str:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return output[:120]

    if name == "search_library":
        count = data.get("count", len(data.get("results", [])))
        query = data.get("query", "")
        return f'Found {count} result(s) for "{query}"'
    if name == "get_director_picks":
        mood = data.get("mood", "")
        parts = []
        for key in ("transitions", "effects", "music"):
            items = data.get(key, [])
            if items:
                parts.append(f"{len(items)} {key}")
        return f"Director picks ({mood}): {', '.join(parts) or 'no matches'}"
    if name == "present_timeline":
        if data.get("error"):
            return str(data["error"])
        return f"Timeline visual: {data.get('view', 'clips')}"
    return output[:120]


def should_surface_trace_event(event: dict[str, Any]) -> bool:
    """Filter noisy internal agent events from the user-visible trace."""
    kind = event.get("type")
    if kind in (
        "agent_thinking", "agent_message", "tool_call", "tool_result",
        "text_delta", "response_start",
        "model_thinking", "model_thinking_start", "model_thinking_end",
    ):
        return False
    if kind in (
        "agent_activity", "chapter_map", "chapter_started", "chapter_planned", "editor_timeline",
    ):
        return True
    if kind == "step":
        step_id = str(event.get("id", ""))
        label = str(event.get("label", ""))
        if "_turn_" in step_id:
            return False
        if label in ("Orchestration complete", "Response complete"):
            return False
        if "observe → think → tool" in label:
            return False
    return True


def sse_line(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def iter_sse(events: Iterator[dict[str, Any]]) -> Iterator[str]:
    for event in events:
        yield sse_line(event)
