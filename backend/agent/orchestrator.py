"""LLM orchestrator — decides answer vs edit agent vs sequential team."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from agent.runtime.model import call_model, llm_available
from agent.streaming import EventEmitter, step as emit_step

logger = logging.getLogger(__name__)

ORCHESTRATOR_INSTRUCTIONS = """You are the CapCut orchestrator. Read the human message (any language) and project snapshot.
Call route_request exactly once. You decide — there are no keyword rules.

## Modes
- **answer**: Greetings, questions, inspection, advice, timeline **visuals**, project scan. No timeline writes.
- **edit**: Focused changes — one area or a few related tweaks (fix a caption, add music, one transition, speed one clip).
- **team**: Large coordinated re-edits — pacing + music + captions + FX across many clips.
  Team agents work **one after another** on the same timeline (never parallel).

## Routing judgment (your call — no code shortcuts)
- Casual chat or thanks with no edit ask → **answer**
- Style/vibe requests on **short** timelines (few clips, low duration_sec) → **edit** (single agent is enough)
- **team** only for long multi-chapter re-edits or explicit "re-edit everything" scope
- In `reason`, summarize the **user's actual words** — never copy example phrases from these instructions

Set ui_label to a short phrase for the UI."""

ROUTE_TOOL = [{
    "type": "function",
    "name": "route_request",
    "description": "Route this request to the right agent workflow.",
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["answer", "edit", "team"],
            },
            "reason": {
                "type": "string",
                "description": "One sentence for the user — why this mode",
            },
            "ui_label": {
                "type": "string",
                "description": "Short status label for the UI",
            },
        },
        "required": ["mode", "reason", "ui_label"],
    },
}]


@dataclass
class RouteDecision:
    mode: str
    reason: str
    ui_label: str


def _parse_route(response) -> RouteDecision | None:
    for item in response.output:
        if item.type != "function_call" or item.name != "route_request":
            continue
        try:
            args = json.loads(item.arguments)
        except json.JSONDecodeError:
            continue
        mode = (args.get("mode") or "edit").lower()
        if mode not in ("answer", "edit", "team"):
            mode = "edit"
        ui_label = str(args.get("ui_label") or mode).strip()
        if len(ui_label) > 48 or ui_label.count(" ") > 6:
            ui_label = {"answer": "Chat", "edit": "Edit agent", "team": "Team"}.get(mode, mode)
        return RouteDecision(
            mode=mode,
            reason=args.get("reason") or "",
            ui_label=ui_label,
        )
    return None


def _llm_route(
    message: str,
    timeline_summary: dict,
    emit: EventEmitter | None = None,
) -> RouteDecision | None:
    context = json.dumps(timeline_summary, indent=2)
    input_items = [{
        "role": "user",
        "content": f"HUMAN MESSAGE:\n{message}\n\nPROJECT SNAPSHOT:\n{context}",
    }]
    try:
        response = call_model(
            instructions=ORCHESTRATOR_INSTRUCTIONS,
            input_items=input_items,
            tools=ROUTE_TOOL,
            temperature=0.1,
            max_output_tokens=256,
            agent="orchestrator",
            emit=emit,
        )
    except Exception as exc:
        logger.warning("Orchestrator failed: %s", exc)
        return None
    if response is None:
        return None
    return _parse_route(response)


def _looks_like_edit_request(message: str) -> bool:
    m = message.lower()
    markers = (
        "transition", "music", "caption", "effect", "trim", "speed",
        "add ", "remove", "change", "make it", "make this", "better",
        "improve", "reorder", "sticker", "image", "anything",
    )
    return any(w in m for w in markers)


def decide_route(
    message: str,
    timeline_summary: dict,
    project_path: str | None,
    *,
    force_team: bool = False,
    auto_edit: bool = False,
    emit: EventEmitter | None = None,
) -> RouteDecision:
    if not project_path:
        return RouteDecision(
            mode="answer",
            reason="No project selected — general chat.",
            ui_label="Chat",
        )

    if auto_edit:
        emit_step(
            emit, "orchestrator", "Auto edit (pro)", "done",
            "Full hierarchical edit — Director plans all chapters, one approve at the end.",
        )
        return RouteDecision(
            mode="team",
            reason=(
                "Auto edit — sequential team workflow across every chapter "
                "(pacing, music, captions, transitions)."
            ),
            ui_label="Auto edit (pro)",
        )

    parsed: RouteDecision | None = None
    if llm_available():
        emit_step(emit, "orchestrator", "Understanding what you need…")
        parsed = _llm_route(message, timeline_summary, emit=emit)

    # Questions / visuals / scan — unless the user clearly asked for an edit
    if parsed and parsed.mode == "answer":
        if _looks_like_edit_request(message):
            parsed = RouteDecision(
                mode="edit",
                reason=parsed.reason or "Edit request detected in your message.",
                ui_label="Edit agent",
            )
        else:
            emit_step(emit, "orchestrator", parsed.ui_label, "done", parsed.reason)
            return parsed

    if force_team:
        emit_step(
            emit, "orchestrator", "Sequential team (forced)", "done",
            "Force team is on — multi-agent workflow for edits.",
        )
        return RouteDecision(
            mode="team",
            reason="You enabled force team mode — sequential multi-agent workflow.",
            ui_label="Sequential team (forced)",
        )

    if not llm_available():
        emit_step(emit, "orchestrator", "Routing to edit agent", "done", "Model offline — single agent")
        return RouteDecision(
            mode="edit",
            reason="Orchestrator model unavailable — using the edit agent directly.",
            ui_label="Edit agent",
        )

    if parsed is not None:
        emit_step(emit, "orchestrator", parsed.ui_label, "done", parsed.reason)
        return parsed

    emit_step(emit, "orchestrator", "Edit agent", "done", "Could not classify — using edit agent")
    return RouteDecision(
        mode="edit",
        reason="Orchestrator could not classify — using the edit agent.",
        ui_label="Edit agent",
    )
