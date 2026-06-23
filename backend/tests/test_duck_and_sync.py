"""Tests for advanced audio ducking and pacing sync."""

import pytest
import copy

from capcut.writer import duck_audio, sync_video_to_beats


def test_duck_audio_dynamic_splitting(monkeypatch):
    # Mock project draft info
    mock_data = {
        "tracks": [
            {
                "id": "music_track_id",
                "type": "audio",
                "segments": [
                    {
                        "id": "music_seg_1",
                        "target_timerange": {"start": 0, "duration": 20_000_000}, # 0 to 20s
                        "source_timerange": {"start": 0, "duration": 20_000_000},
                        "speed": 1.0,
                        "volume": 1.0
                    }
                ]
            },
            {
                "id": "text_track_id",
                "type": "text",
                "segments": [
                    {
                        "id": "caption_1",
                        "target_timerange": {"start": 2_000_000, "duration": 3_000_000}, # 2s to 5s
                    },
                    {
                        "id": "caption_2",
                        "target_timerange": {"start": 5_500_000, "duration": 2_500_000}, # 5.5s to 8s (should merge with 2-5 because gap is 0.5s <= 1.0s)
                    },
                    {
                        "id": "caption_3",
                        "target_timerange": {"start": 12_000_000, "duration": 3_000_000}, # 12s to 15s
                    }
                ]
            }
        ]
    }

    saved_data = {}

    def mock_read(path):
        return copy.deepcopy(mock_data)

    def mock_write(path, data):
        nonlocal saved_data
        saved_data = data
        return True

    monkeypatch.setattr("capcut.writer.read_project", mock_read)
    monkeypatch.setattr("capcut.writer.write_project", mock_write)

    res = duck_audio("/fake/project/path", volume=0.15)
    
    assert res["ducked_segments"] > 0
    
    # Check if music segments are split and volumed correctly
    segments = saved_data["tracks"][0]["segments"]
    
    # Merged intervals should be:
    # 1. 2.0s to 8.0s (merged caption_1 and caption_2)
    # 2. 12.0s to 15.0s (caption_3)
    # So split times should be: 2.0, 8.0, 12.0, 15.0.
    # Therefore, music segment [0, 20] gets split at 2.0, 8.0, 12.0, 15.0:
    # Segments:
    # - [0, 2.0]: volume = 1.0
    # - [2.0, 8.0]: volume = 0.15 (ducked)
    # - [8.0, 12.0]: volume = 1.0
    # - [12.0, 15.0]: volume = 0.15 (ducked)
    # - [15.0, 20.0]: volume = 1.0
    
    assert len(segments) == 5
    
    # Segment 1: 0 to 2s
    assert segments[0]["target_timerange"]["start"] == 0
    assert segments[0]["target_timerange"]["duration"] == 2_000_000
    assert segments[0]["volume"] == 1.0

    # Segment 2: 2s to 8s
    assert segments[1]["target_timerange"]["start"] == 2_000_000
    assert segments[1]["target_timerange"]["duration"] == 6_000_000
    assert segments[1]["volume"] == 0.15

    # Segment 3: 8s to 12s
    assert segments[2]["target_timerange"]["start"] == 8_000_000
    assert segments[2]["target_timerange"]["duration"] == 4_000_000
    assert segments[2]["volume"] == 1.0

    # Segment 4: 12s to 15s
    assert segments[3]["target_timerange"]["start"] == 12_000_000
    assert segments[3]["target_timerange"]["duration"] == 3_000_000
    assert segments[3]["volume"] == 0.15

    # Segment 5: 15s to 20s
    assert segments[4]["target_timerange"]["start"] == 15_000_000
    assert segments[4]["target_timerange"]["duration"] == 5_000_000
    assert segments[4]["volume"] == 1.0


def test_sync_video_to_beats(monkeypatch):
    # Mock project draft info
    mock_data = {
        "tracks": [
            {
                "id": "video_track_id",
                "type": "video",
                "segments": [
                    {
                        "id": "video_seg_1",
                        "target_timerange": {"start": 0, "duration": 1_800_000}, # 1.8s
                        "source_timerange": {"start": 0, "duration": 1_800_000},
                        "speed": 1.0,
                    },
                    {
                        "id": "video_seg_2",
                        "target_timerange": {"start": 1_800_000, "duration": 2_400_000}, # ends at 4.2s
                        "source_timerange": {"start": 0, "duration": 2_400_000},
                        "speed": 1.0,
                    }
                ]
            }
        ]
    }

    saved_data = {}

    def mock_read(path):
        return copy.deepcopy(mock_data)

    def mock_write(path, data):
        nonlocal saved_data
        saved_data = data
        return True

    monkeypatch.setattr("capcut.writer.read_project", mock_read)
    monkeypatch.setattr("capcut.writer.write_project", mock_write)

    # Use bpm = 60.0 -> beat_interval = 1.0s
    res = sync_video_to_beats("/fake/project/path", bpm=60.0)
    
    assert res["aligned_clips"] == 2
    assert res["beat_interval"] == 1.0
    
    segments = saved_data["tracks"][0]["segments"]
    
    # Clip 1 starts at 0, original end is 1.8s. Nearest beat is 2.0s.
    # So new end is 2.0s, new duration is 2.0s.
    assert segments[0]["target_timerange"]["start"] == 0
    assert segments[0]["target_timerange"]["duration"] == 2_000_000
    
    # Clip 2 starts at 2.0s, original end is 4.2s. Nearest beat is 4.0s.
    # So new end is 4.0s, new duration is 4.0 - 2.0 = 2.0s.
    assert segments[1]["target_timerange"]["start"] == 2_000_000
    assert segments[1]["target_timerange"]["duration"] == 2_000_000


