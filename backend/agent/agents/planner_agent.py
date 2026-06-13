"""LLM Planner — goals → propose_* tool calls → Tasks."""

from __future__ import annotations

import json
import logging

from agent.agents.definitions import planner_config
from agent.brain import PendingAction
from agent.critic import critique_plan
from agent.director import EditBrief
from agent.planner import pending_to_task
from agent.runtime.loop import run_agent
from agent.runtime.model import llm_available
from agent.streaming import EventEmitter
from capcut.reader import get_project_summary
from core.models import Goal, Task
from core.slices import get_timeline_summary

logger = logging.getLogger(__name__)


def run_llm_planner(
    brief: EditBrief,
    goals: list[Goal],
    user_message: str,
    project_path: str,
    emit: EventEmitter | None = None,
) -> tuple[list[Task], list[str]] | None:
    """Run real Planner agent. Returns None if LLM unavailable or no proposals."""
    if not llm_available():
        return None

    timeline = get_timeline_summary(project_path)
    full_summary = get_project_summary(project_path)
    goals_block = json.dumps([g.to_dict() for g in goals], indent=2)

    context = (
        f"CREATIVE BRIEF:\n{json.dumps(brief.to_dict(), indent=2)}\n\n"
        f"GOALS:\n{goals_block}\n\n"
        f"TIMELINE (compact — use segment_id/text_id from here):\n"
        f"{json.dumps(timeline, indent=2)}\n\n"
        f"ORIGINAL REQUEST:\n{user_message}"
    )

    result = run_agent(
        planner_config(),
        "Build the full edit plan for these goals. Call propose_* for every change.",
        context=context,
        project_path=project_path,
        timeline_summary=timeline,
        emit=emit,
    )

    pending: list[PendingAction] = result.pending_actions
    if not pending:
        logger.warning("Planner agent returned no proposals")
        return None

    tasks: list[Task] = []
    priority = 100
    for item in pending:
        tasks.append(pending_to_task(item, project_path, priority))
        priority -= 1

    critic_notes = critique_plan(brief, pending, full_summary)
    if result.reply:
        critic_notes.insert(0, f"Planner: {result.reply[:300]}")

    return tasks, critic_notes
