"""Built-in CapCut colour filter catalogue (resource IDs from CapCut / capcut-cli)."""

from __future__ import annotations

# CapCut ships these filters by resource_id even when the bundle is not cached locally.
VIDEO_FILTERS: dict[str, dict[str, str]] = {
    "vintage": {
        "name": "Vintage",
        "effect_id": "7028463716732079117",
        "resource_id": "7028463716732079117",
    },
    "warm": {
        "name": "Warm",
        "effect_id": "7028463716732079118",
        "resource_id": "7028463716732079118",
    },
    "cool": {
        "name": "Cool",
        "effect_id": "7028463716732079119",
        "resource_id": "7028463716732079119",
    },
    "bw": {
        "name": "B&W",
        "effect_id": "7028463716732079120",
        "resource_id": "7028463716732079120",
    },
    "sepia": {
        "name": "Sepia",
        "effect_id": "7028463716732079121",
        "resource_id": "7028463716732079121",
    },
    "vivid": {
        "name": "Vivid",
        "effect_id": "7028463716732079122",
        "resource_id": "7028463716732079122",
    },
    "contrast": {
        "name": "Contrast",
        "effect_id": "7028463716732079123",
        "resource_id": "7028463716732079123",
    },
    "faded": {
        "name": "Faded",
        "effect_id": "7028463716732079124",
        "resource_id": "7028463716732079124",
    },
    "dramatic": {
        "name": "Dramatic",
        "effect_id": "7028463716732079125",
        "resource_id": "7028463716732079125",
    },
    "soft": {
        "name": "Soft",
        "effect_id": "7028463716732079126",
        "resource_id": "7028463716732079126",
    },
}

# Agent-facing preset names → CapCut filter slug.
COLOR_PRESET_TO_FILTER: dict[str, str] = {
    "cinematic": "dramatic",
    "cinematic_film": "dramatic",
    "film": "dramatic",
    "movie": "dramatic",
    "dramatic": "dramatic",
    "warm": "warm",
    "warm_tone": "warm",
    "cool": "cool",
    "cool_blue": "cool",
    "vintage": "vintage",
    "vivid": "vivid",
    "teal_orange": "contrast",
    "teal": "contrast",
    "orange": "warm",
    "moody": "dramatic",
    "moody_dark": "dramatic",
    "dark": "dramatic",
    "faded": "faded",
    "soft": "soft",
    "contrast": "contrast",
    "sepia": "sepia",
    "bw": "bw",
    "black_and_white": "bw",
}


def normalize_preset_key(preset: str) -> str:
    return preset.lower().strip().replace(" ", "_").replace("-", "_")


def resolve_filter_slug(preset: str) -> str:
    """Map a user/agent preset name to a built-in CapCut filter slug."""
    key = normalize_preset_key(preset)
    if key in VIDEO_FILTERS:
        return key
    if key in COLOR_PRESET_TO_FILTER:
        return COLOR_PRESET_TO_FILTER[key]

    for slug, meta in VIDEO_FILTERS.items():
        name = meta["name"].lower()
        if key == name or key in name or name in key:
            return slug

    available = ", ".join(sorted({*VIDEO_FILTERS, *COLOR_PRESET_TO_FILTER}))
    raise ValueError(
        f'Unknown color preset "{preset}". Available presets: {available}'
    )


def filter_meta(slug: str) -> dict[str, str]:
    slug = slug.lower()
    if slug not in VIDEO_FILTERS:
        raise ValueError(f"Unknown filter slug: {slug}")
    return dict(VIDEO_FILTERS[slug])
