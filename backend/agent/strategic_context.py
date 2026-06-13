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

  return ctx
 