def test_detect_audio_peaks_mocked(monkeypatch):
    import subprocess
    from capcut.writer import detect_audio_peaks

    class MockCompletedProcess:
        def __init__(self, stdout, returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    # Create 100 samples (1 second at 100fps)
    # Put a peak of amplitude 120 at index 50 (0.5s), elsewhere amplitude 10
    mock_samples = bytearray([10] * 100)
    mock_samples[50] = 120

    def mock_run(cmd, capture_output=True, timeout=10):
        return MockCompletedProcess(bytes(mock_samples))

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr("pathlib.Path.exists", lambda self: True)

    peaks = detect_audio_peaks("/fake/audio.mp3")
    assert len(peaks) > 0
    # The peak should be around 0.5s
    assert abs(peaks[0] - 0.5) < 0.15


def test_sync_video_to_beats_with_audio_peaks(monkeypatch):
    # Mock project draft info with a video track and a music audio clip
    mock_data = {
        "tracks": [
            {
                "id": "video_track_id",
                "type": "video",
                "segments": [
                    {
                        "id": "video_seg_1",
                        "target_timerange": {"start": 0, "duration": 1_800_000}, # 1.8s
                        "source_timerange": {"start": 0, "duration": 1_800_000},
                        "speed": 1.0,
                    }
                ]
            },
            {
                "id": "music_track_id",
                "type": "audio",
                "segments": [
                    {
                        "id": "music_seg",
                        "material_id": "music_material",
                        "target_timerange": {"start": 0, "duration": 20_000_000},
                    }
                ]
            }
        ],
        "materials": {
            "audios": [
                {
                    "id": "music_material",
                    "path": "/fake/music.mp3"
                }
            ]
        }
    }

    saved_data = {}

    def mock_read(path):
        return copy.deepcopy(mock_data)

    def mock_write(path, data):
        nonlocal saved_data
        saved_data = data
        return True

    monkeypatch.setattr("capcut.writer.read_project", mock_read)
    monkeypatch.setattr("capcut.writer.write_project", mock_write)
    monkeypatch.setattr("pathlib.Path.exists", lambda self: True)
    # Mock peak detection to return a peak at exactly 2.5s
    monkeypatch.setattr("capcut.writer.detect_audio_peaks", lambda path: [2.5])

    res = sync_video_to_beats("/fake/project/path")
    assert res["used_audio_peaks"] is True
    assert res["aligned_clips"] == 1

    segments = saved_data["tracks"][0]["segments"]
    # Video clip 1 should align to the peak at 2.5s
    assert segments[0]["target_timerange"]["duration"] == 2_500_000


def test_smart_fx_selection_with_preset_mood(monkeypatch):
    from capcut.writer import _resolve_asset
    from core.session_memory import SessionMemory

    # Mock session memory with cinematic preset
    mock_memory = SessionMemory(preset_id="cinematic")
    monkeypatch.setattr("capcut.writer.get_session_memory_for_project", lambda p: mock_memory)

    # Mock get_director_picks to return cinematic/calm transitions
    mock_picks = {
        "transitions": [
            {"resource_id": "cinematic_transition_id", "name": "Cinematic Fade", "type": "transition", "cached": True}
        ]
    }
    monkeypatch.setattr("capcut.catalog.get_director_picks", lambda m: mock_picks)
    monkeypatch.setattr("capcut.writer.asset_exists_on_disk", lambda a: True)

    params = {"query": "transition"}
    asset = _resolve_asset(params, "transition", "/fake/project/path")
    assert asset["resource_id"] == "cinematic_transition_id"
    assert asset["name"] == "Cinematic Fade"


def test_multimodal_subtitle_style_matching(monkeypatch):
    import json
    from agent.actions import _build_text_content
    from core.session_memory import SessionMemory

    # Mock session memory with custom caption formatting requirements
    mock_memory = SessionMemory(
        caption_direction="make yellow subtitles",
        style_brief="large font spacing"
    )
    monkeypatch.setattr("capcut.writer.get_session_memory_for_project", lambda p: mock_memory)

    text_json = _build_text_content("Hello World", project_path="/fake/project/path")
    data = json.loads(text_json)

    assert data["text"] == "Hello World"
    style = data["styles"][0]
    # Color should be yellow [1.0, 1.0, 0.0]
    assert style["fill"]["content"]["solid"]["color"] == [1.0, 1.0, 0.0]
    # Size should be large (24)
    assert style["size"] == 24

