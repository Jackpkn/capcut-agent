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
