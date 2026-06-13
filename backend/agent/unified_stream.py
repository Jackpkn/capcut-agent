"""Single entry SSE — orchestrator routes to answer, edit agent, or sequential team."""

from __future__ import annotations

import json
from collections.abc import Iterator

from agent.brain import hydrate_analysis_from_cache, iter_agent_sse
from agent.orchestrator import decide_route
from agent.streaming import sse_line
from core.agent_loop import iter_team_sse
from core.slices import get_timeline_summary
from core.task_queue import start_session


def iter_unified_sse(
    message: str,
    project_path: str | None,
    *,
    force_team: bool = False,
) -> Iterator[str]:
    if project_path:
        hydrate_analysis_from_cache(project_path)

    yield sse_line({
        "type": "agent_start",
        "message": "CapCut agent started",
    })

    timeline = get_timeline_summary(project_path) if project_path else {}
    route = decide_route(
        message,
        timeline,
        project_path,
        force_team=force_team,
    )

    yield sse_line({
        "type": "route_decision",
        "mode": route.mode,
        "reason": route.reason,
        "label": route.ui_label,
        "sequential": True,
    })

    if not project_path:
        yield sse_line({
            "type": "response_start",
        })
        msg = (
            "**Select a CapCut project** in the sidebar dropdown first. "
            "Timeline questions, caption visuals, and edits all read from your project on disk."
        )
        yield sse_line({"type": "text_delta", "delta": msg})
        yield sse_line({
            "type": "done",
            "reply": msg,
            "pending_actions": [],
        })
        return

    if route.mode == "team" and project_path:
        session = start_session(project_path, message)
        yield sse_line({
            "type": "workflow",
            "workflow": "team",
            "session_id": session.id,
            "note": "Specialists run one-by-one on the same timeline (not parallel).",
        })
        yield from iter_team_sse(session.id)
        return

    workflow = "answer" if route.mode == "answer" else "edit"
    yield sse_line({
        "type": "workflow",
        "workflow": workflow,
        "note": "Single agent with project context and tools.",
    })

    for line in iter_agent_sse(message, project_path):
        payload = line.removeprefix("data: ").strip()
        if payload:
            try:
                ev = json.loads(payload)
                if ev.get("type") == "agent_start":
                    continue
            except json.JSONDecodeError:
                pass
        yield line
