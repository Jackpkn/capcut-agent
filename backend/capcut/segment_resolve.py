"""Resolve LLM segment aliases to real CapCut video segment UUIDs."""

from __future__ import annotations

import re

SEGMENT_ID_ACTIONS = frozenset({
    "add_transition",
    "update_clip_speed",
    "trim_clip",
    "move_segment",
    "set_segment_visibility",
})


def resolve_video_segment_id(segment_id: str, video_clips: list[dict]) -> str | None:
    """Map segment_id, clip_2, #2, or UUID prefix → real video segment id."""
    if not video_clips:
        return None
    needle = (segment_id or "").strip()
    if not needle:
        return None

    for clip in video_clips:
        sid = clip.get("segment_id") or ""
        if sid == needle:
            return sid

    m = re.match(r"^clip[_-]?(\d+)$", needle, re.I)
    if m:
        idx = int(m.group(1))
        for clip in video_clips:
            if clip.get("index") == idx:
                return clip["segment_id"]
        if 1 <= idx <= len(video_clips):
            return video_clips[idx - 1]["segment_id"]

    m = re.match(r"^#?(\d+)$", needle)
    if m:
        idx = int(m.group(1))
        for clip in video_clips:
            if clip.get("index") == idx:
                return clip["segment_id"]
        if 1 <= idx <= len(video_clips):
            return video_clips[idx - 1]["segment_id"]

    if len(needle) >= 6:
        matches = [
            c for c in video_clips
            if (c.get("segment_id") or "").startswith(needle)
        ]
        if len(matches) == 1:
            return matches[0]["segment_id"]

    return None


def enrich_segment_params(params: dict, video_clips: list[dict]) -> dict:
    """Attach clip_index / clip_name after resolving segment_id."""
    seg = params.get("segment_id")
    if not seg:
        return params
    out = dict(params)
    for i, clip in enumerate(video_clips, start=1):
        if clip.get("segment_id") == seg:
            out.setdefault("clip_index", clip.get("index", i))
            name = clip.get("name") or ""
            if name:
                out.setdefault("clip_name", name[:40])
            break
    return out


def normalize_pending_params(
    action: str,
    params: dict,
    video_clips: list[dict],
) -> dict | None:
    """Return fixed params or None if the action cannot be applied."""
    if action not in SEGMENT_ID_ACTIONS:
        return params

    p = dict(params)
    seg = p.get("segment_id")
    resolved = resolve_video_segment_id(str(seg), video_clips) if seg else None

    if not resolved:
        if action == "add_transition" and video_clips:
            resolved = video_clips[-1]["segment_id"]
        else:
            return None

    p["segment_id"] = resolved
    return enrich_segment_params(p, video_clips)
