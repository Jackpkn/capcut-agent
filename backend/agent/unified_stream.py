"""Single entry SSE — orchestrator routes to answer, edit agent, or sequential team."""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Iterator

from agent.auto_edit import build_auto_edit_message, display_label
from agent.brain import hydrate_analysis_from_cache, hydrate_clip_intelligence_from_cache, iter_agent_sse, set_clip_intelligence_context
from agent.orchestrator import decide_route
from agent.runtime.agent_log import agent as log_agent
from agent.streaming import sse_line
from analysis.clip_intelligence import iter_understand_sse, load_project_intelligence
from core.agent_loop import iter_team_sse
from core.slices import timeline_summary_from_project_summary
from core.task_queue import start_session


def iter_unified_sse(
    message: str,
    project_path: str | None,
    *,
    force_team: bool = False,
    auto_edit: bool = False,
    images: list[str] | None = None,
    trust_apply: bool = False,
) -> Iterator[str]:
    human_hint = message.strip()
    agent_message = build_auto_edit_message(human_hint) if auto_edit else human_hint

    vision_b64: list[str] = []
    working_message = agent_message
    if images:
        from agent.streaming import step as emit_step

        yield sse_line({
            "type": "step",
            "id": "user_images",
            "status": "running",
            "label": "Analyzing attached image(s)…",
        })
        from agent.user_images import enrich_user_message

        working_message, vision_b64 = enrich_user_message(agent_message, images)
        if vision_b64:
            yield sse_line({
                "type": "step",
                "id": "user_images",
                "status": "done",
                "label": f"Attached {len(vision_b64)} reference image(s)",
            })
        else:
            yield sse_line({
                "type": "step",
                "id": "user_images",
                "status": "error",
                "label": "Could not read attached image(s)",
                "detail": "Use JPEG or PNG under 3MB",
            })

    log_agent(
        "stream start",
        auto_edit=auto_edit,
        force_team=force_team,
        msg_preview=working_message[:80],
        images=len(vision_b64),
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

    preload_box: dict = {}
    route_box: dict = {}
    box_lock = threading.Lock()
    timeline_ready = threading.Event()
    route_q: queue.Queue = queue.Queue()

    def preload_worker() -> None:
        if not project_path:
            with box_lock:
                preload_box["timeline"] = {}
                preload_box["project_summary"] = None
            timeline_ready.set()
            return
        try:
            from capcut.reader import get_project_summary

            summary = get_project_summary(project_path)
            with box_lock:
                preload_box["project_summary"] = summary
                preload_box["timeline"] = timeline_summary_from_project_summary(summary)
        except Exception as exc:
            log_agent("preload failed", error=str(exc))
            with box_lock:
                preload_box["error"] = str(exc)
                preload_box["timeline"] = {}
                preload_box["project_summary"] = None
        finally:
            timeline_ready.set()

    def route_worker() -> None:
        timeline_ready.wait()
        with box_lock:
            timeline_val = preload_box.get("timeline") or {}
        route_decision = decide_route(
            working_message,
            timeline_val,
            project_path,
            force_team=force_team,
            auto_edit=auto_edit,
            attached_images=len(vision_b64),
            emit=lambda ev: route_q.put(ev),
        )
        with box_lock:
            route_box["route"] = route_decision
        route_q.put(None)

    threading.Thread(target=preload_worker, daemon=True).start()
    threading.Thread(target=route_worker, daemon=True).start()

    while True:
        ev = route_q.get()
        if ev is None:
            break
        yield sse_line(ev)

    with box_lock:
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
        session_message = working_message
        use_auto_edit = auto_edit or route.auto_edit
        clips = load_project_intelligence(project_path)
        if not clips:
            log_agent("clip understand", clips="running (cache miss)")
            for event in iter_understand_sse(project_path, max_clips=24):
                yield sse_line(event)
                if event.get("type") == "understand_done":
                    clips = event.get("clips") or []
            set_clip_intelligence_context(clips)
        session = start_session(
            project_path,
            session_message,
            auto_edit=use_auto_edit,
            trust_apply=trust_apply,
        )
        log_agent("team session started", session_id=session.id, clips_understood=len(clips))
        yield sse_line({
            "type": "workflow",
            "workflow": "team",
            "session_id": session.id,
            "auto_edit": use_auto_edit,
            "trust_apply": trust_apply,
            "note": (
                "Auto edit — Director → all chapters → one approve."
                if use_auto_edit
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

    with box_lock:
        summary_val = preload_box.get("project_summary")

    for line in iter_agent_sse(
        working_message,
        project_path,
        answer_only=(route.mode == "answer"),
        project_summary=summary_val,
        images=vision_b64 or None,
        preprocessed_images=bool(vision_b64),
        trust_apply=trust_apply,
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
