"""AI director — creative brief + style presets before tool proposals."""

from __future__ import annotations

from dataclasses import dataclass, field

PRESETS: dict[str, dict] = {
    "travel_vlog": {
        "label": "Travel vlog",
        "keywords": ("travel", "vlog", "trip", "bali", "vacation", "journey", "wander"),
        "mood": "fun",
        "speed": 1.1,
        "speed_clips": "all",
        "transition_query": "fade",
        "music_search": ("cinematic", "chill", "acoustic", "pop", "fun"),
        "replace_music": True,
        "captions": True,
        "hook_style": "best_moment_first",
        "max_clip_sec": 9,
        "caption_style": "short punchy lines, location names, 3-5 words per line",
    },
    "tiktok_viral": {
        "label": "TikTok viral",
        "keywords": ("tiktok", "viral", "reels", "shorts", "hype", "insane"),
        "mood": "energetic",
        "speed": 1.25,
        "speed_clips": "2-",
        "transition_query": "pull in",
        "music_search": ("adrenaline", "intense", "action"),
        "replace_music": True,
        "captions": True,
        "hook_style": "instant_hook",
        "max_clip_sec": 2.5,
        "caption_style": "ALL CAPS hooks, emoji sparingly, max 4 words",
    },
    "cinematic": {
        "label": "Cinematic",
        "keywords": ("cinematic", "film", "movie", "netflix", "trailer", "dramatic"),
        "mood": "dramatic",
        "speed": 1.0,
        "speed_clips": "none",
        "transition_query": "fade",
        "music_search": ("cinematic", "epic", "emotional"),
        "replace_music": True,
        "captions": False,
        "hook_style": "slow_build",
        "max_clip_sec": 12,
        "caption_style": "minimal or none",
    },
    "energetic": {
        "label": "Energetic montage",
        "keywords": ("energetic", "fast", "pump", "montage"),
        "mood": "energetic",
        "speed": 1.2,
        "speed_clips": "2-3",
        "transition_query": "pull in",
        "music_search": ("adrenaline", "action", "intense"),
        "replace_music": True,
        "captions": False,
        "hook_style": "energy_burst",
        "max_clip_sec": 6,
        "caption_style": "optional",
    },
}


@dataclass
class EditBrief:
    preset_id: str
    preset_label: str
    audience: str
    hook: str
    arc: str
    music_direction: str
    caption_direction: str
    platform: str
    creative_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "preset_id": self.preset_id,
            "preset_label": self.preset_label,
            "audience": self.audience,
            "hook": self.hook,
            "arc": self.arc,
            "music_direction": self.music_direction,
            "caption_direction": self.caption_direction,
            "platform": self.platform,
            "creative_notes": self.creative_notes,
        }


def detect_preset(message: str) -> str | None:
    """Pick preset with the most keyword hits (e.g. cinematic + travel → travel_vlog)."""
    lower = message.lower()
    best_id: str | None = None
    best_score = 0
    for preset_id, cfg in PRESETS.items():
        score = sum(1 for kw in cfg["keywords"] if kw in lower)
        if score > best_score:
            best_score = score
            best_id = preset_id
    return best_id


def _pick_hook_clip(clips: list[dict], style: str) -> dict:
    if not clips:
        return {}
    if style == "best_moment_first":
        return max(clips, key=lambda c: c.get("duration_sec", 0))
    if style == "instant_hook":
        return min(clips, key=lambda c: c.get("at_sec", 0))
    return clips[0]


def build_edit_brief(
    user_message: str,
    summary: dict,
    preset_id: str | None = None,
) -> EditBrief:
    from agent.preset_config import effective_preset_config

    preset_id = preset_id or detect_preset(user_message) or "energetic"
    cfg = effective_preset_config(preset_id, user_message)
    clips = summary.get("video_clips", [])
    hook_clip = _pick_hook_clip(clips, cfg.get("hook_style", "energy_burst"))
    hook_idx = hook_clip.get("index", 1) if hook_clip else 1
    hook_name = hook_clip.get("name", f"clip {hook_idx}") if hook_clip else "opening"

    platform = "TikTok / Reels"
    if preset_id == "cinematic":
        platform = "YouTube / long-form"
    elif preset_id == "travel_vlog":
        platform = "Instagram + YouTube travel"

    notes = [
        f"Preset: **{cfg['label']}** — {cfg['mood']} mood",
        f"Target clip length feel: ~{cfg['max_clip_sec']}s max per beat",
    ]
    if cfg.get("captions"):
        notes.append("Captions: on (short, designed — run Whisper when available)")
    if cfg.get("replace_music"):
        notes.append("Replace background music to match mood")

    return EditBrief(
        preset_id=preset_id,
        preset_label=cfg["label"],
        audience=f"{platform} viewers — scroll-stopping travel/content",
        hook=f"Lead with **{hook_name}** (clip {hook_idx}) — strongest visual in first 1–2s",
        arc=_arc_for_preset(preset_id, len(clips)),
        music_direction=f"{cfg['mood']} bed — search: {', '.join(cfg['music_search'])}",
        caption_direction=cfg.get("caption_style", "none"),
        platform=platform,
        creative_notes=notes,
    )


def _arc_for_preset(preset_id: str, clip_count: int) -> str:
    if preset_id == "travel_vlog":
        return "Establish place → highlights → people/food → golden moment → soft outro"
    if preset_id == "tiktok_viral":
        return "Hook (0–2s) → rapid hits → peak → hard stop before attention drops"
    if preset_id == "cinematic":
        return "Slow open → build tension → emotional peak → fade out"
    return f"Pulse energy across {clip_count} clips — no lull longer than 3s"


def brief_to_markdown(brief: EditBrief) -> str:
    lines = [
        f"## Director brief — {brief.preset_label}",
        f"**Platform:** {brief.platform}",
        f"**Audience:** {brief.audience}",
        f"**Hook:** {brief.hook}",
        f"**Story arc:** {brief.arc}",
        f"**Music:** {brief.music_direction}",
        f"**Captions:** {brief.caption_direction}",
        "",
        "**Creative notes:**",
    ]
    lines.extend(f"- {n}" for n in brief.creative_notes)
    return "\n".join(lines)
