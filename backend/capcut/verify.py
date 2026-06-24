"""Layer 1 — post-apply verification and self-correction guardrails."""

from __future__ import annotations

from typing import Any

from capcut.reader import get_project_summary, read_project


def _check_close(actual: float | int | None, expected: float, tol: float) -> bool:
    if actual is None:
        return False
    return abs(float(actual) - float(expected)) <= tol


def verify_project(
    project_path: str,
    expectations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify timeline state against expectations after edits.

    expectations keys (all optional):
      duration_sec, min_video_clips, max_video_clips,
      filter_name, effect_name, min_captions, music_present,
      segment_ids (list — must exist)
    """
    expectations = expectations or {}
    summary = get_project_summary(project_path)
    overview = summary.get("overview", {})
    checks: list[dict[str, Any]] = []

    if "duration_sec" in expectations:
        actual = overview.get("duration_sec")
        expected = float(expectations["duration_sec"])
        tol = float(expectations.get("duration_tolerance_sec", 1.0))
        ok = _check_close(actual, expected, tol)
        checks.append({
            "check": "duration_sec",
            "ok": ok,
            "expected": expected,
            "actual": actual,
            "tolerance_sec": tol,
        })

    if "min_video_clips" in expectations:
        actual = overview.get("video_clip_count", 0)
        expected = int(expectations["min_video_clips"])
        ok = actual >= expected
        checks.append({
            "check": "min_video_clips",
            "ok": ok,
            "expected": f">= {expected}",
            "actual": actual,
        })

    if "max_video_clips" in expectations:
        actual = overview.get("video_clip_count", 0)
        expected = int(expectations["max_video_clips"])
        ok = actual <= expected
        checks.append({
            "check": "max_video_clips",
            "ok": ok,
            "expected": f"<= {expected}",
            "actual": actual,
        })

    if expectations.get("filter_name"):
        needle = str(expectations["filter_name"]).lower()
        filters = summary.get("filters", [])
        names = [f.get("name", "").lower() for f in filters]
        ok = any(needle in n for n in names)
        checks.append({
            "check": "filter_name",
            "ok": ok,
            "expected": expectations["filter_name"],
            "actual": [f.get("name") for f in filters],
        })

    if expectations.get("effect_name"):
        needle = str(expectations["effect_name"]).lower()
        effects = summary.get("effects", [])
        names = [e.get("name", "").lower() for e in effects]
        ok = any(needle in n for n in names)
        checks.append({
            "check": "effect_name",
            "ok": ok,
            "expected": expectations["effect_name"],
            "actual": [e.get("name") for e in effects],
        })

    if "min_captions" in expectations:
        actual = overview.get("text_overlay_count", 0)
        expected = int(expectations["min_captions"])
        ok = actual >= expected
        checks.append({
            "check": "min_captions",
            "ok": ok,
            "expected": f">= {expected}",
            "actual": actual,
        })

    if expectations.get("music_present"):
        ok = overview.get("audio_clip_count", 0) > 0
        checks.append({
            "check": "music_present",
            "ok": ok,
            "expected": True,
            "actual": overview.get("audio_clip_count", 0),
        })

    if expectations.get("segment_ids"):
        data = read_project(project_path)
        known = {
            seg["id"]
            for track in data.get("tracks", [])
            for seg in track.get("segments", [])
        }
        missing = [sid for sid in expectations["segment_ids"] if sid not in known]
        ok = not missing
        checks.append({
            "check": "segment_ids",
            "ok": ok,
            "expected": expectations["segment_ids"],
            "missing": missing,
        })

    passed = all(c["ok"] for c in checks) if checks else True
    return {
        "passed": passed,
        "checks": checks,
        "overview": overview,
    }
