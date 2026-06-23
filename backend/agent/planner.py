"""Planner Agent (Senior Dev) — goals → concrete tasks via LLM only."""

from __future__ import annotations

from core.models import (
    SPECIALIST_FOR_TYPE,
    Task,
    TaskStatus,
    domain_for_action,
    new_id,
)
from core.slices import get_slice_for_task_type

from agent.brain import PendingAction
from agent.director import EditBrief


def _context_summary_for_action(project_path: str, action: str) -> dict:
    task_type = domain_for_action(action).value
    slice_data = get_slice_for_task_type(project_path, task_type)
    if task_type == "video":
        return {"clip_count": len(slice_data.get("clips", [])), "domain": "video"}
    if task_type == "audio":
        return {"audio_count": len(slice_data.get("clips", [])), "domain": "audio"}
    if task_type == "text":
        return {
            "overlay_count": len(slice_data.get("overlays", [])),
            "caption_clips": len(slice_data.get("caption_clips", [])),
            "domain": "text",
        }
    if task_type == "effects":
        return {
            "transitions": slice_data.get("transition_count", 0),
            "domain": "effects",
        }
    return {"domain": task_type}


def pending_to_task(pending: PendingAction, project_path: str, priority: int) -> Task:
    task_type = domain_for_action(pending.action)
    return Task(
        id=new_id(),
        type=task_type,
        instruction=pending.description,
        action=pending.action,
        params=pending.params,
        description=pending.description,
        specialist=SPECIALIST_FOR_TYPE[task_type],
        context_summary=_context_summary_for_action(project_path, pending.action),
        status=TaskStatus.PENDING,
        agent_reasoning=f"{SPECIALIST_FOR_TYPE[task_type]} will apply {pending.action} using domain slice only.",
        priority=priority,
    )


def run_planner(
    brief: EditBrief,
    user_message: str,
    project_path: str,
    goals: list | None = None,
    emit=None,
) -> tuple[list[Task], list[str]]:
    """Build task queue from director goals — LLM planner only, no preset scripts."""
    from agent.agents.planner_agent import run_llm_planner
    from agent.runtime.model import llm_available

    if not goals:
        return [], []

    llm = run_llm_planner(brief, goals, user_message, project_path, emit=emit)
    if llm is not None:
        tasks, notes = llm
        if tasks:
            return tasks, notes
        return [], list(notes) + [
            "Planner could not propose safe edits for these goals. "
            "Try rephrasing or use single-agent chat.",
        ]

    if not llm_available():
        return [], [
            "AI planner unavailable. Start Ollama (gemma4) and/or set GEMINI_API_KEY and retry — "
            "no scripted fallback is used.",
        ]

    return [], ["Planner did not return tasks. Try again or use single-agent mode."]
