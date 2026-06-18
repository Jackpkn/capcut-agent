"""Effective preset config + music selection helpers."""

from __future__ import annotations

import copy

from agent.director import PRESETS
from capcut.catalog import search_catalog
from capcut.media_names import is_background_music_name


def effective_preset_config(preset_id: str) -> dict:
    """Return preset config — preset_id is chosen by the Director LLM."""
    return copy.deepcopy(PRESETS.get(preset_id, PRESETS["custom"]))


def timeline_music_names(summary: dict) -> set[str]:
    names: set[str] = set()
    for audio in summary.get("audio_clips", []):
        name = (audio.get("name") or "").lower().strip()
        if is_background_music_name(name):
            names.add(name)
    return names


def music_on_timeline(summary: dict, music_name: str) -> bool:
    needle = music_name.lower()
    return any(needle in name or name in needle for name in timeline_music_names(summary))


def pick_fresh_music(cfg: dict, summary: dict) -> dict | None:
    """Find catalog music that is not already on the timeline."""
    on_timeline = timeline_music_names(summary)
    terms = list(cfg.get("music_search", ()))
    fallbacks = ("cinematic", "chill", "acoustic", "pop", "happy", "fun")
    seen_terms: set[str] = set()
    for term in terms + list(fallbacks):
        if term in seen_terms:
            continue
        seen_terms.add(term)
        for hit in search_catalog(term, "music", limit=5):
            name_l = (hit.get("name") or "").lower()
            if not name_l:
                continue
            if any(name_l in on or on in name_l for on in on_timeline):
                continue
            return hit
    return None


def music_action_for_preset(
    cfg: dict,
    summary: dict,
    *,
    volume: float = 0.62,
) -> dict | None:
    """Params for add_music or replace_music, or None if nothing new to add."""
    from agent.plan_guard import should_change_music

    if not should_change_music(cfg, summary):
        return None

    hit = pick_fresh_music(cfg, summary)
    if not hit:
        return None
    dur = summary.get("overview", {}).get("duration_sec")
    params: dict = {"query": hit["name"], "start_sec": 0, "volume": volume}
    if dur and dur > 0:
        params["clip_duration_sec"] = float(dur)
    if hit.get("resource_id"):
        params["resource_id"] = hit["resource_id"]
    has_bg = bool(timeline_music_names(summary))
    params["_action"] = "replace_music" if has_bg else "add_music"
    return params
