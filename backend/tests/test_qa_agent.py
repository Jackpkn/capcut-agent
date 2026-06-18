"""Tests for pre-approve QA on pending actions."""

from agent.qa_agent import review_pending_actions

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

SUMMARY = {"video_clips": CLIPS}


def _fake_slice(project_path: str, domain: str) -> dict:
    if domain == "video":
        return {"clips": CLIPS}
    if domain == "text":
        return {"overlays": [], "caption_clips": CLIPS}
    return {"clips": []}


def test_review_pending_normalizes_transition(monkeypatch):
    monkeypatch.setattr("agent.qa_agent.get_slice_for_task_type", _fake_slice)

    approved, blocked, reviews = review_pending_actions(
        [{
            "action": "add_transition",
            "params": {"segment_id": "clip_12", "query": "fade"},
            "description": "Fade at end",
        }],
        "/fake/path",
        project_summary=SUMMARY,
    )

    assert len(approved) == 1
    assert len(blocked) == 0
    assert approved[0]["params"]["segment_id"] == CLIPS[1]["segment_id"]
    assert reviews[0]["approved"] is True


def test_review_pending_blocks_invalid_speed(monkeypatch):
    monkeypatch.setattr("agent.qa_agent.get_slice_for_task_type", _fake_slice)

    approved, blocked, reviews = review_pending_actions(
        [{
            "action": "update_clip_speed",
            "params": {"segment_id": "clip_99", "speed": 1.2},
            "description": "Speed up clip",
        }],
        "/fake/path",
        project_summary=SUMMARY,
    )

    assert len(approved) == 0
    assert len(blocked) == 1
    assert reviews[0]["approved"] is False
    assert blocked[0]["qa_issues"]
