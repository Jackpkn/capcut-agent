"""Tests for shortcuts and edit pipeline."""

import pytest

from capcut.shortcuts import CAPCUT_SHORTCUTS, list_shortcuts, run_shortcut


def test_list_shortcuts():
    items = list_shortcuts()
    assert len(items) == len(CAPCUT_SHORTCUTS)
    assert any(i["name"] == "save" for i in items)


def test_run_shortcut_unknown():
    out = run_shortcut("not_a_real_key")
    assert out["success"] is False
    assert "known" in out


def test_run_edit_pipeline_monkeypatch(monkeypatch):
    from capcut import pipeline

    calls: list[str] = []

    def fake_execute(action, params, path):
        calls.append(action)
        return f"ok:{action}"

    monkeypatch.setattr("agent.actions.execute_action", fake_execute)
    monkeypatch.setattr("capcut.cdp.sync_capcut", lambda p: {"connected": True, "reloaded": 1})
    monkeypatch.setattr("capcut.shortcuts.run_shortcut", lambda name, **kw: {"success": True, "shortcut": name})
    monkeypatch.setattr(
        "capcut.reader.get_project_summary",
        lambda p: {"overview": {"duration_sec": 10, "video_clip_count": 2, "text_overlay_count": 5}},
    )
    monkeypatch.setattr(
        "capcut.verify.verify_project",
        lambda p, e: {"passed": True, "checks": []},
    )

    result = pipeline.run_edit_pipeline("/fake", sync_beats=False)
    assert "generate_captions" in calls
    assert "duck_audio" in calls
    assert "fade_project_music" in calls
    assert "apply_color_preset" in calls
    assert result["success"] is True


def test_bootstrap_and_edit(monkeypatch):
    from capcut import ingest, pipeline

    monkeypatch.setattr(
        ingest,
        "create_project_from_media",
        lambda paths, **kw: {"project_path": "/fake/new", "project_name": "x"},
    )
    monkeypatch.setattr(
        pipeline,
        "run_edit_pipeline",
        lambda path, **kw: {"success": True, "steps": []},
    )
    out = pipeline.bootstrap_and_edit(["/a.mp4"])
    assert out["project_path"] == "/fake/new"
    assert out["pipeline"]["success"] is True
