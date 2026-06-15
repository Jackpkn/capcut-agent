"""LLM Specialist — verify task against domain slice, refine params, confirm."""

from __future__ import annotations

import json
import logging

from agent.agents.definitions import specialist_config
from agent.runtime.loop import run_agent
from agent.runtime.model import llm_available
from agent.runtime.tools import propose_tool_for_action
from agent.streaming import EventEmitter
from core.models import Task
from core.retrieve_context import retrieve_context

logger = logging.getLogger(__name__)


def run_llm_specialist(
    task: Task,
    project_path: str,
    emit: EventEmitter | None = None,
) -> Task | None:
    """Run specialist agent loop for one task. Returns updated task or None on failure."""
    if not llm_available():
        return None

    domain = task.type.value
    retrieved = retrieve_context(project_path, task.instruction, domain=domain)
    task.context_summary = {
        "domains": retrieved.domains,
        "notes": retrieved.retrieval_notes,
    }

    propose_tool = propose_tool_for_action(task.action)
    tool_hint = f"Primary tool: {propose_tool}" if propose_tool else ""

    user_message = (
        f"TASK: {task.instruction}\n"
        f"ACTION: {task.action}\n"
        f"PARAMS: {json.dumps(task.params)}\n"
        f"{tool_hint}\n"
        "Verify against the slice, refine if needed, then confirm_task."
    )
    context = retrieved.to_prompt_block()

    result = run_agent(
        specialist_config(domain),
        user_message,
        context=context,
        project_path=project_path,
        emit=emit,
    )

    confirm = result.orchestration.get("confirm_task")
    if confirm:
        task.action = confirm.get("action", task.action)
        task.params = confirm.get("params", task.params)
        task.description = confirm.get("description", task.description)
        task.agent_reasoning = confirm.get("reasoning", result.reply or task.agent_reasoning)
        return task

    if result.pending_actions:
        best = result.pending_actions[-1]
        task.action = best.action
        task.params = best.params
        task.description = best.description
        task.agent_reasoning = result.reply or f"{task.specialist} refined via propose_*"
        return task

    if result.reply:
        task.agent_reasoning = result.reply
        return task

    return None
