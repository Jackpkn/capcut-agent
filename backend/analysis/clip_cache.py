"""SQLite cache for per-clip understanding (System 1)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path.home() / ".capcut-agent" / "clip_intelligence.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clip_understanding (
            project_path TEXT NOT NULL,
            segment_id TEXT NOT NULL,
            source_path TEXT,
            source_mtime REAL,
            data_json TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (project_path, segment_id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_clip_project
        ON clip_understanding (project_path)
    """)
    conn.commit()
    return conn


def get_cached_clip(
    project_path: str,
    segment_id: str,
    *,
    source_path: str = "",
    source_mtime: float | None = None,
) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT data_json, source_path, source_mtime FROM clip_understanding "
            "WHERE project_path = ? AND segment_id = ?",
            (project_path, segment_id),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    if source_path and row[1] == source_path and source_mtime is not None:
        if abs(float(row[2] or 0) - source_mtime) > 0.5:
            return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def set_cached_clip(project_path: str, segment_id: str, data: dict) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO clip_understanding "
            "(project_path, segment_id, source_path, source_mtime, data_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                project_path,
                segment_id,
                data.get("source_path", ""),
                float(data.get("source_mtime") or 0),
                json.dumps(data),
                time.time(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_project_clips(project_path: str) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT data_json FROM clip_understanding WHERE project_path = ? ORDER BY updated_at",
            (project_path,),
        ).fetchall()
    finally:
        conn.close()
    out: list[dict] = []
    for (raw,) in rows:
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return sorted(out, key=lambda c: c.get("index", 0))


def clear_project(project_path: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM clip_understanding WHERE project_path = ?",
            (project_path,),
        )
        conn.commit()
    finally:
        conn.close()
