"""Preview before/after state for proposed edits (no disk writes)."""

from __future__ import annotations

from capcut.reader import get_project_summary
from capcut.media_names import is_background_music_name


def _clip_name(summary: dict, segment_id: str) -> str:
    for clip in summary.get("video_clips", []):
        if clip["segment_id"] == segment_id:
            return clip.get("name") or f"Clip {clip.get('index', '?')}"
    for audio in summary.get("audio_clips", []):
        if audio["segment_id"] == segment_id:
            return audio.get("name") or "Audio"
    return segment_id[:8] + "…"


def _background_music_label(summary: dict) -> str:
    names = []
    for audio in summary.get("audio_clips", []):
        name = audio.get("name") or ""
        if is_background_music_name(name):
            vol = int(audio.get("volume", 1) * 100)
            names.append(f"{name} ({vol}%)")
    return ", ".join(names) if names else "—"


def compute_edit_diff(project_path: str, actions: list[dict]) -> dict:
    summary = get_project_summary(project_path)
    clips = {c["segment_id"]: c for c in summary.get("video_clips", [])}
    audio = {a["segment_id"]: a for a in summary.get("audio_clips", [])}

    rows: list[dict] = []
    trans_before = summary["overview"]["transition_count"]
    trans_adds = 0
    music_before = _background_music_label(summary)
    music_after = music_before
    swapped = False

    for item in actions:
        action = item.get("action", "")
        params = item.get("params") or {}

        if action == "update_clip_speed":
            seg_id = params.get("segment_id", "")
            clip = clips.get(seg_id, {})
            before = clip.get("speed", 1.0)
            after = params.get("speed", before)
            if before != after:
                rows.append({
                    "category": "Video",
                    "target": _clip_name(summary, seg_id),
                    "field": "Speed",
                    "before": f"{before}x",
                    "after": f"{after}x",
                })

        elif action == "update_volume":
            seg_id = params.get("segment_id", "")
            clip = clips.get(seg_id) or audio.get(seg_id, {})
            before_vol = clip.get("volume", 1.0)
            after_vol = params.get("volume", 1.0)
            if round(before_vol, 2) != round(after_vol, 2):
                cat = "Audio" if seg_id in audio and seg_id not in clips else "Video"
                rows.append({
                    "category": cat,
                    "target": _clip_name(summary, seg_id),
                    "field": "Volume",
                    "before": f"{int(before_vol * 100)}%",
                    "after": f"{int(after_vol * 100)}%",
                })

        elif action == "add_transition":
            seg_id = params.get("segment_id", "")
            name = params.get("query") or params.get("name") or "Transition"
            dur = params.get("duration_sec", 0.5)
            trans_adds += 1
            rows.append({
                "category": "Transition",
                "target": _clip_name(summary, seg_id),
                "field": "After clip",
                "before": "—",
                "after": f'{name} ({dur}s)',
            })

        elif action == "add_music":
            name = params.get("name") or params.get("query") or "Music"
            vol = int(params.get("volume", 0.8) * 100)
            start = params.get("start_sec", 0)
            music_after = f"{name} ({vol}%) @ {start}s"
            rows.append({
                "category": "Music",
                "target": "Timeline",
                "field": "Background",
                "before": music_before,
                "after": f"{music_after} (+ keep existing)",
            })

        elif action == "replace_music":
            name = params.get("name") or params.get("query") or "Music"
            vol = int(params.get("volume", 0.8) * 100)
            music_after = f"{name} ({vol}%)"
            rows.append({
                "category": "Music",
                "target": "Timeline",
                "field": "Background",
                "before": music_before,
                "after": f"{music_after} (replaces / mutes old)",
            })

        elif action == "generate_captions":
            rows.append({
                "category": "Captions",
                "target": "All clips",
                "field": "Whisper",
                "before": "—",
                "after": f'{params.get("style", "travel")} style (~{params.get("max_words_per_line", 5)} words/line)',
            })

        elif action == "reorder_clips":
            if not swapped:
                a_id = params.get("segment_id_a", "")
                b_id = params.get("segment_id_b", "")
                rows.append({
                    "category": "Video",
                    "target": f"{_clip_name(summary, a_id)} ↔ {_clip_name(summary, b_id)}",
                    "field": "Order",
                    "before": "Original order",
                    "after": "Swapped",
                })
                swapped = True

        elif action == "trim_clip":
            seg_id = params.get("segment_id", "")
            clip = clips.get(seg_id, {})
            dur_us = params.get("duration")
            after = f"{dur_us / 1_000_000:.1f}s" if dur_us else "trimmed"
            rows.append({
                "category": "Video",
                "target": _clip_name(summary, seg_id),
                "field": "Duration",
                "before": f"{clip.get('duration_sec', 0):.1f}s",
                "after": after,
            })

    return {
        "rows": rows,
        "overview": {
            "transitions_before": trans_before,
            "transitions_after": trans_before + trans_adds,
            "music_before": music_before,
            "music_after": music_after,
            "change_count": len(actions),
        },
    }
