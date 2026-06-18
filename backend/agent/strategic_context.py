"""Layer 1 context — metadata only, no segment IDs."""

from __future__ import annotations

from core.chapters import default_chapters_from_timeline


def build_strategic_context(
    timeline_summary: dict,
    analysis: dict | None = None,
) -> dict:
    """
    What the Director may see: duration, counts, chapter time ranges, analysis.
    Never includes segment_id or full clip lists.
    """
    duration = timeline_summary.get("duration_sec")
    clip_count = timeline_summary.get("video_clip_count", 0)
    hints = default_chapters_from_timeline(timeline_summary)

    ctx = {
        "duration_sec": duration,
        "fps": timeline_summary.get("fps"),
        "video_clip_count": clip_count,
        "audio_clip_count": timeline_summary.get("audio_clip_count", 0),
        "text_overlay_count": timeline_summary.get("text_overlay_count", 0),
        "transition_count": timeline_summary.get("transition_count", 0),
        "suggested_chapter_count": len(hints),
        "suggested_chapters": [
            {
                "index": h.index,
                "start_sec": h.start_sec,
                "end_sec": h.end_sec,
                "label": h.label,
                "clip_count": h.clip_count,
            }
            for h in hints
        ],
    }

    if analysis:
        ctx["analysis"] = {
            "score": analysis.get("score"),
            "clips_analyzed": analysis.get("clips_analyzed"),
            "issue_types": list({
                i.get("type") for i in (analysis.get("issues") or []) if i.get("type")
            })[:8],
        }

    from core.episodic_memory import load_user_preferences

    prefs = load_user_preferences()
    if prefs.get("preferred_transitions"):
        ctx["user_preferred_transitions"] = prefs["preferred_transitions"]
    if prefs.get("rejects"):
        ctx["recent_rejects"] = [r.get("reason") or "" for r in prefs["rejects"] if r.get("reason")][:5]

    from agent import brain as brain_module

    clips = brain_module.clip_intelligence_context
    if clips:
        from analysis.clip_intelligence import director_clip_summaries, hook_clip_index

        summaries = director_clip_summaries(clips)
        ctx["clip_intelligence"] = summaries
        hook_idx = hook_clip_index(clips)
        if hook_idx is not None:
            ctx["suggested_hook_clip_index"] = hook_idx
        best = max(clips, key=lambda c: float(c.get("hook_strength") or 0), default=None)
        if best and float(best.get("hook_strength") or 0) >= 0.5:
            ctx["suggested_hook"] = {
                "clip_index": best.get("index"),
                "name": best.get("name"),
                "reason": best.get("content"),
                "hook_strength": best.get("hook_strength"),
            }

    return ctx
