"""Route tasks to the correct specialist (domain slice only)."""

from __future__ import annotations

from core.models import Task, TaskType
from core.slices import get_slice_for_task_type


def _execute_rules_specialist(task: Task, project_path: str) -> Task:
    """Rule-based reasoning when LLM unavailable."""
    slice_data = get_slice_for_task_type(project_path, task.type.value)
    task.context_summary = _summarize_slice(task.type, slice_data)

    if task.type == TaskType.VIDEO:
        task.agent_reasoning = _video_reasoning(task, slice_data)
    elif task.type == TaskType.AUDIO:
        task.agent_reasoning = _audio_reasoning(task, slice_data)
    elif task.type == TaskType.TEXT:
        task.agent_reasoning = _text_reasoning(task, slice_data)
    elif task.type == TaskType.EFFECTS:
        task.agent_reasoning = _effects_reasoning(task, slice_data)
    else:
        task.agent_reasoning = f"Prepared {task.action}"

    return task


def execute_specialist(task: Task, project_path: str, emit=None) -> Task:
    """
    Specialist validates task against its domain slice via LLM agent loop.
    Falls back to rule-based reasoning when Groq is unavailable.
    """
    from agent.agents.specialist_agent import run_llm_specialist

    updated = run_llm_specialist(task, project_path, emit=emit)
    if updated is not None:
        return updated
    return _execute_rules_specialist(task, project_path)


def _summarize_slice(task_type: TaskType, data: dict) -> dict:
    if task_type == TaskType.VIDEO:
        return {"clips": len(data.get("clips", [])), "domain": "video"}
    if task_type == TaskType.AUDIO:
        return {"tracks": len(data.get("tracks", [])), "domain": "audio"}
    if task_type == TaskType.TEXT:
        return {
            "overlays": len(data.get("overlays", [])),
            "caption_clips": len(data.get("caption_clips", [])),
            "domain": "text",
        }
    if task_type == TaskType.EFFECTS:
        return {
            "transitions": data.get("transition_count", 0),
            "domain": "effects",
        }
    return {"domain": task_type.value}


def _video_reasoning(task: Task, data: dict) -> str:
    clips = data.get("clips", [])
    seg = task.params.get("segment_id", "")[:8]
    if task.action == "update_clip_speed":
        return f"Video Agent: set segment {seg}… to {task.params.get('speed')}x ({len(clips)} clips in slice)"
    if task.action == "reorder_clips":
        return "Video Agent: reorder clips for stronger story flow"
    return f"Video Agent: {task.description}"


def _audio_reasoning(task: Task, data: dict) -> str:
    if task.action in ("add_music", "replace_music"):
        return f"Audio Agent: {task.action} — {task.params.get('query', 'catalog track')}"
    return f"Audio Agent: {task.description}"


def _text_reasoning(task: Task, data: dict) -> str:
    if task.action == "generate_captions":
        n = len(data.get("caption_clips", []))
        return f"Text Agent: Whisper speech-sync on {n} clip(s), word-level timing"
    return f"Text Agent: {task.description}"


def _effects_reasoning(task: Task, data: dict) -> str:
    if task.action == "add_transition":
        return f"FX Agent: transition on segment {str(task.params.get('segment_id', ''))[:8]}…"
    return f"FX Agent: {task.description}"
