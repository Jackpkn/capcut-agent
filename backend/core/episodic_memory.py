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
    for event_type, actions_json, reason in rows:
        actions = json.loads(actions_json or "[]")
        if event_type == "rejected":
            rejects.append({"reason": reason or "", "actions": actions[:3]})
        elif event_type == "approved":
            for action in actions:
                if action.get("action") != "add_transition":
                    continue
                params = action.get("params") or {}
                name = params.get("query") or params.get("name") or params.get("transition")
                if name and name not in transitions:
                    transitions.append(str(name))

    return {
        "preferred_transitions": transitions[:5],
        "preferred_speed": None,
        "rejects": rejects[:8],
    }
