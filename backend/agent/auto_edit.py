"""One-click pro auto-edit — Director → all chapters → single approve."""

from __future__ import annotations

AUTO_EDIT_CORE = """Professional full-project auto-edit. Deliver a publish-ready cut like an experienced editor:

- Tighten pacing across ALL chapters — trim dead air, keep rhythm engaging
- Transitions at natural cuts (taste over quantity — not every join)
- Background music that matches mood and platform; replace weak or missing beds
- Designed captions where they add value (hooks, locations, punch lines)
- Effects only when they improve cohesion — do not over-process
- Prefer propose_draft_operations for batch timeline changes per chapter when efficient
- Respect strong existing moments — enhance personality, do not flatten it

Run the full hierarchical workflow: Director maps chapters → scene planner per chapter → specialists → one human approve at the end."""


def build_auto_edit_message(human_hint: str = "") -> str:
    """Combine the pro auto-edit brief with an optional vibe or platform hint."""
    hint = (human_hint or "").strip()
    if not hint:
        return AUTO_EDIT_CORE
    return f"{AUTO_EDIT_CORE}\n\n## Human direction\n{hint}"


def display_label(human_hint: str = "") -> str:
    hint = (human_hint or "").strip()
    if hint:
        return f"Auto edit — {hint[:72]}{'…' if len(hint) > 72 else ''}"
    return "Auto edit — pro full timeline"
