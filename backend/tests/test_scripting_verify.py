"""Tests for Layer 3 scripting sandbox and Layer 1 verify."""

import copy

import pytest

from capcut.scripting import ScriptSecurityError, execute_capcut_script
from capcut.verify import verify_project


def test_script_blocks_import_os():
    with pytest.raises(ScriptSecurityError):
        execute_capcut_script("/fake", "import os\nresult=1")


def test_script_runs_primitives(monkeypatch):
    calls = []

    def mock_zoom(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ok": True}

    import capcut.scripting as scripting

    real_ns = scripting.build_script_namespace

    def mock_ns(path):
        ns = real_ns(path)
        ns["primitives"].zoom_pulse = mock_zoom
        return ns

    monkeypatch.setattr(scripting, "build_script_namespace", mock_ns)

    out = execute_capcut_script(
        "/fake/project",
        'result = primitives.zoom_pulse(project_path, "SEG-1", peak_scale=1.2)',
    )
    assert out["ok"] is True
    assert calls


def test_verify_project_duration(monkeypatch):
    summary = {
        "overview": {
            "duration_sec": 25.0,
            "video_clip_count": 5,
            "audio_clip_count": 1,
            "text_overlay_count": 2,
        },
        "filters": [{"name": "Dramatic"}],
        "effects": [],
    }

    monkeypatch.setattr("capcut.verify.get_project_summary", lambda path: summary)

    report = verify_project(
        "/fake",
        {"duration_sec": 25.0, "filter_name": "dramatic", "min_video_clips": 3},
    )
    assert report["passed"] is True
    assert len(report["checks"]) == 3


def test_verify_project_fails(monkeypatch):
    summary = {
        "overview": {"duration_sec": 10.0, "video_clip_count": 1},
        "filters": [],
        "effects": [],
    }
    monkeypatch.setattr("capcut.verify.get_project_summary", lambda path: summary)

    report = verify_project("/fake", {"duration_sec": 25.0})
    assert report["passed"] is False
