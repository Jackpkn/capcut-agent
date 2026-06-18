"""Tests for episodic memory store."""

import sqlite3

from core import episodic_memory as em


def test_record_and_load_preferences(tmp_path, monkeypatch):
    db_path = tmp_path / "episodic.db"
    monkeypatch.setattr(em, "_DB_PATH", db_path)
    monkeypatch.setattr(em, "_DB_DIR", tmp_path)

    em.record_approval(
        "/projects/test",
        [{"action": "add_transition", "params": {"query": "fade out"}, "description": "fade"}],
    )
    em.record_rejection(
        "/projects/test",
        [{"action": "add_music", "params": {"query": "lofi"}, "description": "music"}],
        reason="too loud",
    )

    prefs = em.load_user_preferences()
    assert "fade out" in prefs["preferred_transitions"]
    assert any(r.get("reason") == "too loud" for r in prefs["rejects"])

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM edit_events").fetchone()[0]
    assert count == 2
