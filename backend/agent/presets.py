"""Turn director presets into concrete CapCut edit proposals."""

from __future__ import annotations

from agent.director import PRESETS, EditBrief
from agent.preset_config import effective_preset_config, music_action_for_preset
from capcut.catalog import search_catalog


def _clip_indices_for_speed(spec: str, clip_count: int) -> set[int]:
    if spec == "all":
        return set(range(1, clip_count + 1))
    if spec == "none":
        return set()
    if spec == "2-3":
        return {2, 3}
    if spec == "2-":
        return set(range(2, clip_count + 1))
    return set()


def plan_from_preset(
    brief: EditBrief,
    user_message: str,
    summary: dict,
    project_path: str | None,
) -> list:
    """Preset-driven plan merged with message-specific heuristic rules."""
    from agent.brain import (
        PendingAction,
        _build_heuristic_plan,
        _dedupe_pending,
        _segment_ids_with_transitions,
        _tool_to_pending,
    )

    cfg = effective_preset_config(brief.preset_id, user_message)
    clips = sorted(summary.get("video_clips", []), key=lambda c: c["at_sec"])
    pending: list[PendingAction] = []

    has_transitions = (
        _segment_ids_with_transitions(project_path) if project_path else set()
    )

    speed_val = cfg.get("speed", 1.0)
    target_nums = _clip_indices_for_speed(cfg.get("speed_clips", "all"), len(clips))
    for i, clip in enumerate(clips, start=1):
        if i not in target_nums:
            continue
        current = float(clip.get("speed") or 1.0)
        if abs(current - speed_val) < 0.01:
            continue
        from agent.plan_guard import enrich_speed_description
        from agent.actions import describe_action

        sparams = enrich_speed_description({
            "segment_id": clip["segment_id"],
            "speed": speed_val,
        }, summary)
        spa = _tool_to_pending("propose_update_clip_speed", sparams)
        spa.description = describe_action("update_clip_speed", sparams)
        pending.append(spa)

    trans_query = cfg.get("transition_query", "fade")
    hits = search_catalog(trans_query, "transition", limit=1)
    t_name = hits[0]["name"] if hits else trans_query.title()
    t_rid = hits[0].get("resource_id") if hits else None
    for clip in clips[:-1]:
        if clip["segment_id"] in has_transitions:
            continue
        params: dict = {
            "segment_id": clip["segment_id"],
            "query": t_name,
            "duration_sec": 0.4 if brief.preset_id == "tiktok_viral" else 0.6,
        }
        if t_rid:
            params["resource_id"] = t_rid
        pending.append(_tool_to_pending("propose_add_transition", params))

    from agent.plan_guard import should_generate_captions

    if cfg.get("replace_music") or "music" in user_message.lower():
        music_params = music_action_for_preset(cfg, summary, user_message=user_message)
        if music_params:
            action = music_params.pop("_action", "replace_music")
            tool = "propose_replace_music" if action == "replace_music" else "propose_add_music"
            pending.append(_tool_to_pending(tool, music_params))

    if should_generate_captions(cfg, summary, user_message):
        cap_params: dict = {
            "style": brief.preset_id,
            "max_words_per_line": 4 if brief.preset_id == "tiktok_viral" else 6,
        }
        if cfg.get("visible_captions"):
            cap_params["visible_captions"] = True
        pending.append(_tool_to_pending("propose_generate_captions", cap_params))

    if "reorder" in user_message.lower() and len(clips) >= 2:
        pending.append(_tool_to_pending("propose_reorder_clips", {
            "segment_id_a": clips[0]["segment_id"],
            "segment_id_b": clips[-1]["segment_id"],
        }))

    heuristic = _build_heuristic_plan(user_message, summary, project_path)
    pending.extend(heuristic)

    pending = _dedupe_pending(pending)

    from agent.plan_guard import collapse_redundant_pending

    if project_path:
        pending = collapse_redundant_pending(pending, summary, project_path)

    return pending


def _minimum_preset_actions(
    brief: EditBrief,
    user_message: str,
    summary: dict,
    project_path: str | None,
) -> list:
    """When idempotency skips everything, still propose core preset changes."""
    from agent.brain import PendingAction, _tool_to_pending

    cfg = effective_preset_config(brief.preset_id, user_message)
    pending: list[PendingAction] = []
    clips = sorted(summary.get("video_clips", []), key=lambda c: c["at_sec"])

    music_params = music_action_for_preset(cfg, summary)
    if music_params:
        action = music_params.pop("_action", "replace_music")
        tool = "propose_replace_music" if action == "replace_music" else "propose_add_music"
        pending.append(_tool_to_pending(tool, music_params))

    if cfg.get("captions") or "caption" in user_message.lower():
        cap_params: dict = {
            "style": brief.preset_id,
            "max_words_per_line": 4 if brief.preset_id == "tiktok_viral" else 6,
        }
        if cfg.get("visible_captions"):
            cap_params["visible_captions"] = True
        pending.append(_tool_to_pending("propose_generate_captions", cap_params))

    speed_val = cfg.get("speed", 1.0)
    target_nums = _clip_indices_for_speed(cfg.get("speed_clips", "all"), len(clips))
    for i, clip in enumerate(clips, start=1):
        if i not in target_nums:
            continue
        current = float(clip.get("speed") or 1.0)
        if abs(current - speed_val) < 0.01:
            continue
        pending.append(_tool_to_pending("propose_update_clip_speed", {
            "segment_id": clip["segment_id"],
            "speed": speed_val,
        }))

    if not pending and clips and project_path:
        trans_query = cfg.get("transition_query", "fade")
        hits = search_catalog(trans_query, "transition", limit=1)
        if hits and clips:
            pending.append(_tool_to_pending("propose_add_transition", {
                "segment_id": clips[0]["segment_id"],
                "query": hits[0]["name"],
                "resource_id": hits[0].get("resource_id"),
                "duration_sec": 0.6,
            }))

    return pending
