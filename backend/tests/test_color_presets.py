"""Tests for colour filter presets (not VFX scene effects)."""

import copy

import pytest

from capcut.filters import resolve_filter_slug
from capcut.writer import add_filter, apply_color_preset


def test_resolve_filter_slug_mappings():
    assert resolve_filter_slug("cinematic") == "dramatic"
    assert resolve_filter_slug("warm") == "warm"
    assert resolve_filter_slug("teal_orange") == "contrast"
    assert resolve_filter_slug("dramatic") == "dramatic"


def test_resolve_filter_slug_unknown():
    with pytest.raises(ValueError, match="Unknown color preset"):
        resolve_filter_slug("neon_rainbow_party")


def test_apply_color_preset_uses_filter_track(monkeypatch):
    mock_data = {
        "duration": 25_000_000,
        "tracks": [
            {
                "id": "video_track",
                "type": "video",
                "segments": [
                    {
                        "id": "clip_1",
                        "target_timerange": {"start": 0, "duration": 25_000_000},
                    }
                ],
            },
            {
                "id": "old_filter_track",
                "type": "filter",
                "name": "filter",
                "segments": [
                    {
                        "id": "old_seg",
                        "material_id": "old_filter_mat",
                        "target_timerange": {"start": 0, "duration": 25_000_000},
                    }
                ],
            },
        ],
        "materials": {
            "video_effects": [
                {
                    "id": "old_filter_mat",
                    "name": "Warm",
                    "type": "filter",
                    "resource_id": "7028463716732079118",
                    "effect_id": "7028463716732079118",
                },
                {
                    "id": "countdown_fx",
                    "name": "Classic Countdown 2",
                    "type": "video_effect",
                    "resource_id": "7590232066420116789",
                    "effect_id": "7590232066420116789",
                },
            ]
        },
    }

    saved_data = {}

    def mock_read(path):
        return copy.deepcopy(mock_data)

    def mock_write(path, data):
        nonlocal saved_data
        saved_data = data
        return True

    def mock_summary(path):
        return {"overview": {"duration_sec": 25.0}}

    def mock_resolve(preset, project_path):
        return {
            "slug": "dramatic",
            "resource_id": "7028463716732079125",
            "effect_id": "7028463716732079125",
            "name": "Dramatic",
            "type": "filter",
            "category_name": "Filter",
            "path": "",
            "cached": False,
        }

    monkeypatch.setattr("capcut.writer.read_project", mock_read)
    monkeypatch.setattr("capcut.writer.write_project", mock_write)
    monkeypatch.setattr("capcut.writer._resolve_filter_asset", mock_resolve)
    monkeypatch.setattr("capcut.reader.get_project_summary", mock_summary)

    result = apply_color_preset("/fake/project", preset="cinematic")

    assert result["name"] == "Dramatic"
    assert result["slug"] == "dramatic"

    filters = [e for e in saved_data["materials"]["video_effects"] if e.get("type") == "filter"]
    effects = [e for e in saved_data["materials"]["video_effects"] if e.get("type") != "filter"]

    assert len(filters) == 1
    assert filters[0]["name"] == "Dramatic"
    assert filters[0]["resource_id"] == "7028463716732079125"
    assert effects[0]["name"] == "Classic Countdown 2"

    filter_track = next(t for t in saved_data["tracks"] if t.get("type") == "filter")
    assert len(filter_track["segments"]) == 1
    assert filter_track["segments"][0]["target_timerange"]["duration"] == 25_000_000


def test_add_filter_does_not_call_add_effect(monkeypatch):
    mock_data = {"tracks": [], "materials": {"video_effects": []}}
    saved_data = {}

    monkeypatch.setattr("capcut.writer.read_project", lambda path: copy.deepcopy(mock_data))
    monkeypatch.setattr(
        "capcut.writer.write_project",
        lambda path, data: saved_data.update({"data": data}) or True,
    )
    monkeypatch.setattr(
        "capcut.reader.get_project_summary",
        lambda path: {"overview": {"duration_sec": 10.0}},
    )
    monkeypatch.setattr(
        "capcut.writer._resolve_filter_asset",
        lambda preset, project_path: {
            "slug": "warm",
            "resource_id": "7028463716732079118",
            "effect_id": "7028463716732079118",
            "name": "Warm",
            "type": "filter",
            "category_name": "Filter",
            "path": "",
            "cached": False,
        },
    )

    called = {"add_effect": False}

    def fake_add_effect(*args, **kwargs):
        called["add_effect"] = True

    monkeypatch.setattr("capcut.writer.add_effect", fake_add_effect)

    add_filter("/fake/project", preset="warm")

    assert called["add_effect"] is False
    assert saved_data["data"]["materials"]["video_effects"][0]["type"] == "filter"
