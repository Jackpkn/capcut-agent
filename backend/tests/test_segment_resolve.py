"""Tests for CapCut segment_id resolution (LLM alias → real UUID)."""

from capcut.segment_resolve import (
    clips_without_transition,
    normalize_pending_params,
    parse_transition_placement_hint,
    resolve_transition_target,
    resolve_video_segment_id,
)

CLIPS = [
    {
        "index": 1,
        "segment_id": "AAAA1111-1111-1111-1111-111111111111",
        "name": "intro.mp4",
        "at_sec": 0.0,
        "transition": "Fade",
    },
    {
        "index": 2,
        "segment_id": "BBBB2222-2222-2222-2222-222222222222",
        "name": "middle.mp4",
        "at_sec": 8.0,
        "transition": None,
    },
    {
        "index": 3,
        "segment_id": "CCCC3333-3333-3333-3333-333333333333",
        "name": "outro.mp4",
        "at_sec": 16.0,
        "transition": None,
    },
]


def test_resolve_exact_uuid():
    sid = CLIPS[0]["segment_id"]
    assert resolve_video_segment_id(sid, CLIPS) == sid


def test_resolve_clip_index_alias():
    assert resolve_video_segment_id("clip_2", CLIPS) == CLIPS[1]["segment_id"]
    assert resolve_video_segment_id("#1", CLIPS) == CLIPS[0]["segment_id"]


def test_parse_end_placement():
    assert parse_transition_placement_hint("add a dissolve at the end") == {"placement": "end"}


def test_parse_between_clips():
    hint = parse_transition_placement_hint("transition between clip 1 and 2")
    assert hint["placement"] == "between"
    assert hint["after_clip_index"] == 1


def test_resolve_end_targets_last_clip():
    sid = resolve_transition_target({"placement": "end"}, CLIPS)
    assert sid == CLIPS[2]["segment_id"]


def test_resolve_vague_avoids_cut_that_already_has_transition():
    """Clip 1 has Fade — vague request should target clip 2, not refuse."""
    sid = resolve_transition_target({}, CLIPS, user_message="add a transition")
    assert sid == CLIPS[1]["segment_id"]


def test_resolve_explicit_end_keeps_last_even_with_transition():
    sid = resolve_transition_target(
        {"placement": "end"},
        CLIPS,
        user_message="add dissolve at the end",
    )
    assert sid == CLIPS[2]["segment_id"]


def test_resolve_hallucinated_clip_uses_missing_not_last():
    params = normalize_pending_params(
        "add_transition",
        {"segment_id": "clip_12", "query": "fade out"},
        CLIPS,
    )
    assert params is not None
    assert params["segment_id"] == CLIPS[1]["segment_id"]
    assert params["clip_index"] == 2


def test_normalize_speed_drops_invalid_segment():
    assert normalize_pending_params(
        "update_clip_speed",
        {"segment_id": "clip_99", "speed": 1.5},
        CLIPS,
    ) is None


def test_clips_without_transition():
    missing = clips_without_transition(CLIPS)
    assert len(missing) == 2
    assert missing[0]["index"] == 2
