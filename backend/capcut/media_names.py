"""Small helpers for CapCut media naming conventions."""

from __future__ import annotations


def is_background_music_name(name: str | None) -> bool:
    """
    CapCut often labels camera audio tracks as VID_*.
    Treat anything else as background music.
    """
    n = (name or "").strip()
    return bool(n) and not n.upper().startswith("VID_")

