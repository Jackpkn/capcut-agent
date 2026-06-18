import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent.actions import iter_execute_sse
from agent.brain import (
    chat,
    confirm_actions,
    format_execute_reply,
    hydrate_analysis_from_cache,
    iter_agent_sse,
    record_assistant_reply,
    reject_actions,
    set_analysis_context,
)
from analysis.analyzer import analyze_project
from analysis.suggestions import build_report_text, issues_to_actions
from capcut.cache_index import get_index
from capcut.catalog import build_catalog, get_stats, search_catalog
from capcut.cdp import get_pages, is_connected, sync_capcut
from capcut.library import director_picks, ensure_cached, init_cdp_library, refresh_catalog, search_library
from capcut.reader import get_all_projects, get_draft_write_paths, get_project_summary
from capcut.watcher import start_watcher, stop_watcher
from capcut.draft_repair import load_best_draft_source, repair_draft_data
from capcut.apply_queue import (
    clear_queue,
    get_queue,
    queue_apply,
    start_apply_poller,
)
from capcut.guard import assert_safe_to_write, can_write_safely, is_capcut_running
from capcut.project_ui import apply_with_ui_handoff, capcut_sync_hint, reopen_project
from capcut.writer import _flush_project

logging.basicConfig(level=logging.INFO)
from agent.runtime.agent_log import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

from analysis.cache import get_cached, set_cached


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_watcher()
    init_cdp_library()
    start_apply_poller()
    yield
    stop_watcher()


