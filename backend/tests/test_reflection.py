"""Tests for Phase C Reflection & Self-Correction Agent."""

import pytest
import copy
import json
from core.models import Task, TaskType
from agent.reflection_agent import self_correct_task
from agent.qa_agent import review_task


def test_self_correct_task_success(monkeypatch):
    class MockOutputItem:
        def __init__(self, name, arguments):
            self.type = "function_call"
            self.name = name
            self.arguments = arguments

    class MockResponse:
        def __init__(self, output):
            self.output = output

    def mock_call_model(*args, **kwargs):
        # The model should call correct_task_parameters with corrected params
        arguments = json.dumps({
            "params": {
                "segment_id": "video_seg_valid",
                "speed": 2.0
            },
            "explanation": "Updated segment_id to video_seg_valid which exists on the timeline"
        })
        return MockResponse([MockOutputItem("correct_task_parameters", arguments)])

    monkeypatch.setattr("agent.reflection_agent.call_model", mock_call_model)

    # Mock project data containing the valid segment
    mock_project_data = {
        "tracks": [
            {
                "id": "track_1",
                "type": "video",
                "segments": [
                    {
                        "id": "video_seg_valid",
                        "target_timerange": {"start": 0, "duration": 4_500_000},
                        "source_timerange": {"start": 0, "duration": 4_500_000},
                        "speed": 1.0,
                    }
                ]
            }
        ],
        "materials": {
            "videos": []
        }
    }

    monkeypatch.setattr("capcut.reader.read_project", lambda path: mock_project_data)
    monkeypatch.setattr("core.slices.read_project", lambda path: mock_project_data)

    task = Task(
        id="task_1",
        description="Speed up travel clip",
        instruction="Set speed to 2x for clip 1",
        action="update_clip_speed",
        params={"segment_id": "invalid_id", "speed": 2.0},
        type=TaskType.VIDEO,
    )

    # Run review_task first to see that it fails
    qa_before = review_task(task, "/fake/project/path")
    assert not qa_before["approved"]
    assert any("not found in video slice" in issue for issue in qa_before["issues"])

    # Run self-correction
    corrected = self_correct_task(task, qa_before["issues"], "/fake/project/path", {})
    assert corrected is not None
    assert corrected["segment_id"] == "video_seg_valid"
    assert corrected["speed"] == 2.0

    # Apply correction and check that QA now passes
    task.params = corrected
    qa_after = review_task(task, "/fake/project/path")
    assert qa_after["approved"]
    assert len(qa_after["issues"]) == 0
