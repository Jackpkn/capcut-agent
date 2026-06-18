"""Tests for CapCut segment_id resolution (LLM alias → real UUID)."""

from capcut.segment_resolve import (
    normalize_pending_params,
    resolve_video_segment_id,
)

CLIPS = [
    {
        "index": 1,
        "segment_id": "AAAA1111-1111-1111-1111-111111111111",
        "name": "intro.mp4",
        "at_sec": 0.0,
    },
    {
        "index": 2,
        "segment_id": "BBBB2222-2222-2222-2222-222222222222",
        "name": "outro.mp4",
        "at_sec": 8.0,
    },
]


def test_resolve_exact_uuid():
    sid = CLIPS[0]["segment_id"]
    assert resolve_video_segment_id(sid, CLIPS) == sid


def test_resolve_clip_index_alias():
    assert resolve_video_segment_id("clip_2", CLIPS) == CLIPS[1]["segment_id"]
    assert resolve_video_segment_id("#1", CLIPS) == CLIPS[0]["segment_id"]


def test_resolve_hallucinated_clip_uses_none():
    assert resolve_video_segment_id("clip_12", CLIPS) is None


def test_normalize_transition_falls_back_to_last_video_clip():
    params = normalize_pending_params(
        "add_transition",
        {"segment_id": "clip_12", "query": "fade out"},
        CLIPS,
    )
    assert params is not None
    assert params["segment_id"] == CLIPS[1]["segment_id"]
    assert params["clip_index"] == 2
    assert params["clip_name"] == "outro.mp4"


def test_normalize_speed_drops_invalid_segment():
    assert normalize_pending_params(
        "update_clip_speed",
        {"segment_id": "clip_99", "speed": 1.2},
        CLIPS,
    ) is None
