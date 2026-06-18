"""Tests for Phase B task dependency ordering."""

from core.models import Task, TaskType
from core.task_deps import order_action_dicts, order_tasks


def _task(action: str, tid: str) -> Task:
    return Task(
        id=tid,
        type=TaskType.AUDIO if "music" in action else TaskType.TEXT,
        instruction="",
        action=action,
        params={},
        description=action,
    )


def test_captions_run_after_music():
    tasks = [
        _task("generate_captions", "c1"),
        _task("replace_music", "m1"),
    ]
    ordered = order_tasks(tasks)
    assert [t.id for t in ordered] == ["m1", "c1"]
    assert ordered[1].depends_on == ["m1"]


def test_transitions_run_after_pacing_and_music():
    tasks = [
        _task("add_transition", "t1"),
        _task("update_clip_speed", "v1"),
        _task("add_music", "m1"),
    ]
    ordered = order_tasks(tasks)
    assert ordered[0].id == "v1"
    assert ordered[1].id == "m1"
    assert ordered[2].id == "t1"
    assert "v1" in ordered[2].depends_on
    assert "m1" in ordered[2].depends_on


def test_order_action_dicts():
    actions = [
        {"action": "generate_captions", "params": {}, "description": "captions"},
        {"action": "replace_music", "params": {}, "description": "music"},
    ]
    ordered = order_action_dicts(actions)
    assert ordered[0]["action"] == "replace_music"
    assert ordered[1]["action"] == "generate_captions"
