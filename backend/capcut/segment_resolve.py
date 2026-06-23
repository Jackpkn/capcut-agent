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


def _clip_by_index(video_clips: list[dict], index: int) -> dict | None:
    for clip in video_clips:
        if clip.get("index") == index:
            return clip
    if 1 <= index <= len(video_clips):
        return video_clips[index - 1]
    return None


def clips_without_transition(video_clips: list[dict]) -> list[dict]:
    """Cuts with no transition after them (transition field null in summary)."""
    return [c for c in video_clips if not c.get("transition")]


def parse_transition_placement_hint(message: str) -> dict:
    """
    Read placement from the human message only (scoped transition targeting).
    Transitions attach AFTER a clip — on the cut to the next clip.
    """
    if not message:
        return {}

    human = message.lower()

    if any(
        p in human
        for p in (
            "at the end",
            "at end",
            "end of the video",
            "end of video",
            "last clip",
            "final clip",
            "outro",
            "ending",
        )
    ):
        return {"placement": "end"}

    if any(
        p in human
        for p in (
            "at the start",
            "start of the video",
            "start of video",
            "first clip",
            "beginning",
            "intro",
            "opening",
        )
    ):
        return {"placement": "first"}

    between = re.search(
        r"between\s+(?:clip\s*)?#?(\d+)\s+and\s+(?:clip\s*)?#?(\d+)",
        human,
    )
    if between:
        return {
            "placement": "between",
            "after_clip_index": int(between.group(1)),
        }

    after = re.search(r"after\s+(?:clip\s*)?#?(\d+)", human)
    if after:
        return {"placement": "after_clip", "after_clip_index": int(after.group(1))}

    on_clip = re.search(
        r"(?:on|to)\s+(?:clip\s*)?#?(\d+)(?:\s|$|[^0-9])",
        human,
    )
    if on_clip:
        return {"placement": "after_clip", "after_clip_index": int(on_clip.group(1))}

    return {}


def _clip_for_segment(video_clips: list[dict], segment_id: str) -> dict | None:
    for clip in video_clips:
        if clip.get("segment_id") == segment_id:
            return clip
    return None


def _explicit_transition_target(merged: dict, user_message: str) -> bool:
    """True when the human named a specific cut (honor even if it already has a transition)."""
    if merged.get("segment_id") or merged.get("clip_index") is not None:
        return True
    if merged.get("after_clip_index") is not None:
        return True
    placement = str(merged.get("placement") or "").lower()
    if placement in ("end", "last", "first", "start", "between", "after_clip"):
        return True
    return bool(parse_transition_placement_hint(user_message))


def resolve_transition_target(
    params: dict,
    video_clips: list[dict],
    *,
    user_message: str = "",
) -> str | None:
    """
    Pick which video segment gets the transition (transition sits after that clip).

    Vague "add transition" → first cut with no transition yet.
    Never refuse just because another cut already has one.
    """
    if not video_clips:
        return None

    hints = parse_transition_placement_hint(user_message)
    merged: dict = {**hints, **{k: v for k, v in (params or {}).items() if v is not None}}
    explicit = _explicit_transition_target(merged, user_message)

    candidate: str | None = None

    seg = merged.get("segment_id")
    if seg:
        candidate = resolve_video_segment_id(str(seg), video_clips)

    if not candidate:
        for key in ("clip_index", "after_clip_index"):
            raw = merged.get(key)
            if raw is not None:
                clip = _clip_by_index(video_clips, int(raw))
                if clip:
                    candidate = clip["segment_id"]
                    break

    if not candidate:
        placement = str(merged.get("placement") or "").lower()
        if placement in ("end", "last"):
            candidate = video_clips[-1]["segment_id"]
        elif placement in ("first", "start"):
            candidate = video_clips[0]["segment_id"]
        elif placement in ("between", "after_clip") and merged.get("after_clip_index"):
            clip = _clip_by_index(video_clips, int(merged["after_clip_index"]))
            if clip:
                candidate = clip["segment_id"]

    if not candidate:
        missing = clips_without_transition(video_clips)
        candidate = missing[0]["segment_id"] if missing else video_clips[-1]["segment_id"]

    clip = _clip_for_segment(video_clips, candidate)
    if clip and clip.get("transition") and not explicit:
        missing = clips_without_transition(video_clips)
        if missing:
            return missing[0]["segment_id"]

    return candidate


def clips_needing_transition(video_clips: list[dict]) -> list[dict]:
    """All cuts that do not have a transition yet (for batch adds)."""
    return clips_without_transition(video_clips)


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
            existing = clip.get("transition")
            if existing:
                out.setdefault("existing_transition", existing)
            break
    return out


def normalize_pending_params(
    action: str,
    params: dict,
    video_clips: list[dict],
    *,
    user_message: str = "",
) -> dict | None:
    """Return fixed params or None if the action cannot be applied."""
    if action not in SEGMENT_ID_ACTIONS:
        return params

    p = dict(params)

    if action == "add_transition":
        if not video_clips:
            return None
        resolved = resolve_transition_target(p, video_clips, user_message=user_message)
        if not resolved:
            return None
        p["segment_id"] = resolved
        if user_message:
            p["user_message"] = user_message
        return enrich_segment_params(p, video_clips)

    seg = p.get("segment_id")
    resolved = resolve_video_segment_id(str(seg), video_clips) if seg else None
    if not resolved:
        return None

    p["segment_id"] = resolved
    return enrich_segment_params(p, video_clips)