app = FastAPI(title="CapCut AI Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    project_path: str | None = None


class ActionItem(BaseModel):
    action: str
    params: dict
    description: str | None = None


class ExecuteRequest(BaseModel):
    project_path: str
    actions: list[ActionItem]


class RejectRequest(BaseModel):
    reason: str | None = None
    project_path: str | None = None
    actions: list[ActionItem] | None = None
    project_path: str | None = None
    actions: list[ActionItem] | None = None


class CatalogDownloadRequest(BaseModel):
    resource_id: str | None = None
    name: str | None = None
    type: str = "music"
    project_path: str | None = None


@app.get("/projects")
def list_projects():
    return get_all_projects()


@app.get("/project/summary")
def project_summary(path: str):
    try:
        return get_project_summary(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze/stream")
def analyze_stream_endpoint(path: str, max_clips: int = 8):
    """SSE: progressive video → audio → suggestions (CapCut-style analysis UI)."""
    from analysis.streaming import iter_analyze_sse

    return StreamingResponse(
        iter_analyze_sse(path, max_clips=max_clips),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/analyze")
def analyze_endpoint(path: str, max_clips: int = 8):
    try:
        analysis = analyze_project(path, max_clips=max_clips)
        report = build_report_text(analysis)
        suggestions = issues_to_actions(
            analysis["issues"],
            analysis.get("summary", {}),
        )
        set_cached(path, analysis)
        hydrate_analysis_from_cache(path)
        return {
            "score": analysis["score"],
            "clips_analyzed": analysis["clips_analyzed"],
            "total_clips": analysis["total_clips"],
            "total_issues": analysis["total_issues"],
            "issues": analysis["issues"],
            "clip_reports": analysis["clip_reports"],
            "report": report,
            "suggested_actions": suggestions,
        }
    except Exception as e:
        logger.exception("Analysis error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/analyze/cache")
def get_cached_analysis(path: str):
    cached = get_cached(path)
    if not cached:
        raise HTTPException(status_code=404, detail="No analysis cached. Run /analyze first.")
    return {
        "score": cached["score"],
        "issues": cached["issues"],
        "clip_reports": cached["clip_reports"],
        "report": build_report_text(cached),
        "suggested_actions": issues_to_actions(cached["issues"], cached.get("summary", {})),
    }


@app.get("/project/clip-intelligence")
def clip_intelligence_endpoint(path: str):
    """Cached per-clip understanding (System 1 — FFmpeg + optional Gemini vision)."""
    from analysis.clip_intelligence import director_clip_summaries, load_project_intelligence
    from analysis.vision_local import vision_available

    clips = load_project_intelligence(path)
    return {
        "clips": clips,
        "director_summaries": director_clip_summaries(clips),
        "vision_available": vision_available(),
        "count": len(clips),
    }


@app.get("/library/search")
def library_search(q: str = "", type: str = "all", limit: int = 20):
    try:
        return search_library(q, type, limit=limit)
    except Exception as e:
        logger.exception("Library search error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/library/stats")
def library_stats():
    stats = get_stats()
    by = stats.get("by_type", {})
    return {
        "music": by.get("music", {}).get("total", 0),
        "effects": by.get("effect", {}).get("total", 0),
        "transitions": by.get("transition", {}).get("total", 0),
        "stickers": by.get("sticker", {}).get("total", 0),
        "text_templates": by.get("text_template", {}).get("total", 0),
        "catalog_total": stats.get("total", 0),
        "named_from_projects": stats.get("named_from_projects", 0),
        "cdp_connected": is_connected(),
    }


@app.post("/library/refresh")
def library_refresh():
    return refresh_catalog()


@app.post("/catalog/build")
def catalog_build():
    try:
        return build_catalog()
    except Exception as e:
        logger.exception("Catalog build error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/catalog/search")
def catalog_search(q: str = "", type: str = "all", limit: int = 20):
    return {"results": search_catalog(q, type, limit=limit), "count": len(search_catalog(q, type, limit=limit))}


@app.get("/catalog/director")
def catalog_director(mood: str = "energetic"):
    return director_picks(mood)


@app.post("/catalog/download")
def catalog_download(req: CatalogDownloadRequest):
    try:
        asset = ensure_cached(
            resource_id=req.resource_id,
            name=req.name,
            asset_type=req.type,
            project_path=req.project_path,
        )
        return {"success": True, "asset": asset}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Catalog download error")
        raise HTTPException(status_code=500, detail=str(e))


class AgentStreamRequest(BaseModel):
    message: str
    project_path: str | None = None
    force_team: bool = False
    auto_edit: bool = False


@app.post("/agent/stream")
def agent_stream_endpoint(req: AgentStreamRequest):
    """Unified SSE: orchestrator → answer | edit agent | sequential team."""
    if not req.message.strip() and not req.auto_edit:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    from agent.runtime.agent_log import agent as log_agent
    from agent.unified_stream import iter_unified_sse

    log_agent(
        "HTTP POST /agent/stream",
        auto_edit=req.auto_edit,
        force_team=req.force_team,
        message=req.message[:60],
    )

    return StreamingResponse(
        iter_unified_sse(
            req.message,
            req.project_path,
            force_team=req.force_team,
            auto_edit=req.auto_edit,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/chat/stream")
def chat_stream_endpoint(req: ChatRequest):
    """Legacy chat stream — prefer POST /agent/stream."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    hydrate_analysis_from_cache(req.project_path)

    return StreamingResponse(
        iter_agent_sse(req.message, req.project_path),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    try:
        hydrate_analysis_from_cache(req.project_path)
        result = chat(req.message, req.project_path)
        action_dicts = [
            {
                "action": a.action,
                "params": a.params,
                "description": a.description,
            }
            for a in result.pending_actions
        ]
        payload: dict = {
            "reply": result.reply,
            "pending_actions": action_dicts,
        }
        if req.project_path and action_dicts:
            from agent.diff import compute_edit_diff

            payload["edit_diff"] = compute_edit_diff(req.project_path, action_dicts)
        return payload
    except Exception as e:
        logger.exception("Chat error")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/project/restore-backup")
def restore_latest_backup(path: str):
    """Restore cleaned edits from CapCut .bak or agent backup (CapCut must be quit)."""
    try:
        assert_safe_to_write(path)
        data, source = load_best_draft_source(path)
        repair_draft_data(data)

        speed_by_id = {s["id"]: s for s in data["materials"].get("speeds", [])}
        for track in data.get("tracks", []):
            if track.get("type") != "video":
                continue
            for segment in track.get("segments", []):
                speed = segment.get("speed", 1)
                if speed == 1:
                    continue
                for ref in segment.get("extra_material_refs", []):
                    if ref in speed_by_id:
                        speed_by_id[ref]["speed"] = speed

        _flush_project(path, data)
        trans = len(data["materials"].get("transitions", []))
        fast = sum(
            1 for t in data.get("tracks", [])
            if t.get("type") == "video"
            for s in t.get("segments", [])
            if s.get("speed", 1) != 1
        )
        return {
            "restored_from": source,
            "transitions": trans,
            "sped_clips": fast,
            "draft_files": [str(p) for p in get_draft_write_paths(path)],
            "message": (
                f"Restored {trans} transition(s) and {fast} speed change(s) from {source}. "
                "Open CapCut and load project 0610."
            ),
        }
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.exception("Restore backup error")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/queue/apply")
def queue_apply_endpoint(req: ExecuteRequest):
    """Queue edits — auto-applies when CapCut quits (no manual reopen dance)."""
    if not req.actions:
        raise HTTPException(status_code=400, detail="No actions to execute")
    actions = [{"action": a.action, "params": a.params, "description": a.description} for a in req.actions]
    try:
        assert_safe_to_write(req.project_path)
    except RuntimeError:
        item = queue_apply(req.project_path, actions)
        return {
            "mode": "queued",
            "queued": True,
            "count": len(actions),
            "message": (
                f"Queued {len(actions)} change(s). Agent will auto-close the project in CapCut "
                "and apply when the timeline unlocks."
            ),
            "status": item.status,
        }

    from agent.actions import execute_actions
    from core.episodic_memory import record_approval
    from core.project_ledger import record_applied_edits

    results, suffix = apply_with_ui_handoff(
        req.project_path,
        lambda: execute_actions(actions, req.project_path),
    )
    record_applied_edits(req.project_path, actions)
    record_approval(req.project_path, actions)
    sync_capcut(req.project_path)
    reply = format_execute_reply(results) + suffix
    record_assistant_reply(reply)
    return {"mode": "immediate", "reply": reply, "queued": False}


@app.get("/queue/status")
def queue_status():
    item = get_queue()
    if not item:
        return {"queued": False, "capcut_running": is_capcut_running()}
    from capcut.project_ui import accessibility_enabled

    return {
        "queued": True,
        "status": item.status,
        "count": len(item.actions),
        "message": item.message,
        "results": item.results,
        "capcut_running": is_capcut_running(),
        "can_apply_now": can_write_safely(item.project_path),
        "accessibility_enabled": accessibility_enabled(),
    }


@app.delete("/queue")
def queue_cancel():
    clear_queue()
    return {"cancelled": True}


@app.post("/preview/edits")
def preview_edits_endpoint(req: ExecuteRequest):
    """Before/after preview for proposed actions (no disk writes)."""
    if not req.actions:
        raise HTTPException(status_code=400, detail="No actions to preview")
    from agent.diff import compute_edit_diff

    actions = [
        {"action": a.action, "params": a.params, "description": a.description}
        for a in req.actions
    ]
    return compute_edit_diff(req.project_path, actions)


@app.post("/execute/stream")
def execute_stream_endpoint(req: ExecuteRequest):
    if not req.actions:
        raise HTTPException(status_code=400, detail="No actions to execute")
    actions = [{"action": a.action, "params": a.params, "description": a.description} for a in req.actions]

    def wrapped():
        from agent.streaming import sse_line

        yield sse_line({
            "type": "step",
            "id": "handoff",
            "status": "running",
            "label": "Closing project in CapCut so edits can write to disk…",
        })
        try:
            assert_safe_to_write(req.project_path)
        except RuntimeError as e:
            item = queue_apply(req.project_path, actions)
            yield sse_line({
                "type": "step",
                "id": "handoff",
                "status": "error",
                "label": "Could not unlock project — queued for auto-apply",
                "detail": str(e),
            })
            yield sse_line({
                "type": "done",
                "reply": f"**{len(actions)} edits queued.** {e}",
                "queued": True,
            })
            return

        yield sse_line({
            "type": "step",
            "id": "handoff",
            "status": "done",
            "label": "Timeline unlocked — applying edits…",
        })

        last_done = None
        for line in iter_execute_sse(actions, req.project_path):
            if line.startswith("data: "):
                try:
                    ev = json.loads(line[6:].strip())
                    if ev.get("type") == "done":
                        last_done = ev
                except json.JSONDecodeError:
                    pass
            yield line

        yield sse_line({
            "type": "step",
            "id": "reopen",
            "status": "running",
            "label": "Reopening project in CapCut…",
        })
        reopened = reopen_project(req.project_path)
        yield sse_line({
            "type": "step",
            "id": "reopen",
            "status": "done" if reopened else "error",
            "label": "Project reopened in CapCut" if reopened else "Edits saved — tap your project in CapCut",
        })

        if last_done and last_done.get("results"):
            results = last_done["results"]
            reply = format_execute_reply(results)
            sync_hint = capcut_sync_hint(req.project_path, reopened=reopened)
            reply += f"\n\n{sync_hint}"
            record_assistant_reply(reply)
            from core.episodic_memory import record_approval

            record_approval(req.project_path, actions)
            sync_capcut(req.project_path)
            yield sse_line({
                "type": "done",
                "reply": reply,
                "results": results,
                "capcut_sync_hint": sync_hint,
                "reopened": reopened,
            })

    return StreamingResponse(
        wrapped(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.post("/execute")
def execute_endpoint(req: ExecuteRequest):
    if not req.actions:
        raise HTTPException(status_code=400, detail="No actions to execute")
    try:
        assert_safe_to_write(req.project_path)
        actions = [
            {"action": a.action, "params": a.params, "description": a.description}
            for a in req.actions
        ]
        from agent.actions import execute_actions
        from core.episodic_memory import record_approval
        from core.project_ledger import record_applied_edits

        results, suffix = apply_with_ui_handoff(
            req.project_path,
            lambda: execute_actions(actions, req.project_path),
        )
        record_applied_edits(req.project_path, actions)
        record_approval(req.project_path, actions)
        reply = format_execute_reply(results) + suffix
        record_assistant_reply(reply)
        cdp_result = sync_capcut(req.project_path)
        reopen_project(req.project_path)
        return {"reply": reply, "cdp": cdp_result, "reload_required": False}
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.exception("Execute error")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/reject")
def reject_endpoint(req: RejectRequest):
    from core.episodic_memory import record_rejection

    actions = [
        {"action": a.action, "params": a.params, "description": a.description}
        for a in (req.actions or [])
    ]
    record_rejection(req.project_path, actions, req.reason)
    reply = reject_actions(req.reason or "Changes rejected. Let me know what you'd like instead.")
    return {"reply": reply}


@app.get("/status")
def status():
    from capcut.accessibility import accessibility_report

    acc = accessibility_report()
    pages = get_pages()
    catalog = get_stats()
    return {
        "backend": "running",
        "ffmpeg": _check_ffmpeg(),
        "catalog_total": catalog.get("total", 0),
        "cdp_connected": is_connected(),
        "cdp_pages": len(pages),
        "capcut_launch_hint": (
            "Launch CapCut with: open /Applications/CapCut.app --args --remote-debugging-port=9222"
            if not is_connected()
            else None,
        ),
        "capcut_running": is_capcut_running(),
        "apply_queue": _queue_payload(),
        "accessibility_enabled": acc["enabled"],
        "accessibility_host_app": acc["host_app"],
        "whisper": _whisper_status(),
        "llm": _llm_status(),
    }


def _llm_status() -> dict:
    from agent.runtime.model import (
        gemini_available,
        groq_available,
        list_ollama_models,
        ollama_available,
        provider_order,
        resolve_ollama_model,
    )

    order = provider_order()
    return {
        "available": bool(order),
        "provider_order": order,
        "ollama": {
            "running": ollama_available(),
            "model": resolve_ollama_model() if ollama_available() else None,
            "models_installed": list_ollama_models()[:8],
        },
        "groq": groq_available(),
        "gemini": gemini_available(),
    }


def _whisper_status() -> dict:
    from analysis.whisper_cache import cache_stats
    from analysis.whisper_captions import WHISPER_INSTALL_HINT, whisper_available

    return {
        "available": whisper_available(),
        "cache": cache_stats(),
        "install_hint": WHISPER_INSTALL_HINT,
    }


def _queue_payload() -> dict | None:
    item = get_queue()
    if not item:
        return None
    return {
        "status": item.status,
        "count": len(item.actions),
        "message": item.message,
    }


def _check_ffmpeg() -> bool:
    import shutil
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


class TeamStartRequest(BaseModel):
    message: str
    project_path: str


class TeamFeedbackRequest(BaseModel):
    feedback: str


class TeamRejectTaskRequest(BaseModel):
    reason: str = ""


class TeamApproveRequest(BaseModel):
    """Fallback when in-memory session expired (e.g. uvicorn --reload)."""
    project_path: str | None = None
    actions: list[ActionItem] | None = None


@app.post("/team/start")
def team_start(req: TeamStartRequest):
    """Create a multi-agent edit session (Director → Planner → task queue)."""
    from core.task_queue import start_session

    if not req.project_path or not Path(req.project_path).exists():
        raise HTTPException(status_code=400, detail="Invalid project_path")
    session = start_session(req.project_path, req.message)
    # Planning runs in /team/stream — avoids blocking on LLM and duplicate work
    return session.to_dict()


@app.get("/team/sessions")
def team_sessions():
    from core.task_queue import list_sessions

    return {"sessions": list_sessions()}


@app.get("/team/session/{session_id}")
def team_session(session_id: str):
    from core.task_queue import get_session

    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.to_dict()


@app.get("/team/stream/{session_id}")
def team_stream(session_id: str):
    """SSE: Director → Planner → Specialists → QA → awaiting human approval."""
    from core.agent_loop import iter_team_sse

    return StreamingResponse(
        iter_team_sse(session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.post("/team/session/{session_id}/approve")
def team_approve(session_id: str):
    """Apply all QA-approved tasks from a team session."""
    from core.agent_loop import apply_session_tasks
    from agent.brain import format_execute_reply, record_assistant_reply

    try:
        assert_safe_to_write(
            get_session_project_path(session_id)
        )
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    try:
        results, suffix = apply_session_tasks(session_id)
        reply = format_execute_reply(results) + suffix
        record_assistant_reply(reply)
        return {"reply": reply, "results": results}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Team apply error")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/team/session/{session_id}/approve/stream")
def team_approve_stream(session_id: str, req: TeamApproveRequest | None = None):
    """SSE: unlock CapCut → apply each team task → CDP reload → reopen."""
    from core.agent_loop import iter_apply_actions_sse, resolve_team_apply_actions
    from agent.brain import record_assistant_reply
    from agent.streaming import sse_line

    req = req or TeamApproveRequest()
    fallback_actions = None
    if req.actions:
        fallback_actions = [
            {"action": a.action, "params": a.params, "description": a.description}
            for a in req.actions
        ]
    try:
        project_path, actions = resolve_team_apply_actions(
            session_id,
            project_path=req.project_path,
            actions=fallback_actions,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    def wrapped():
        yield sse_line({
            "type": "step",
            "id": "handoff",
            "status": "running",
            "label": "Closing project in CapCut so edits can write to disk…",
        })
        try:
            assert_safe_to_write(project_path)
        except RuntimeError as e:
            item = queue_apply(project_path, actions)
            yield sse_line({
                "type": "step",
                "id": "handoff",
                "status": "error",
                "label": "Could not unlock project — queued for auto-apply",
                "detail": str(e),
            })
            yield sse_line({
                "type": "done",
                "reply": f"**{len(actions)} team task(s) queued.** {e}",
                "queued": True,
                "status": item.status,
            })
            return

        yield sse_line({
            "type": "step",
            "id": "handoff",
            "status": "done",
            "label": "Timeline unlocked — applying team tasks…",
        })

        last_done = None
        for line in iter_apply_actions_sse(project_path, actions, session_id=session_id):
            if line.startswith("data: "):
                try:
                    ev = json.loads(line[6:].strip())
                    if ev.get("type") == "done":
                        last_done = ev
                except json.JSONDecodeError:
                    pass
            yield line

        if last_done and last_done.get("reply"):
            record_assistant_reply(last_done["reply"])

    return StreamingResponse(
        wrapped(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.post("/team/session/{session_id}/pause")
def team_pause(session_id: str):
    from core.task_queue import pause_session

    if not pause_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"paused": True, "session_id": session_id}


@app.post("/team/session/{session_id}/resume")
def team_resume(session_id: str):
    from core.task_queue import resume_session

    if not resume_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"resumed": True, "session_id": session_id}


@app.post("/team/session/{session_id}/feedback")
def team_feedback(session_id: str, req: TeamFeedbackRequest):
    """Human redirects the team mid-session."""
    from core.task_queue import set_human_feedback

    session = set_human_feedback(session_id, req.feedback)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "feedback": req.feedback}


@app.post("/team/session/{session_id}/task/{task_id}/reject")
def team_reject_task(session_id: str, task_id: str, req: TeamRejectTaskRequest):
    from core.task_queue import reject_task

    task = reject_task(session_id, task_id, req.reason)
    if not task:
        raise HTTPException(status_code=404, detail="Task or session not found")
    return {"rejected": True, "task": task.to_dict()}


@app.get("/team/slice/{domain}")
def team_slice(domain: str, project_path: str):
    """Debug: view domain slice (never full JSON)."""
    from core.slices import get_slice_for_task_type

    if domain not in ("video", "audio", "text", "effects", "timeline"):
        raise HTTPException(status_code=400, detail="domain must be video|audio|text|effects|timeline")
    key = "timeline" if domain == "timeline" else domain
    from core.slices import get_timeline_summary

    if domain == "timeline":
        return get_timeline_summary(project_path)
    return get_slice_for_task_type(project_path, key)


def get_session_project_path(session_id: str) -> str:
    from core.task_queue import get_session

    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.project_path


@app.get("/health")
def health():
    return {"status": "running"}


@app.get("/accessibility")
def accessibility_check():
    """Which app needs Accessibility + whether UI automation works right now."""
    from capcut.accessibility import accessibility_report

    return accessibility_report()
