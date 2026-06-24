"""Phase C — reflect on chapter plans / completed tasks before continuing."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from agent.runtime.model import call_model

logger = logging.getLogger(__name__)

REFLECT_TOOL = [{
    "type": "function",
    "name": "chapter_reflection",
    "description": "Summarize chapter edit quality and flag redundant tasks to skip.",
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "issues": {"type": "array", "items": {"type": "string"}},
            "skip_task_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Task ids to cancel from remaining queue (redundant/conflicting)",
            },
        },
        "required": ["summary"],
    },
}]


@dataclass
class ChapterReflection:
    summary: str
    issues: list[str]
    skip_task_ids: list[str]


def reflect_chapter(
    *,
    chapter_label: str,
    human_goal: str,
    completed_tasks: list[dict],
    remaining_tasks: list[dict],
) -> ChapterReflection | None:
    """Review a finished chapter's proposals; optionally skip bad remaining tasks."""
    if not completed_tasks:
        return None

    payload = {
        "chapter": chapter_label,
        "human_goal": human_goal[:500],
        "completed": completed_tasks[:12],
        "remaining_in_chapter": remaining_tasks[:12],
    }
    try:
        response = call_model(
            instructions=(
                "You are a reflection agent for a CapCut edit team. "
                "Review completed proposals for this chapter vs the human goal. "
                "Flag redundancy (duplicate transitions on same clip, conflicting music). "
                "Put task ids to cancel in skip_task_ids only when clearly wrong — not stylistic prefs."
            ),
            input_items=[{
                "role": "user",
                "content": json.dumps(payload, indent=2),
            }],
            tools=REFLECT_TOOL,
            temperature=0.2,
            max_output_tokens=512,
            agent="Reflection Agent",
            think=False,
        )
    except Exception as exc:
        logger.warning("Reflection failed: %s", exc)
        return None

    if response is None:
        return None

    for item in response.output:
        if item.type != "function_call" or item.name != "chapter_reflection":
            continue
        try:
            args = json.loads(item.arguments or "{}")
        except json.JSONDecodeError:
            continue
        return ChapterReflection(
            summary=str(args.get("summary") or ""),
            issues=[str(x) for x in args.get("issues") or []],
            skip_task_ids=[str(x) for x in args.get("skip_task_ids") or []],
        )
    return None


CORRECT_TASK_TOOL = [{
    "type": "function",
    "name": "correct_task_parameters",
    "description": "Correct the parameters of a failed task to resolve QA validation issues.",
    "parameters": {
        "type": "object",
        "properties": {
            "params": {
                "type": "object",
                "description": "The corrected, complete parameter dictionary for the task action.",
            },
            "explanation": {
                "type": "string",
                "description": "Short explanation of why these parameters were changed and how they resolve the issue.",
            },
        },
        "required": ["params", "explanation"],
    },
}]


def self_correct_task(
    task: any,
    issues: list[str],
    project_path: str,
    timeline_summary: dict,
) -> dict | None:
    """Use the Reflection Agent to analyze QA issues and return corrected parameters."""
    from core.slices import get_slice_for_task_type
    try:
        slice_data = get_slice_for_task_type(project_path, task.type.value)
    except Exception as exc:
        logger.warning("Could not retrieve slice data for self-correction: %s", exc)
        slice_data = {}

    payload = {
        "task_id": task.id,
        "action": task.action,
        "description": task.description,
        "instruction": task.instruction,
        "current_params": task.params,
        "validation_errors": issues,
        "timeline_slice": slice_data,
    }

    instructions = (
        "You are the CapCut Reflection and Self-Correction Agent.\n"
        "A proposed task has failed QA validation. Your goal is to analyze the validation errors "
        "and correct the task parameters using the provided timeline slice context.\n\n"
        "Common corrections:\n"
        "- Mismatched/NotFound segment_id: Look at the timeline_slice, find the correct segment_id "
        "based on the clip description/index, and replace it.\n"
        "- Out-of-range values: Adjust volume, speed, or durations to fit within acceptable ranges.\n"
        "- Duplicate or invalid queries: Adjust parameters to meet constraints.\n\n"
        "Call correct_task_parameters with the corrected params and a brief explanation."
    )

    try:
        response = call_model(
            instructions=instructions,
            input_items=[{
                "role": "user",
                "content": json.dumps(payload, indent=2),
            }],
            tools=CORRECT_TASK_TOOL,
            temperature=0.2,
            max_output_tokens=512,
            agent="Reflection Agent",
            think=False,
        )
    except Exception as exc:
        logger.warning("Self-correction LLM call failed: %s", exc)
        return None

    if response is None:
        return None

    for item in response.output:
        if item.type != "function_call" or item.name != "correct_task_parameters":
            continue
        try:
            args = json.loads(item.arguments or "{}")
            corrected_params = args.get("params")
            explanation = args.get("explanation")
            logger.info("Reflection Agent self-corrected task %s. Explanation: %s", task.id, explanation)
            return corrected_params
        except json.JSONDecodeError:
            continue

    return None

