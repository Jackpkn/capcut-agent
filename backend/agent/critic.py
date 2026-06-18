"""Second-pass review — editor critic before human approval."""

from __future__ import annotations

from agent.brain import PendingAction
from agent.director import EditBrief
from capcut.media_names import is_background_music_name


def critique_plan(
    brief: EditBrief,
    pending: list[PendingAction],
    summary: dict,
) -> list[str]:
    """Rule-based critic notes (fast, no extra LLM call)."""
    notes: list[str] = []
    clips = summary.get("video_clips", [])
    actions = {p.action for p in pending}

    if not pending:
        notes.append("No edits proposed — try a preset: *travel vlog*, *TikTok viral*, or *cinematic*.")
        return notes

    trans_on_timeline = summary.get("overview", {}).get("transition_count", 0)
    if (
        "add_transition" not in actions
        and len(clips) > 1
        and trans_on_timeline < max(len(clips) - 1, 1)
    ):
        notes.append("Consider transitions between clips for a more polished flow.")
    elif trans_on_timeline >= max(len(clips) - 1, 1):
        notes.append(f"Transitions already on timeline ({trans_on_timeline}) — good.")

    if brief.preset_id == "tiktok_viral":
        long_clips = [c for c in clips if c.get("duration_sec", 0) > 3]
        if long_clips and "trim_clip" not in actions:
            notes.append(
                f"TikTok preset: {len(long_clips)} clip(s) over 3s — trim for retention?"
            )
        if "generate_captions" not in actions:
            notes.append("Viral edits usually need captions in the first 2 seconds.")

    audio_clips = summary.get("audio_clips", [])
    bg_music = [
        a for a in audio_clips
        if is_background_music_name(str(a.get("name", "")))
    ]
    if brief.preset_id == "travel_vlog":
        if bg_music and "replace_music" not in actions and "add_music" not in actions:
            names = ", ".join(a["name"][:30] for a in bg_music[:2])
            notes.append(f"Background music already on timeline ({names}).")
        elif not bg_music and "replace_music" not in actions and "add_music" not in actions:
            notes.append("Travel vlogs benefit from a dedicated music bed — music not in plan.")

    if "update_clip_speed" in actions and brief.preset_id == "cinematic":
        notes.append("Cinematic preset: speed changes may feel un-film-like — review speeds.")

    trans_count = sum(1 for p in pending if p.action == "add_transition")
    if trans_count > len(clips):
        notes.append("Many transitions queued — ensure it doesn't feel busy.")

    if len(notes) == 0:
        notes.append("Plan aligns with director brief — good to approve.")

    return notes
