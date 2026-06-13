"""LLM Director — strategic layer: chapters + goals, no segment IDs."""

from __future__ import annotations

import json
import logging

from agent.agents.definitions import director_config
from agent import brain as brain_module
from agent.director import EditBrief, build_edit_brief, detect_preset
from agent.runtime.loop import run_agent
from agent.runtime.model import llm_available
from agent.strategic_context import build_strategic_context
from agent.streaming import EventEmitter
from agent.team_director import DirectorResult
from core.chapters import chapters_from_director_payload, default_chapters_from_timeline
from core.models import Goal, TaskType, new_id
from core.session_memory import SessionMemory

logger = logging.getLogger(__name__)

_TASK_TYPE_MAP = {
    "video": TaskType.VIDEO,
    "audio": TaskType.AUDIO,
    "text": TaskType.TEXT,
    "effects": TaskType.EFFECTS,
}


def run_llm_director(
    user_message: str,
    timeline_summary: dict,
    project_path: str,
    emit: EventEmitter | None = None,
) -> DirectorResult | None:
    if not llm_available():
        return None

    strategic = build_strategic_context(timeline_summary, brain_module.analysis_context)
    context = (
        f"HUMAN REQUEST:\n{user_message}\n\n"
        f"STRATEGIC PROJECT VIEW (no segment IDs):\n{json.dumps(strategic, indent=2)}"
    )

    result = run_agent(
        director_config(),
        user_message,
        context=context,
        project_path=project_path,
        timeline_summary=timeline_summary,
        emit=emit,
    )

    submit = result.orchestration.get("submit_goals")
    if not submit:
        logger.warning("Director agent did not call submit_goals")
        return None

    intent = (submit.get("intent") or "edit").lower()
    markdown = submit.get("brief_markdown") or ""

    if intent == "answer":
        brief = build_edit_brief(user_message, timeline_summary, "custom")
        return DirectorResult(
            brief=brief, markdown=markdown, goals=[], answer_only=True,
        )

    preset_hint = submit.get("preset_hint") or detect_preset(user_message)
    brief = build_edit_brief(user_message, timeline_summary, preset_hint)

    memory = SessionMemory()
    memory.apply_brief(brief.to_dict())
    memory.constraints = list(submit.get("constraints") or [])
    memory.avoid = list(submit.get("avoid") or [])
    if markdown:
        memory.style_brief = markdown[:500]

    chapters = chapters_from_director_payload(
        submit.get("chapters") or [],
        timeline_summary,
    )
    if not chapters:
        chapters = default_chapters_from_timeline(timeline_summary)

    goals: list[Goal] = []
    for item in submit.get("goals", []):
        raw_type = (item.get("type") or "video").lower()
        goals.append(Goal(
            id=new_id(),
            description=item.get("description", "Edit goal"),
            type=_TASK_TYPE_MAP.get(raw_type, TaskType.VIDEO),
            priority=int(item.get("priority", 3)),
        ))

    if not goals:
        logger.warning("Director intent=edit but no goals submitted")
        return None

    goals.sort(key=lambda g: -g.priority)
    return DirectorResult(
        brief=brief,
        markdown=markdown,
        goals=goals,
        chapters=chapters,
        memory=memory,
        answer_only=False,
    )
