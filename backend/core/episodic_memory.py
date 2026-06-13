"""Phase E — per-user taste across sessions (stub)."""

from __future__ import annotations

# TODO: SQLite store for preferred_transitions, rejects, approved_patterns.
# Inject into Director strategic context on session start.


def load_user_preferences(user_id: str = "default") -> dict:
    return {
        "preferred_transitions": [],
        "preferred_speed": None,
        "rejects": [],
    }
