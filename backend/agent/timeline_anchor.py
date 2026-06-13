"""Resolve where on the timeline an edit lands — for chat + team UI."""

from __future__ import annotations


def describe_timeline_target(
    action: str,
    params: dict,
    summary: dict | None,
) -> dict:
    """Human-readable placement: at_sec, target label, clip name."""
    if not summary:
        return {}

    clips = {c["segment_id"]: c for c in summary.get("video_clips", [])}
    texts = {t["text_id"]: t for t in summary.get("text_overlays", [])}
    seg_id = params.get("segment_id")
    text_id = params.get("text_id")

    if seg_id and seg_id in clips:
        c = clips[seg_id]
        return {
            "at_sec": c.get("at_sec"),
            "duration_sec": c.get("duration_sec"),
            "target": c.get("name") or f"clip {c.get('index', '?')}",
            "segment_id": seg_id,
        }

    if text_id and text_id in texts:
        t = texts[text_id]
        return {
            "at_sec": t.get("at_sec"),
            "duration_sec": t.get("duration_sec"),
            "target": (t.get("content") or "caption")[:40],
            "text_id": text_id,
        }

    if action in ("add_music", "replace_music"):
        start = params.get("start_sec", 0)
        return {"at_sec": start, "target": params.get("query") or "music bed"}

    if action in ("add_transition",):
        if seg_id:
            c = clips.get(seg_id, {})
            return {
                "at_sec": c.get("at_sec"),
                "target": c.get("name") or "clip",
                "segment_id": seg_id,
            }

    if action in ("add_text_template", "add_effect", "add_sticker"):
        start = params.get("start_sec", 0)
        return {
            "at_sec": start,
            "duration_sec": params.get("duration_sec"),
            "target": params.get("query") or action.replace("_", " "),
        }

    if action in ("generate_image", "generate_video_clip"):
        return {
            "at_sec": params.get("start_sec", 0),
            "duration_sec": params.get("duration_sec"),
            "target": params.get("prompt", "")[:48] or "AI asset",
        }

    if action == "reorder_clips":
        a = clips.get(params.get("segment_id_a", ""), {})
        b = clips.get(params.get("segment_id_b", ""), {})
        return {
            "at_sec": a.get("at_sec"),
            "target": f"{a.get('name', '?')} ↔ {b.get('name', '?')}",
        }

    return {}
