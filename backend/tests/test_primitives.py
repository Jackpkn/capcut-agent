"""Tests for Layer 3 primitives."""

import copy

import pytest

from capcut.primitives import add_keyframes, set_canvas, set_clip_transform


def test_set_clip_transform(monkeypatch):
    mock_data = {
        "tracks": [
            {
                "type": "video",
                "segments": [
                    {
                        "id": "SEG-1",
                        "clip": {"scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0, "y": 0}},
                    }
                ],
            }
        ],
        "canvas_config": {},
    }
    saved = {}

    monkeypatch.setattr("capcut.primitives.read_project", lambda p: copy.deepcopy(mock_data))
    monkeypatch.setattr(
        "capcut.primitives.write_project",
        lambda p, d: saved.update({"data": d}),
    )

    set_clip_transform("/fake", "SEG-1", scale=1.5, position_x=0.1, alpha=0.9)
    seg = saved["data"]["tracks"][0]["segments"][0]
    assert seg["clip"]["scale"]["x"] == 1.5
    assert seg["clip"]["transform"]["x"] == 0.1
    assert seg["clip"]["alpha"] == 0.9


def test_add_keyframes(monkeypatch):
    mock_data = {
        "tracks": [{"type": "video", "segments": [{"id": "SEG-1", "common_keyframes": []}]}],
    }
    saved = {}

    monkeypatch.setattr("capcut.primitives.read_project", lambda p: copy.deepcopy(mock_data))
    monkeypatch.setattr(
        "capcut.primitives.write_project",
        lambda p, d: saved.update({"data": d}),
    )

    add_keyframes(
        "/fake",
        "SEG-1",
        "scale_x",
        [{"time_sec": 0.0, "value": 1.0}, {"time_sec": 2.0, "value": 1.2}],
    )
    tracks = saved["data"]["tracks"][0]["segments"][0]["common_keyframes"]
    assert len(tracks) == 1
    assert tracks[0]["property_type"] == "KFTypeScaleX"
    assert len(tracks[0]["keyframe_list"]) == 2


def test_set_canvas(monkeypatch):
    mock_data = {"tracks": [], "canvas_config": {"width": 1080, "height": 1920}}
    saved = {}

    monkeypatch.setattr("capcut.primitives.read_project", lambda p: copy.deepcopy(mock_data))
    monkeypatch.setattr(
        "capcut.primitives.write_project",
        lambda p, d: saved.update({"data": d}),
    )

    set_canvas("/fake", width=1920, height=1080, ratio="16:9")
    assert saved["data"]["canvas_config"]["ratio"] == "16:9"
