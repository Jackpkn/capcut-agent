"""QA Agent — validate proposed tasks before human approval."""

from __future__ import annotations

from core.models import ACTION_DOMAIN, Task, TaskType, new_id
from core.slices import get_slice_for_task_type
from capcut.segment_resolve import SEGMENT_ID_ACTIONS, normalize_pending_params


def _segment_ids_in_slice(slice_data: dict, domain: str) -> set[str]:
    ids: set[str] = set()
    if domain == "video":
        for clip in slice_data.get("clips", []):
            if clip.get("segment_id"):
                ids.add(clip["segment_id"])
    elif domain == "audio":
        for clip in slice_data.get("clips", []):
            if clip.get("segment_id"):
                ids.add(clip["segment_id"])
    elif domain == "text":
        for overlay in slice_data.get("overlays", []):
            if overlay.get("segment_id"):
                ids.add(overlay["segment_id"])
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


def review_action(
    action: str,
    params: dict,
    project_path: str,
    *,
    project_summary: dict | None = None,
) -> dict:
    """QA a single pending action dict (normalize segment IDs first)."""
    from capcut.reader import get_project_summary

    summary = project_summary or get_project_summary(project_path)
    video_clips = summary.get("video_clips", [])
    normalized = normalize_pending_params(action, dict(params or {}), video_clips)
    if normalized is None and action in SEGMENT_ID_ACTIONS:
        return {
            "approved": False,
            "confidence": 0.15,
            "issues": [f"Cannot resolve segment_id for {action}"],
            "suggestion": "Re-ask using a clip # from the timeline, or save in CapCut (Cmd+S).",
            "params": params,
        }

    use_params = normalized if normalized is not None else dict(params or {})
    task = Task(
        id=new_id(),
        description="",
        instruction="",
        action=action,
        params=use_params,
        type=ACTION_DOMAIN.get(action, TaskType.EFFECTS),
    )
    result = review_task(task, project_path)
    result["params"] = use_params
    return result


def review_pending_actions(
    actions: list[dict],
    project_path: str,
    *,
    project_summary: dict | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (approved_actions, blocked_actions, review_summaries)."""
    approved: list[dict] = []
    blocked: list[dict] = []
    reviews: list[dict] = []
    for item in actions:
        rev = review_action(
            item["action"],
            item.get("params") or {},
            project_path,
            project_summary=project_summary,
        )
        reviews.append({
            "action": item["action"],
            "description": item.get("description", ""),
            "approved": rev["approved"],
            "confidence": rev["confidence"],
            "issues": rev["issues"],
        })
        out = {
            "action": item["action"],
            "params": rev["params"],
            "description": item.get("description", ""),
        }
        if rev["approved"]:
            approved.append(out)
        else:
            blocked.append({**out, "qa_issues": rev["issues"]})
    return approved, blocked, reviews
