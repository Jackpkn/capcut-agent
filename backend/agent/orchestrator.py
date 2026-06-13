"""LLM orchestrator — decides answer vs edit agent vs sequential team."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from agent.runtime.model import call_model, llm_available
from agent.streaming import EventEmitter, step as emit_step

logger = logging.getLogger(__name__)

ORCHESTRATOR_INSTRUCTIONS = """You are the CapCut orchestrator. Read the human message (any language) and project snapshot.
Call route_request exactly once.

## Modes
- **answer**: Questions, inspection, advice, timeline **visuals** ("show captions on timeline", "where do captions sit"), **project scan** / health review. No timeline writes.
- **edit**: Focused changes — one area or a few related tweaks (fix a caption, add music, one transition, speed one clip).
- **team**: Large coordinated re-edits on long or multi-clip timelines — pacing + music + captions + FX across many clips.
  Team agents work **one after another** on the same timeline (never parallel). Use team when scope is genuinely big/complex.

## Team signals (not rules — use judgment)
- Long timeline (high duration_sec) or many video clips needing coordinated style
- Full vibe / platform packages ("make this a TikTok travel vlog", "cinematic re-edit everything")
- NOT for simple Q&A, timeline visuals, project scan, or a single small change

Set ui_label to a short phrase for the UI (e.g. "Answering from timeline", "Timeline visual", "Edit agent", "Sequential team")."""

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
        return RouteDecision(
            mode=mode,
            reason=args.get("reason") or "",
            ui_label=args.get("ui_label") or mode,
        )
    return None


def _llm_route(message: str, timeline_summary: dict) -> RouteDecision | None:
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
            temperature=0.2,
            max_output_tokens=512,
        )
    except Exception as exc:
        logger.warning("Orchestrator failed: %s", exc)
        return None
    if response is None:
        return None
    return _parse_route(response)


def decide_route(
    message: str,
    timeline_summary: dict,
    project_path: str | None,
    *,
    force_team: bool = False,
    emit: EventEmitter | None = None,
) -> RouteDecision:
    if not project_path:
        return RouteDecision(
            mode="answer",
            reason="No project selected — general chat.",
            ui_label="Chat",
        )

    parsed: RouteDecision | None = None
    if llm_available():
        emit_step(emit, "orchestrator", "Understanding what you need…")
        parsed = _llm_route(message, timeline_summary)

    # Questions / visuals / scan always use single agent (present_timeline + full project JSON)
    if parsed and parsed.mode == "answer":
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

    duration = float(timeline_summary.get("duration_sec") or 0)
    clip_count = int(timeline_summary.get("video_clip_count") or 0)
    if duration > 180 or clip_count > 8:
        emit_step(
            emit, "orchestrator", "Long timeline — team recommended", "done",
            f"{duration:.0f}s, {clip_count} clips",
        )
        return RouteDecision(
            mode="team",
            reason=(
                f"Long timeline ({duration:.0f}s, {clip_count} clips) — "
                "hierarchical chapter-based team workflow."
            ),
            ui_label="Sequential team (long project)",
        )

    if parsed is not None:
        emit_step(emit, "orchestrator", parsed.ui_label, "done", parsed.reason)
        return parsed

    emit_step(emit, "orchestrator", "Edit agent", "done", "Defaulting to edit agent")
    return RouteDecision(
        mode="edit",
        reason="Could not classify — using the edit agent.",
        ui_label="Edit agent",
    )
