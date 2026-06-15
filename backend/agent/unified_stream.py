"""Single entry SSE — orchestrator routes to answer, edit agent, or sequential team."""

from __future__ import annotations

import json
from collections.abc import Iterator

from agent.auto_edit import build_auto_edit_message, display_label
from agent.brain import hydrate_analysis_from_cache, hydrate_clip_intelligence_from_cache, iter_agent_sse, set_clip_intelligence_context
from agent.orchestrator import decide_route
from agent.runtime.agent_log import agent as log_agent
from agent.streaming import sse_line
from analysis.clip_intelligence import iter_understand_sse, load_project_intelligence
from core.agent_loop import iter_team_sse
from core.slices import get_timeline_summary
from core.task_queue import start_session


def iter_unified_sse(
    message: str,
    project_path: str | None,
    *,
    force_team: bool = False,
    auto_edit: bool = False,
) -> Iterator[str]:
    human_hint = message.strip()
    agent_message = build_auto_edit_message(human_hint) if auto_edit else human_hint

    log_agent(
        "stream start",
        auto_edit=auto_edit,
        force_team=force_team,
        msg_preview=agent_message[:80],
    )

    if project_path:
        hydrate_analysis_from_cache(project_path)
        hydrate_clip_intelligence_from_cache(project_path)

    yield sse_line({
        "type": "agent_start",
        "message": "CapCut agent started",
    })

    if auto_edit and project_path:
        yield sse_line({
            "type": "auto_edit_start",
            "label": display_label(human_hint),
            "hint": human_hint or None,
        })

    timeline = get_timeline_summary(project_path) if project_path else {}

    import queue
    import threading

    route_q: queue.Queue = queue.Queue()
    route_box: dict = {}

    def route_worker() -> None:
        route_box["route"] = decide_route(
            agent_message,
            timeline,
            project_path,
            force_team=force_team,
            auto_edit=auto_edit,
            emit=lambda ev: route_q.put(ev),
        )
        route_q.put(None)

    threading.Thread(target=route_worker, daemon=True).start()
    while True:
        ev = route_q.get()
        if ev is None:
            break
        yield sse_line(ev)

    route = route_box["route"]

    log_agent("route", mode=route.mode, label=route.ui_label, reason=route.reason[:100])

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
        yield sse_line({"type": "text_delta", "content": msg})
        yield sse_line({
            "type": "done",
            "reply": msg,
            "pending_actions": [],
        })
        return

    if route.mode == "team" and project_path:
        clips = load_project_intelligence(project_path)
        if not clips:
            log_agent("clip understand", clips="running (cache miss)")
            for event in iter_understand_sse(project_path, max_clips=24):
                yield sse_line(event)
                if event.get("type") == "understand_done":
                    clips = event.get("clips") or []
            set_clip_intelligence_context(clips)
        session = start_session(project_path, agent_message, auto_edit=auto_edit)
        log_agent("team session started", session_id=session.id, clips_understood=len(clips))
        yield sse_line({
            "type": "workflow",
            "workflow": "team",
            "session_id": session.id,
            "auto_edit": auto_edit,
            "note": (
                "Auto edit — Director → all chapters → one approve."
                if auto_edit
                else "Specialists run one-by-one on the same timeline (not parallel)."
            ),
        })
        yield from iter_team_sse(session.id)
        return

    workflow = "answer" if route.mode == "answer" else "edit"
    yield sse_line({
        "type": "workflow",
        "workflow": workflow,
        "note": "Single agent with project context and tools.",
    })

    for line in iter_agent_sse(
        message,
        project_path,
        answer_only=(route.mode == "answer"),
    ):
        payload = line.removeprefix("data: ").strip()
        if payload:
            try:
                ev = json.loads(payload)
                if ev.get("type") == "agent_start":
                    continue
            except json.JSONDecodeError:
                pass
        yield line
