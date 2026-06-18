"""Phase E — per-user edit taste across sessions (SQLite)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

_DB_DIR = Path(__file__).resolve().parent.parent / "data"
_DB_PATH = _DB_DIR / "episodic.db"


def _conn() -> sqlite3.Connection:
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS edit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            project_path TEXT,
            event_type TEXT NOT NULL,
            actions_json TEXT,
            reason TEXT,
            created_at REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _record(
    user_id: str,
    project_path: str | None,
    event_type: str,
    actions: list[dict],
    *,
    reason: str | None = None,
) -> None:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO edit_events
                (user_id, project_path, event_type, actions_json, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, project_path, event_type, json.dumps(actions), reason, time.time()),
        )
        conn.commit()


def record_approval(
    project_path: str,
    actions: list[dict],
    user_id: str = "default",
) -> None:
    _record(user_id, project_path, "approved", actions)


def record_rejection(
    project_path: str | None,
    actions: list[dict] | None,
    reason: str | None = None,
    user_id: str = "default",
) -> None:
    _record(user_id, project_path, "rejected", actions or [], reason=reason)


def load_user_preferences(user_id: str = "default") -> dict:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT event_type, actions_json, reason
            FROM edit_events
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (user_id,),
        ).fetchall()

    rejects: list[dict] = []
    transitions: list[str] = []
    music: list[str] = []
    rejected_actions: list[str] = []
    avoid_notes: list[str] = []

    for event_type, actions_json, reason in rows:
        actions = json.loads(actions_json or "[]")
        if event_type == "rejected":
            rejects.append({"reason": reason or "", "actions": actions[:3]})
            if reason:
                avoid_notes.append(reason)
            for action in actions:
                name = action.get("action")
                if name and name not in rejected_actions:
                    rejected_actions.append(name)
        elif event_type == "approved":
            for action in actions:
                act = action.get("action") or ""
                params = action.get("params") or {}
                if act == "add_transition":
                    name = params.get("query") or params.get("name") or params.get("transition")
                    if name and name not in transitions:
                        transitions.append(str(name))
                if act in ("add_music", "replace_music"):
                    mname = params.get("query") or params.get("name")
                    if mname and mname not in music:
                        music.append(str(mname))

    return {
        "preferred_transitions": transitions[:5],
        "preferred_music": music[:5],
        "preferred_speed": None,
        "rejects": rejects[:8],
        "rejected_actions": rejected_actions[:8],
        "avoid_notes": avoid_notes[:5],
    }


def director_taste_block(user_id: str = "default") -> str:
    """Short markdown block for Director strategic context."""
    prefs = load_user_preferences(user_id)
    lines: list[str] = []
    if prefs.get("preferred_transitions"):
        lines.append(
            "- Preferred transitions: "
            + ", ".join(f"*{t}*" for t in prefs["preferred_transitions"])
        )
    if prefs.get("preferred_music"):
        lines.append(
            "- Preferred music beds: "
            + ", ".join(f"*{m}*" for m in prefs["preferred_music"])
        )
    if prefs.get("avoid_notes"):
        lines.append("- Recent reject reasons: " + "; ".join(prefs["avoid_notes"][:3]))
    if prefs.get("rejected_actions"):
        lines.append(
            "- Often rejected action types: "
            + ", ".join(prefs["rejected_actions"][:5])
        )
    if not lines:
        return ""
    return "## User taste (from past sessions)\n" + "\n".join(lines)
