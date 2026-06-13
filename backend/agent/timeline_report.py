"""Contextual timeline visuals — only when the agent calls present_timeline."""

from __future__ import annotations

import logging

from analysis.cache import get_cached
from analysis.media_preview import audio_waveform_peaks, clip_thumbnail_base64, merge_waveform_peaks
from capcut.reader import get_project_summary, read_project
from core.slices import get_timeline_summary

logger = logging.getLogger(__name__)

_VIEWS = frozenset({"clips", "captions", "audio", "edits", "full_scan"})


def _clip_rows(
    summary: dict,
    materials: dict,
    *,
    include_thumbnails: bool,
    limit: int = 12,
) -> list[dict]:
    rows: list[dict] = []
    for clip in summary.get("video_clips", [])[:limit]:
        material = materials.get(clip.get("material_id", ""), {})
        path = material.get("path", "")
        thumb = None
        if include_thumbnails and path:
            try:
                thumb = clip_thumbnail_base64(path)
            except Exception as exc:
                logger.debug("thumb skip: %s", exc)
        rows.append({
            "index": clip.get("index"),
            "name": clip.get("name", ""),
            "at_sec": clip.get("at_sec"),
            "duration_sec": clip.get("duration_sec"),
            "thumbnail": thumb,
            "issues": [],
        })
    return rows


def _caption_rows(summary: dict) -> list[dict]:
    return [
        {
            "index": t.get("index", i),
            "content": (t.get("content") or "")[:80],
            "at_sec": t.get("at_sec"),
            "duration_sec": t.get("duration_sec"),
        }
        for i, t in enumerate(summary.get("text_overlays", []), start=1)
    ]


def build_timeline_visual(
    project_path: str,
    *,
    view: str = "clips",
    reason: str = "",
    markers: list[dict] | None = None,
    timeline_summary: dict | None = None,
    include_thumbnails: bool = False,
) -> dict:
    """
    Build a view-specific timeline payload for chat UI.
    Called only when the model invokes present_timeline — never auto-attached.
    """
    view = view if view in _VIEWS else "clips"
    if timeline_summary is None:
        timeline_summary = get_timeline_summary(project_path)

    summary = get_project_summary(project_path)
    data = read_project(project_path)
    materials = {v["id"]: v for v in data.get("materials", {}).get("videos", [])}
    duration = float(timeline_summary.get("duration_sec") or 0)
    clips = _clip_rows(summary, materials, include_thumbnails=include_thumbnails)
    captions = _caption_rows(summary)
    cached = get_cached(project_path)

    payload: dict = {
        "view": view,
        "reason": reason,
        "duration_sec": duration,
        "clip_count": len(clips),
        "clips": clips,
        "captions": captions,
        "markers": markers or [],
        "phases": {},
    }

    if view == "clips":
        payload["phases"]["video"] = {
            "status": "done",
            "label": "Clips on your timeline",
            "detail": reason or f"{len(clips)} video clip(s) in order.",
        }

    elif view == "captions":
        payload["phases"]["captions"] = {
            "status": "done",
            "label": "Captions on your timeline",
            "detail": reason or f"{len(captions)} text overlay(s).",
        }

    elif view == "audio":
        peaks: list[float] = []
        audio_markers: list[float] = []
        if cached:
            peaks = cached.get("waveform_peaks") or []
            audio_markers = cached.get("audio_markers") or []
        else:
            series: list[list[float]] = []
            for clip in summary.get("video_clips", [])[:4]:
                path = materials.get(clip.get("material_id", ""), {}).get("path", "")
                if path:
                    try:
                        series.append(audio_waveform_peaks(path, points=48))
                    except Exception:
                        pass
            if series:
                peaks = merge_waveform_peaks(series)
        payload["waveform_peaks"] = peaks
        payload["audio_markers"] = audio_markers
        payload["phases"]["audio"] = {
            "status": "done" if peaks else "pending",
            "label": "Audio on your timeline",
            "detail": reason or (
                "Volume and peaks across clips."
                if peaks
                else "Run Analyze in the sidebar for a deeper audio scan."
            ),
        }

    elif view == "edits":
        payload["phases"]["edits"] = {
            "status": "done",
            "label": "Where edits will land",
            "detail": reason or f"{len(markers or [])} placement(s) on the timeline.",
        }

    elif view == "full_scan":
        peaks = (cached or {}).get("waveform_peaks") or []
        audio_markers = (cached or {}).get("audio_markers") or []
        suggestions = []
        score = cached.get("score") if cached else None
        if cached:
            for issue in cached.get("issues", [])[:6]:
                suggestions.append({
                    "type": issue.get("type", ""),
                    "severity": issue.get("severity", "info"),
                    "message": issue.get("message", ""),
                })
        payload["waveform_peaks"] = peaks
        payload["audio_markers"] = audio_markers
        payload["suggestions"] = suggestions
        payload["score"] = score
        payload["phases"] = {
            "video": {
                "status": "done",
                "label": "Video check is done",
                "detail": reason or f"Scanned {len(clips)} clip(s).",
            },
            "audio": {
                "status": "done" if peaks else "pending",
                "label": "Audio check is done" if peaks else "Audio",
                "detail": "Volume, noise, and speech levels." if peaks else "Analyze for full audio scan.",
            },
            "suggestions": {
                "status": "done" if suggestions else "pending",
                "label": "Suggestions are ready" if suggestions else "Suggestions",
                "detail": f"Health {score}/100" if score is not None else "Propose or analyze for suggestions.",
            },
        }

    return payload
