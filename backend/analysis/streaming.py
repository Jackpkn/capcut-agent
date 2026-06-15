"""SSE streaming project analysis — video → audio → suggestions."""

from __future__ import annotations

import time

from agent.brain import set_analysis_context, set_clip_intelligence_context
from agent.streaming import sse_line
from analysis.analyzer import (
    ISSUE_LABELS,
    _make_issue,
    _score_from_issues,
    analyze_pacing,
    analyze_audio_quality,
    analyze_video_quality,
)
from analysis.cache import set_cached
from analysis.ffmpeg_probe import probe_file
from analysis.media_preview import (
    audio_waveform_peaks,
    clip_thumbnail_base64,
    merge_waveform_peaks,
)
from analysis.clip_intelligence import iter_understand_sse, director_clip_summaries
from analysis.suggestions import build_report_text, issues_to_actions
from capcut.reader import get_project_summary, read_project


def iter_analyze_sse(project_path: str, max_clips: int = 8):
    yield sse_line({
        "type": "phase",
        "id": "video",
        "status": "running",
        "progress": 5,
        "label": "Checking your video…",
        "detail": "Checking for flicker, blur, shaking, and pacing across clips…",
    })

    summary = get_project_summary(project_path)
    data = read_project(project_path)
    materials = {v["id"]: v for v in data.get("materials", {}).get("videos", [])}
    clips = summary.get("video_clips", [])[:max_clips]
    total = max(len(clips), 1)

    clip_reports: list[dict] = []
    all_waveforms: list[list[float]] = []
    path_cache: dict[str, dict] = {}

    for idx, clip in enumerate(clips):
        material = materials.get(clip.get("material_id", ""), {})
        path = material.get("path", "")
        name = clip.get("name", f"Clip {clip.get('index', idx + 1)}")
        thumb = clip_thumbnail_base64(path) if path else None
        video_issue_types: list[str] = []
        video_q: dict = {}

        if path:
            if path not in path_cache:
                probe = probe_file(path)
                if probe:
                    video_q = analyze_video_quality(path) if probe.get("video") else {}
                    path_cache[path] = {"probe": probe, "video": video_q}
            else:
                video_q = path_cache[path].get("video", {})
            video_issue_types = video_q.get("issues", [])

        yield sse_line({
            "type": "clip_preview",
            "index": clip.get("index", idx + 1),
            "name": name,
            "thumbnail": thumb,
            "issues": video_issue_types,
            "segment_id": clip.get("segment_id"),
        })
        progress = 5 + int(((idx + 1) / total) * 45)
        yield sse_line({
            "type": "phase",
            "id": "video",
            "status": "running",
            "progress": progress,
            "label": "Checking your video…",
            "detail": f"Scanned clip {idx + 1} of {len(clips)}",
        })
        time.sleep(0.04)

    yield sse_line({
        "type": "phase",
        "id": "video",
        "status": "done",
        "progress": 52,
        "label": "Video check complete",
        "detail": f"{len(clips)} clip(s) scanned",
    })

    yield sse_line({
        "type": "phase",
        "id": "audio",
        "status": "running",
        "progress": 58,
        "label": "Checking audio…",
        "detail": "Checking volume, noise, clipping, and silence…",
    })

    audio_markers: list[float] = []

    for idx, clip in enumerate(clips):
        material = materials.get(clip.get("material_id", ""), {})
        path = material.get("path", "")
        audio_q: dict = {}
        audio_issue_objs: list[dict] = []

        if path:
            if path not in path_cache:
                probe = probe_file(path)
                if probe:
                    path_cache[path] = {"probe": probe, "video": {}}
            audio_q = analyze_audio_quality(path)
            audio_issue_objs = [
                _make_issue(t, ISSUE_LABELS.get(t, t), clip=clip.get("name", ""), segment_id=clip.get("segment_id"))
                for t in audio_q.get("issues", [])
            ]
            all_waveforms.append(audio_waveform_peaks(path))
            if audio_q.get("issues"):
                audio_markers.append(round((idx + 0.5) / total, 3))

        video_q = path_cache.get(path, {}).get("video", {}) if path else {}
        video_issue_objs = [
            _make_issue(t, ISSUE_LABELS.get(t, t), clip=clip.get("name", ""), segment_id=clip.get("segment_id"))
            for t in video_q.get("issues", [])
        ]
        issues = video_issue_objs + audio_issue_objs

        clip_reports.append({
            **clip,
            "analysis": {
                "path": path,
                "video": video_q,
                "audio": audio_q,
                "issues": issues,
                "score": _score_from_issues(issues),
            },
        })

        progress = 58 + int(((idx + 1) / total) * 28)
        yield sse_line({
            "type": "phase",
            "id": "audio",
            "status": "running",
            "progress": progress,
            "label": "Checking audio…",
            "detail": f"Audio clip {idx + 1} of {len(clips)}",
        })
        time.sleep(0.04)

    combined = merge_waveform_peaks(all_waveforms)
    yield sse_line({"type": "waveform", "peaks": combined, "markers": audio_markers})
    yield sse_line({
        "type": "phase",
        "id": "audio",
        "status": "done",
        "progress": 88,
        "label": "Audio check complete",
        "detail": "Volume and clarity scanned",
    })

    clip_intel: list[dict] = []
    for event in iter_understand_sse(project_path, max_clips=max_clips):
        yield sse_line(event)
        if event.get("type") == "understand_done":
            clip_intel = event.get("clips") or []
    set_clip_intelligence_context(clip_intel)

    yield sse_line({
        "type": "phase",
        "id": "suggestions",
        "status": "running",
        "progress": 92,
        "label": "Suggesting improvements…",
        "detail": "Building auto-fix plan from findings…",
    })

    pacing_issues = analyze_pacing(summary)
    all_issues: list[dict] = []
    for cr in clip_reports:
        all_issues.extend(cr.get("analysis", {}).get("issues", []))
    all_issues.extend(pacing_issues)
    fixable = [i for i in all_issues if i.get("type") != "pacing_stats"]
    overall_score = _score_from_issues(fixable)
    suggestions = issues_to_actions(fixable, summary)

    result = {
        "score": overall_score,
        "clips_analyzed": len(clip_reports),
        "total_clips": len(summary.get("video_clips", [])),
        "total_issues": len(fixable),
        "issues": all_issues,
        "clip_reports": clip_reports,
        "pacing": pacing_issues,
        "summary": summary,
        "suggested_actions": suggestions,
        "report": build_report_text({
            "score": overall_score,
            "clips_analyzed": len(clip_reports),
            "total_clips": len(summary.get("video_clips", [])),
            "total_issues": len(fixable),
            "issues": all_issues,
            "clip_reports": clip_reports,
        }),
        "waveform_peaks": combined,
        "audio_markers": audio_markers,
        "clip_intelligence": clip_intel,
        "clip_intelligence_summary": director_clip_summaries(clip_intel) if clip_intel else [],
    }

    set_cached(project_path, result)
    set_analysis_context({
        "score": overall_score,
        "issues": all_issues,
        "clips_analyzed": len(clip_reports),
    })

    yield sse_line({
        "type": "phase",
        "id": "suggestions",
        "status": "done",
        "progress": 100,
        "label": "Analysis complete",
        "detail": f"Score {overall_score}/100 · {len(fixable)} issue(s) · {len(suggestions)} fix(es)",
    })
    yield sse_line({"type": "done", "result": result})
