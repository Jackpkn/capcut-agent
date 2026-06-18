"""Timeline summary helpers."""

from core.slices import timeline_summary_from_project_summary


def test_timeline_summary_from_cached_project_summary():
    summary = {
        "overview": {
            "duration_sec": 15.7,
            "video_clip_count": 2,
            "audio_clip_count": 1,
            "text_overlay_count": 0,
            "transition_count": 0,
            "effect_count": 0,
            "fps": 30,
        },
        "video_clips": [
            {"index": 1, "segment_id": "a", "name": "c1", "at_sec": 0},
            {"index": 2, "segment_id": "b", "name": "c2", "at_sec": 8},
        ],
        "audio_clips": [],
        "text_overlays": [],
    }
    compact = timeline_summary_from_project_summary(summary)
    assert compact["video_clip_count"] == 2
    assert len(compact["video_clips"]) == 2
    assert compact["video_clips"][0]["segment_id"] == "a"
