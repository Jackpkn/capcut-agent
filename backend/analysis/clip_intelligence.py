"""System 1 — per-clip understanding (FFmpeg + optional Gemini vision, all local/free)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

from analysis.analyzer import _score_from_issues, _make_issue, ISSUE_LABELS
from analysis.clip_cache import get_cached_clip, list_project_clips, set_cached_clip
from analysis.clip_frames import extract_frame_jpeg, sample_timestamps
from analysis.ffmpeg_probe import analyze_audio_quality, analyze_video_quality, probe_file
from analysis.vision_local import describe_frame, vision_available
from capcut.reader import get_project_summary, read_project

logger = logging.getLogger(__name__)


def _log_clip(msg: str, **fields: object) -> None:
    from agent.runtime.agent_log import agent as log_agent
    log_agent(msg, **fields)


def _source_mtime(path: str) -> float:
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0


def _heuristic_from_ffmpeg(
    *,
    clip: dict,
    video_q: dict,
    audio_q: dict,
    issues: list[dict],
) -> dict:
    duration = float(clip.get("duration_sec") or 0)
    motion = float(video_q.get("motion") or 0)
    brightness = float(video_q.get("brightness") or 128)
    issue_types = {i.get("type") for i in issues}

    if "blurry" in issue_types or "too_dark" in issue_types:
        scene_type = "low quality footage"
        emotion = "unclear"
        suggested = "trim or cut"
        hook = 0.2
    elif motion > 28:
        scene_type = "high motion / action"
        emotion = "energetic, dynamic"
        suggested = "hook candidate" if duration <= 6 else "highlight moment"
        hook = 0.75
    elif brightness > 180:
        scene_type = "bright outdoor or well-lit"
        emotion = "upbeat, open"
        suggested = "establishing or b-roll"
        hook = 0.5
    elif brightness < 45:
        scene_type = "dark / indoor / night"
        emotion = "moody, intimate"
        suggested = "atmosphere b-roll"
        hook = 0.35
    else:
        scene_type = "general b-roll"
        emotion = "neutral, calm"
        suggested = "middle section"
        hook = 0.45

    if "shaky" in issue_types:
        suggested = "stabilize or trim"
        hook *= 0.7
    if "long_clip" in issue_types:
        suggested = "trim for pacing"
    if "short_clip" in issue_types and hook > 0.5:
        suggested = "hook candidate"

    has_speech = (
        audio_q.get("silence_seconds", 99) < duration * 0.6
        if duration > 0
        else False
    )
    audio_type = "speech" if has_speech else "ambient"
    if audio_q.get("issues") and "quiet" in audio_q.get("issues", []):
        audio_type = "quiet speech" if has_speech else "quiet ambient"

    quality_score = round(_score_from_issues(issues) / 100.0, 2)
    best_moment = round(min(duration * 0.4, max(0.0, duration - 0.5)), 2) if duration else 0.0
    if motion > 28:
        best_moment = round(min(duration * 0.25, duration), 2)

    return {
        "content": f"{clip.get('name', 'Clip')} — {scene_type}",
        "emotion": emotion,
        "scene_type": scene_type,
        "objects": [],
        "has_face": False,
        "hook_strength": round(hook, 2),
        "quality_note": "good" if quality_score > 0.7 else "soft",
        "suggested_use": suggested,
        "best_moment_sec": best_moment,
        "has_speech": has_speech,
        "audio_type": audio_type,
        "quality_score": quality_score,
    }


def understand_one_clip(
    project_path: str,
    clip: dict,
    *,
    material_path: str = "",
    force_refresh: bool = False,
) -> dict:
    """Build or load understanding for one timeline clip."""
    segment_id = clip.get("segment_id") or ""
    path = material_path or clip.get("source_path") or ""
    mtime = _source_mtime(path) if path else 0.0

    if segment_id and not force_refresh:
        cached = get_cached_clip(
            project_path, segment_id,
            source_path=path, source_mtime=mtime,
        )
        if cached:
            _log_clip("clip cache hit", name=clip.get("name"), segment_id=segment_id[:8])
            return cached

    _log_clip("clip understand", name=clip.get("name"), source="ffmpeg+vision")

    duration = float(clip.get("duration_sec") or 0)
    video_q: dict = {}
    audio_q: dict = {}
    issues: list[dict] = []

    if path and Path(path).exists():
        probe = probe_file(path)
        if probe:
            if probe.get("video"):
                video_q = analyze_video_quality(path)
            audio_q = analyze_audio_quality(path)
            issues = [
                _make_issue(t, ISSUE_LABELS.get(t, t), clip=clip.get("name", ""), segment_id=segment_id)
                for t in video_q.get("issues", []) + audio_q.get("issues", [])
            ]

    heuristic = _heuristic_from_ffmpeg(
        clip=clip, video_q=video_q, audio_q=audio_q, issues=issues,
    )

    source = "heuristic"
    vision_data: dict | None = None
    if path and vision_available():
        ts = sample_timestamps(duration or 3.0, count=1)[0]
        frame = extract_frame_jpeg(path, ts)
        if frame:
            vision_data = describe_frame(
                frame,
                clip_name=clip.get("name", ""),
                duration_sec=duration,
            )

    if vision_data:
        source = "hybrid" if heuristic else "vision"
        content = vision_data.get("content") or heuristic["content"]
        emotion = vision_data.get("emotion") or heuristic["emotion"]
        scene_type = vision_data.get("scene_type") or heuristic["scene_type"]
        objects = list(vision_data.get("objects") or [])
        hook = float(vision_data.get("hook_strength") or heuristic["hook_strength"])
        quality_note = vision_data.get("quality_note") or heuristic["quality_note"]
        has_face = bool(vision_data.get("has_face"))
        if hook >= 0.65 and duration <= 8:
            suggested = "hook candidate"
        elif hook >= 0.55:
            suggested = "highlight moment"
        else:
            suggested = heuristic["suggested_use"]
    else:
        content = heuristic["content"]
        emotion = heuristic["emotion"]
        scene_type = heuristic["scene_type"]
        objects = heuristic["objects"]
        hook = heuristic["hook_strength"]
        quality_note = heuristic["quality_note"]
        has_face = heuristic["has_face"]
        suggested = heuristic["suggested_use"]

    quality_score = heuristic["quality_score"]
    if quality_note in ("dark", "overexposed", "soft"):
        quality_score = min(quality_score, 0.55)

    record = {
        "segment_id": segment_id,
        "index": clip.get("index"),
        "name": clip.get("name", ""),
        "duration_sec": duration,
        "at_sec": clip.get("at_sec"),
        "content": content,
        "emotion": emotion,
        "scene_type": scene_type,
        "objects": objects,
        "has_face": has_face,
        "hook_strength": round(hook, 2),
        "quality_score": quality_score,
        "quality_note": quality_note,
        "best_moment_sec": heuristic["best_moment_sec"],
        "has_speech": heuristic["has_speech"],
        "audio_type": heuristic["audio_type"],
        "suggested_use": suggested,
        "ffmpeg_issues": [i.get("type") for i in issues if i.get("type")],
        "source": source,
        "source_path": path,
        "source_mtime": mtime,
        "vision_available": vision_available(),
    }

    if segment_id:
        set_cached_clip(project_path, segment_id, record)
    _log_clip(
        "clip done",
        name=record.get("name"),
        source=record.get("source"),
        hook=record.get("hook_strength"),
    )
    return record


def understand_project(
    project_path: str,
    *,
    max_clips: int = 24,
    force_refresh: bool = False,
) -> list[dict]:
    summary = get_project_summary(project_path)
    data = read_project(project_path)
    materials = {v["id"]: v for v in data.get("materials", {}).get("videos", [])}
    clips = summary.get("video_clips", [])[:max_clips]

    results: list[dict] = []
    for clip in clips:
        material = materials.get(clip.get("material_id", ""), {})
        path = material.get("path", "")
        results.append(
            understand_one_clip(
                project_path, clip,
                material_path=path,
                force_refresh=force_refresh,
            )
        )
    return results


def iter_understand_sse(
    project_path: str,
    *,
    max_clips: int = 24,
    force_refresh: bool = False,
) -> Iterator[dict]:
    """Yield progress events then final clip list."""
    summary = get_project_summary(project_path)
    data = read_project(project_path)
    materials = {v["id"]: v for v in data.get("materials", {}).get("videos", [])}
    clips = summary.get("video_clips", [])[:max_clips]
    total = max(len(clips), 1)

    yield {
        "type": "phase",
        "id": "understand",
        "status": "running",
        "progress": 0,
        "label": "Understanding clips…",
        "detail": (
            "FFmpeg + optional Gemini vision (your key) — no CapCut Pro"
            if vision_available()
            else "FFmpeg heuristics — add GEMINI_API_KEY for richer descriptions"
        ),
    }

    results: list[dict] = []
    for idx, clip in enumerate(clips):
        material = materials.get(clip.get("material_id", ""), {})
        path = material.get("path", "")
        record = understand_one_clip(
            project_path, clip,
            material_path=path,
            force_refresh=force_refresh,
        )
        results.append(record)
        yield {
            "type": "clip_understanding",
            "clip": record,
            "index": idx + 1,
            "total": total,
        }
        progress = int(((idx + 1) / total) * 100)
        yield {
            "type": "phase",
            "id": "understand",
            "status": "running",
            "progress": progress,
            "label": "Understanding clips…",
            "detail": f"{record.get('name', 'Clip')} — {record.get('content', '')[:60]}",
        }

    yield {
        "type": "phase",
        "id": "understand",
        "status": "done",
        "progress": 100,
        "label": "Clip understanding complete",
        "detail": f"{len(results)} clip(s) indexed",
    }
    yield {"type": "understand_done", "clips": results}


def director_clip_summaries(clips: list[dict]) -> list[dict]:
    """Strip segment IDs for Director strategic layer."""
    return [
        {
            "index": c.get("index"),
            "name": c.get("name"),
            "duration_sec": c.get("duration_sec"),
            "content": c.get("content"),
            "emotion": c.get("emotion"),
            "scene_type": c.get("scene_type"),
            "objects": c.get("objects", [])[:6],
            "hook_strength": c.get("hook_strength"),
            "quality_score": c.get("quality_score"),
            "best_moment_sec": c.get("best_moment_sec"),
            "suggested_use": c.get("suggested_use"),
            "has_speech": c.get("has_speech"),
            "audio_type": c.get("audio_type"),
        }
        for c in clips
    ]


def load_project_intelligence(project_path: str) -> list[dict]:
    if not project_path:
        return []
    cached = list_project_clips(project_path)
    if cached:
        return cached
    return []


def hook_clip_index(clips: list[dict]) -> int | None:
    if not clips:
        return None
    best = max(clips, key=lambda c: float(c.get("hook_strength") or 0))
    if float(best.get("hook_strength") or 0) < 0.5:
        return None
    return best.get("index")
