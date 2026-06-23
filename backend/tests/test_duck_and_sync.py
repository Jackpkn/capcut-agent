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
