from capcut.reader import get_project_summary, read_project
from analysis.ffmpeg_probe import analyze_audio_quality, analyze_video_quality, probe_file

ISSUE_LABELS = {
    "too_dark": "Clip is too dark",
    "overexposed": "Clip is overexposed",
    "low_contrast": "Low contrast / flat image",
    "shaky": "High camera shake or motion",
    "rapid_cuts": "Very rapid scene changes",
    "blurry": "Possibly blurry or soft focus",
    "quiet": "Audio too quiet",
    "loud": "Audio too loud",
    "clipping": "Audio clipping detected",
    "long_silence": "Long silence gaps in audio",
    "short_clip": "Clip very short — may feel rushed",
    "long_clip": "Clip very long — pacing may drag",
    "fast_speed": "Clip sped up significantly",
    "low_volume": "Timeline volume below 50%",
    "text_overlap": "Text overlays overlap on timeline",
    "short_transition": "Transition very short",
    "long_transition": "Transition very long",
}

SEVERITY = {
    "clipping": "critical",
    "blurry": "warning",
    "shaky": "warning",
    "too_dark": "warning",
    "overexposed": "warning",
    "quiet": "warning",
    "loud": "warning",
    "long_silence": "info",
    "low_volume": "info",
    "fast_speed": "info",
    "short_clip": "info",
    "long_clip": "info",
    "text_overlap": "info",
    "short_transition": "info",
    "long_transition": "info",
    "low_contrast": "info",
    "rapid_cuts": "info",
}


def _score_from_issues(issues: list[dict]) -> int:
    if not issues:
        return 100
    # One penalty per (clip, issue type) — avoid stacked flags crushing score to 0
    seen: set[tuple[str, str]] = set()
    penalty = 0
    for issue in issues:
        if issue.get("type") == "pacing_stats":
            continue
        key = (issue.get("clip") or "", issue.get("type") or "")
        if key in seen:
            continue
        seen.add(key)
        sev = issue.get("severity", "info")
        if sev == "critical":
            penalty += 20
        elif sev == "warning":
            penalty += 8
        else:
            penalty += 3
    penalty = min(penalty, 75)
    return max(20, 100 - penalty)


def _make_issue(issue_type: str, message: str, clip: str = "", **extra) -> dict:
    return {
        "type": issue_type,
        "severity": SEVERITY.get(issue_type, "info"),
        "message": message,
        "clip": clip,
        **extra,
    }


def analyze_pacing(summary: dict) -> list[dict]:
    issues = []
    clips = summary.get("video_clips", [])
    durations = [c["duration_sec"] for c in clips if c.get("duration_sec")]

    for clip in clips:
        dur = clip.get("duration_sec", 0)
        name = clip.get("name", "Clip")
        if 0 < dur < 0.5:
            issues.append(_make_issue(
                "short_clip",
                f'"{name}" is only {dur}s — may feel too fast',
                clip=name,
                segment_id=clip.get("segment_id"),
            ))
        elif dur > 8:
            issues.append(_make_issue(
                "long_clip",
                f'"{name}" is {dur}s — consider trimming for pacing',
                clip=name,
                segment_id=clip.get("segment_id"),
            ))
        if clip.get("speed", 1) > 1.5:
            issues.append(_make_issue(
                "fast_speed",
                f'"{name}" is at {clip["speed"]}x speed',
                clip=name,
                segment_id=clip.get("segment_id"),
                speed=clip["speed"],
            ))
        if clip.get("volume", 1) < 0.5:
            issues.append(_make_issue(
                "low_volume",
                f'"{name}" timeline volume is {int(clip["volume"] * 100)}%',
                clip=name,
                segment_id=clip.get("segment_id"),
                volume=clip["volume"],
            ))

    texts = summary.get("text_overlays", [])
    for i, t1 in enumerate(texts):
        end1 = t1["at_sec"] + t1["duration_sec"]
        for t2 in texts[i + 1:]:
            if t2["at_sec"] < end1:
                issues.append(_make_issue(
                    "text_overlap",
                    f'Text "{t1["content"][:20]}" overlaps with "{t2["content"][:20]}"',
                    clip=t1.get("content", "")[:30],
                ))
                break

    for trans in summary.get("transitions", []):
        dur = trans.get("duration_sec", 0)
        if 0 < dur < 0.2:
            issues.append(_make_issue(
                "short_transition",
                f'Transition "{trans["name"]}" is only {dur}s',
                clip=trans["name"],
                transition_id=trans.get("id"),
            ))
        elif dur > 1.5:
            issues.append(_make_issue(
                "long_transition",
                f'Transition "{trans["name"]}" is {dur}s — may feel slow',
                clip=trans["name"],
                transition_id=trans.get("id"),
            ))

    if durations:
        avg = sum(durations) / len(durations)
        issues.append({
            "type": "pacing_stats",
            "severity": "info",
            "message": f"Average clip length: {avg:.1f}s across {len(clips)} clips",
            "clip": "",
        })

    return issues


def analyze_project(project_path: str, max_clips: int = 8) -> dict:
    summary = get_project_summary(project_path)
    data = read_project(project_path)
    materials = {v["id"]: v for v in data.get("materials", {}).get("videos", [])}

    analyzed_paths: dict[str, dict] = {}
    clip_reports = []

    for clip in summary.get("video_clips", [])[:max_clips]:
        material = materials.get(clip.get("material_id", ""), {})
        path = material.get("path", "")
        if not path or path in analyzed_paths:
            if path in analyzed_paths:
                clip_reports.append({**clip, "analysis": analyzed_paths[path]})
            continue

        probe = probe_file(path)
        if not probe:
            continue

        video_q = analyze_video_quality(path) if probe.get("video") else {}
        audio_q = analyze_audio_quality(path) if probe.get("audio") else {}

        issues = []
        for issue_type in video_q.get("issues", []):
            issues.append(_make_issue(
                issue_type,
                ISSUE_LABELS.get(issue_type, issue_type),
                clip=clip.get("name", probe["name"]),
                segment_id=clip.get("segment_id"),
            ))
        for issue_type in audio_q.get("issues", []):
            issues.append(_make_issue(
                issue_type,
                ISSUE_LABELS.get(issue_type, issue_type),
                clip=clip.get("name", probe["name"]),
                segment_id=clip.get("segment_id"),
            ))

        report = {
            "path": path,
            "probe": probe,
            "video": video_q,
            "audio": audio_q,
            "issues": issues,
            "score": _score_from_issues(issues),
        }
        analyzed_paths[path] = report
        clip_reports.append({**clip, "analysis": report})

    pacing_issues = analyze_pacing(summary)
    all_issues = []
    for cr in clip_reports:
        all_issues.extend(cr.get("analysis", {}).get("issues", []))
    all_issues.extend(pacing_issues)

    fixable = [i for i in all_issues if i.get("type") != "pacing_stats"]
    overall_score = _score_from_issues(fixable)

    return {
        "score": overall_score,
        "clips_analyzed": len(clip_reports),
        "total_clips": len(summary.get("video_clips", [])),
        "total_issues": len(fixable),
        "issues": all_issues,
        "clip_reports": clip_reports,
        "pacing": pacing_issues,
        "summary": summary,
    }
