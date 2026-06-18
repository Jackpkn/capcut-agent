"""Guards and idempotency for edit plans — avoid wrong/stale timeline edits."""

from __future__ import annotations

from capcut.guard import is_project_locked
from capcut.reader import get_project_summary

from agent.brain import PendingAction, _empty_timeline_reply
from agent.preset_config import timeline_music_names


def timeline_edit_blockers(project_path: str) -> tuple[bool, str, list[str]]:
    """
    Returns (blocked, user_message, warnings).
    blocked=True → do not plan or apply edits.
    """
    warnings: list[str] = []
    try:
        summary = get_project_summary(project_path)
    except Exception as exc:
        return True, f"Could not read project: {exc}", warnings

    clip_count = summary.get("overview", {}).get("video_clip_count", 0)
    if clip_count == 0:
        return True, _empty_timeline_reply(), warnings

    if is_project_locked(project_path):
        warnings.append(
            "Project is **open in CapCut** (`.locked`). What you see may differ from disk — "
            "press **Cmd+S**, click **Home**, then re-run the plan before approving."
        )

    return False, "", warnings


def should_change_music(cfg: dict, summary: dict) -> bool:
    """Only touch music when the Director preset asks for it."""
    if not cfg.get("replace_music"):
        return False
    names = timeline_music_names(summary)
    if not names:
        return True
    if len(names) > 1:
        return True
    return False


def should_generate_captions(cfg: dict, summary: dict) -> bool:
    if not cfg.get("captions"):
        return False
    overlays = summary.get("text_overlays", [])
    if len(overlays) >= 3:
        return False
    return True


def enrich_speed_description(params: dict, summary: dict) -> dict:
    """Add clip index/name so tasks are distinguishable in the UI."""
    seg = params.get("segment_id")
    if not seg:
        return params
    for i, clip in enumerate(summary.get("video_clips", []), start=1):
        if clip.get("segment_id") == seg:
            out = dict(params)
            out["clip_index"] = i
            name = clip.get("name") or ""
            if name:
                out["clip_name"] = name[:40]
            return out
    return params


def collapse_redundant_pending(
    pending: list[PendingAction],
    summary: dict,
    project_path: str,
) -> list[PendingAction]:
    """Drop no-op / redundant proposals before they become tasks."""
    clips = {c["segment_id"]: c for c in summary.get("video_clips", [])}
    music_names = timeline_music_names(summary)
    kept: list[PendingAction] = []
    seen: set[tuple[str, str]] = set()

    for item in pending:
        key = (item.action, json_key(item.params))
        if key in seen:
            continue

        if item.action == "update_clip_speed":
            seg = item.params.get("segment_id")
            target = float(item.params.get("speed", 1.0))
            clip = clips.get(seg, {})
            current = float(clip.get("speed") or 1.0)
            if abs(current - target) < 0.01:
                continue
            item.params = enrich_speed_description(item.params, summary)
            from agent.actions import describe_action
            item.description = describe_action(item.action, item.params)

        if item.action == "replace_music":
            query = (item.params.get("query") or "").lower()
            if query and any(query in n or n in query for n in music_names):
                continue

        if item.action == "add_music":
            query = (item.params.get("query") or "").lower()
            if query and any(query in n or n in query for n in music_names):
                continue

        if item.action == "generate_captions":
            if len(summary.get("text_overlays", [])) >= 8:
                continue

        if item.action in (
            "update_clip_speed", "add_transition", "trim_clip", "move_segment",
            "set_segment_visibility",
        ):
            seg = item.params.get("segment_id")
            if seg and seg not in clips:
                continue

        seen.add(key)
        kept.append(item)

    return kept


def json_key(params: dict) -> str:
    import json
    return json.dumps(params, sort_keys=True)
