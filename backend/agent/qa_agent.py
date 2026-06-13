"""QA Agent — validate proposed tasks before human approval."""

from __future__ import annotations

from core.models import Task, TaskStatus, TaskType
from core.slices import get_slice_for_task_type


def _segment_ids_in_slice(slice_data: dict, domain: str) -> set[str]:
    ids: set[str] = set()
    if domain == "video":
        for clip in slice_data.get("clips", []):
            if clip.get("segment_id"):
                ids.add(clip["segment_id"])
    if domain == "audio":
        for clip in slice_data.get("clips", []):
            if clip.get("segment_id"):
                ids.add(clip["segment_id"])
    for track in slice_data.get("tracks", []):
        for seg in track.get("segments", []):
            if seg.get("id"):
                ids.add(seg["id"])
    return ids


def review_task(task: Task, project_path: str) -> dict:
    """Rule-based QA (fast, no LLM). Returns {approved, confidence, issues, suggestion}."""
    issues: list[str] = []
    domain = task.type.value
    slice_data = get_slice_for_task_type(project_path, domain)
    seg_ids = _segment_ids_in_slice(slice_data, domain)
    video_slice = get_slice_for_task_type(project_path, "video")
    video_seg_ids = _segment_ids_in_slice(video_slice, "video")

    params = task.params or {}
    action = task.action

    video_clips = video_slice.get("clips", [])
    if action in ("update_clip_speed", "trim_clip", "move_segment", "add_transition", "reorder_clips"):
        if not video_clips:
            issues.append("No video clips on timeline — save project in CapCut (Cmd+S) first")

    if domain == "video" and not video_clips:
        issues.append("No video clips on timeline — save project in CapCut (Cmd+S) first")

    if action == "update_clip_speed":
        speed = params.get("speed")
        if speed is not None and (speed < 0.1 or speed > 4.0):
            issues.append(f"Speed {speed}x is out of safe range (0.1–4.0)")
        seg = params.get("segment_id")
        if seg and seg_ids and seg not in seg_ids:
            issues.append(f"segment_id {seg[:8]}… not found in video slice")

    if action == "update_volume":
        vol = params.get("volume")
        if vol is not None and (vol < 0 or vol > 2.0):
            issues.append(f"Volume {vol} is out of range (0–2.0)")

    if action in ("add_transition", "trim_clip", "move_segment"):
        seg = params.get("segment_id")
        if seg and video_seg_ids and seg not in video_seg_ids:
            issues.append(f"segment_id {seg[:8]}… not on video timeline")

    if action == "generate_captions":
        caption_clips = slice_data.get("caption_clips", [])
        if not caption_clips and domain == "text":
            issues.append("No video clips available for caption transcription")

    if action in ("add_music", "replace_music") and not params.get("query") and not params.get("resource_id"):
        issues.append("Music task missing query or resource_id")

    if action in ("add_music", "replace_music"):
        from agent.preset_config import timeline_music_names
        query = (params.get("query") or params.get("name") or "").lower()
        on_timeline = timeline_music_names({"audio_clips": slice_data.get("clips", [])})
        if query and any(query in n or n in query for n in on_timeline):
            issues.append(f'"{params.get("query", query)}" is already on the timeline — skip music change')

    approved = len(issues) == 0
    return {
        "approved": approved,
        "confidence": 0.95 if approved else 0.4,
        "issues": issues,
        "suggestion": "Fix params and re-plan" if issues else "",
    }


def review_all_tasks(tasks: list[Task], project_path: str) -> list[Task]:
    for task in tasks:
        result = review_task(task, project_path)
        task.qa_feedback = result["issues"]
        task.qa_approved = result["approved"]
        if not result["approved"]:
            task.agent_reasoning += f" QA flagged: {'; '.join(result['issues'])}"
    return tasks
