"""Routing hints for multimodal chat — not general keyword routing."""

from __future__ import annotations


def _human_text(message: str) -> str:
    """Strip vision enrichment block; keep the user's words."""
    if "## User-attached reference" in message:
        return message.split("## User-attached reference")[0].strip()
    return (message or "").strip()


def full_edit_wants_auto_team(message: str) -> bool:
    """Multi-area or full-video brief → hierarchical auto edit (team + Director)."""
    human = _human_text(message)
    m = human.lower().strip()
    if not m:
        return False

    strong = (
        "full edit", "auto edit", "pro edit", "edit my video", "edit the whole",
        "entire video", "whole video", "make this a", "turn this into",
        "travel vlog", "tiktok", "reel", "youtube short",
    )
    if any(p in m for p in strong):
        return True

    domains = (
        "music", "caption", "transition", "effect", "speed", "trim",
        "color", "grade", "sticker", "hook", "pacing",
    )
    hits = sum(1 for d in domains if d in m)
    return hits >= 2 and len(m.split()) >= 6


def attached_image_wants_answer_only(message: str, attached_count: int) -> bool:
    """
    User attached image(s) and wants to view/describe them — not apply timeline edits.
    Scoped to multimodal intent only (see AGENTS.md — orchestrator still uses LLM otherwise).
    """
    if attached_count <= 0:
        return False

    human = _human_text(message).lower()
    if not human:
        return True

    edit_signals = (
        "add ",
        "apply",
        "put ",
        "insert ",
        "match this",
        "like this",
        "same style",
        "transition",
        "caption",
        " music",
        "speed",
        "edit ",
        "change ",
        "fix ",
        "grade my",
        "color grade",
        "make it look",
        "copy this style",
        "queue ",
        "propose ",
    )
    if any(s in human for s in edit_signals):
        return False

    view_signals = (
        "analyze",
        "analysis",
        "describe",
        "what is",
        "what's in",
        "whats in",
        "see this",
        "see the",
        "look at",
        "tell me about",
        "this image",
        "the image",
        "what do you see",
        "what's this",
        "review this image",
        "attached",
    )
    if any(s in human for s in view_signals):
        return True

    if len(human.split()) <= 8:
        return True

    return False
