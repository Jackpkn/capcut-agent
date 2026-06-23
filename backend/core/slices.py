"""Domain slices — agents never receive full draft_info.json."""

from __future__ import annotations

from capcut.reader import get_project_summary, list_video_segments_for_captions, read_project


def _compact_clips(clips: list[dict], limit: int = 20) -> list[dict]:
    return [
        {
            "index": c.get("index"),
            "segment_id": c.get("segment_id"),
            "name": c.get("name"),
            "at_sec": c.get("at_sec"),
            "duration_sec": c.get("duration_sec"),
            "speed": c.get("speed"),
            "volume": c.get("volume"),
            "track_index": c.get("track_index"),
            "transition": c.get("transition"),
        }
        for c in clips[:limit]
    ]


def timeline_summary_from_project_summary(summary: dict) -> dict:
    """One-page project view from an already-loaded summary (no disk read)."""
    overview = summary.get("overview", {})
    return {
        "duration_sec": overview.get("duration_sec"),
        "fps": overview.get("fps"),
        "video_clip_count": overview.get("video_clip_count"),
        "audio_clip_count": overview.get("audio_clip_count"),
        "text_overlay_count": overview.get("text_overlay_count"),
        "transition_count": overview.get("transition_count"),
        "effect_count": overview.get("effect_count"),
        "video_clips": _compact_clips(summary.get("video_clips", [])),
        "audio_clips": _compact_clips(summary.get("audio_clips", [])),
        "text_overlays": [
            {
                "index": t.get("index"),
                "text_id": t.get("text_id"),
                "content": (t.get("content") or "")[:80],
                "at_sec": t.get("at_sec"),
                "duration_sec": t.get("duration_sec"),
            }
            for t in summary.get("text_overlays", [])[:15]
        ],
    }


def get_timeline_summary(project_path: str) -> dict:
    """One-page project view for Director / Planner (no raw JSON)."""
    return timeline_summary_from_project_summary(get_project_summary(project_path))


def get_video_slice(project_path: str) -> dict:
    data = read_project(project_path)
    summary = get_project_summary(project_path)
    return {
        "tracks": [t for t in data.get("tracks", []) if t.get("type") == "video"],
        "videos": data.get("materials", {}).get("videos", []),
        "speeds": data.get("materials", {}).get("speeds", []),
        "clips": _compact_clips(summary.get("video_clips", [])),
        "duration": data.get("duration"),
        "fps": data.get("fps"),
    }


def get_audio_slice(project_path: str) -> dict:
    data = read_project(project_path)
    summary = get_project_summary(project_path)
    return {
        "tracks": [t for t in data.get("tracks", []) if t.get("type") == "audio"],
        "audios": data.get("materials", {}).get("audios", []),
        "speeds": data.get("materials", {}).get("speeds", []),
        "clips": _compact_clips(summary.get("audio_clips", [])),
    }


def get_text_slice(project_path: str) -> dict:
    data = read_project(project_path)
    summary = get_project_summary(project_path)
    return {
        "tracks": [t for t in data.get("tracks", []) if t.get("type") == "text"],
        "texts": data.get("materials", {}).get("texts", []),
        "text_templates": data.get("materials", {}).get("text_templates", []),
        "overlays": summary.get("text_overlays", [])[:20],
        "caption_clips": list_video_segments_for_captions(data)[:10],
    }


def get_effects_slice(project_path: str) -> dict:
    data = read_project(project_path)
    return {
        "tracks": [
            t for t in data.get("tracks", [])
            if t.get("type") in ("effect", "sticker")
        ],
        "video_effects": data.get("materials", {}).get("video_effects", []),
        "transitions": data.get("materials", {}).get("transitions", []),
        "stickers": data.get("materials", {}).get("stickers", []),
        "transition_count": len(data.get("materials", {}).get("transitions", [])),
    }


def get_slice_for_task_type(project_path: str, task_type: str) -> dict:
    loaders = {
        "video": get_video_slice,
        "audio": get_audio_slice,
        "text": get_text_slice,
        "effects": get_effects_slice,
    }
    loader = loaders.get(task_type, get_timeline_summary)
    return loader(project_path)
