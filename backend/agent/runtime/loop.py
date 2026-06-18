"""Core agent loop: observe → LLM → tool → repeat until done."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from agent.brain import PendingAction
from agent.runtime.model import call_model
from agent.runtime.tools import (
    ORCHESTRATION_TOOL_NAMES,
    normalize_tool_name,
    propose_from_call,
    run_immediate_tool,
    to_responses_tools,
    tools_by_names,
)
from agent.streaming import (
    EventEmitter,
    proposal as emit_proposal,
    step as emit_step,
    summarize_tool_output,
    tool_call as emit_tool_call,
    tool_result as emit_tool_result,
)
from agent.brain import IMMEDIATE_TOOLS, PROPOSE_TO_ACTION
from agent.runtime.agent_log import agent as log_agent

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    name: str
    instructions: str
    tool_names: set[str]
    max_turns: int = 6
    temperature: float = 0.4
    stop_on_proposals: bool = True
    orchestration_names: set[str] = field(default_factory=set)


@dataclass
class AgentRunResult:
    reply: str
    pending_actions: list[PendingAction] = field(default_factory=list)
    orchestration: dict[str, Any] = field(default_factory=dict)
    tool_trace: list[dict] = field(default_factory=list)
    turns_used: int = 0


def _append_response_to_input(input_items: list, response) -> None:
    for item in response.output:
        if item.type == "function_call":
            input_items.append({
                "type": "function_call",
                "call_id": getattr(item, "call_id", None) or getattr(item, "id", ""),
                "name": item.name,
                "arguments": item.arguments,
            })
        elif item.type == "message":
            text_parts = []
            for content in item.content:
                if content.type == "output_text" and content.text:
                    text_parts.append(content.text)
            if text_parts:
                input_items.append({
                    "role": "assistant",
                    "content": "\n".join(text_parts),
                })


def _parse_calls(response) -> tuple[str, list[dict]]:
    reply_parts: list[str] = []
    calls: list[dict] = []

    for item in response.output:
        if item.type == "function_call":
            tool_name = normalize_tool_name(item.name or "")
            try:
                args = json.loads(item.arguments)
            except json.JSONDecodeError:
                args = {}
            calls.append({
                "call_id": getattr(item, "call_id", None) or getattr(item, "id", ""),
                "name": tool_name,
                "args": args,
            })
        elif item.type == "message":
            for content in item.content:
                if content.type == "output_text" and content.text:
                    reply_parts.append(content.text)

    reply = "\n".join(reply_parts).strip() or (getattr(response, "output_text", None) or "").strip()
    return reply, calls


def run_agent(
    config: AgentConfig,
    user_message: str,
    *,
    context: str = "",
    project_path: str | None = None,
    timeline_summary: dict | None = None,
    emit: EventEmitter | None = None,
) -> AgentRunResult:
    """
    Generic ReAct-style loop used by Director, Planner, and Specialists.
    - immediate tools (search_library): run inline, feed output back
    - propose_* tools: collect as PendingAction, stop if stop_on_proposals
    - orchestration tools (submit_goals, confirm_task): stored in result.orchestration
    """
    all_tool_names = config.tool_names | config.orchestration_names
    tool_defs = tools_by_names(all_tool_names)
    for name in config.orchestration_names:
        if name == "submit_goals":
            from agent.runtime.tools import SUBMIT_GOALS_TOOL
            tool_defs.append(SUBMIT_GOALS_TOOL)
        elif name == "confirm_task":
            from agent.runtime.tools import CONFIRM_TASK_TOOL
            tool_defs.append(CONFIRM_TASK_TOOL)

    responses_tools = to_responses_tools(tool_defs) if tool_defs else None
    input_items: list[dict] = [
        {"role": "user", "content": user_message + (f"\n\n{context}" if context else "")},
    ]

    pending: list[PendingAction] = []
    orchestration: dict[str, Any] = {}
    reply_parts: list[str] = []
    tool_trace: list[dict] = []
    agent_slug = config.name.lower().replace(" ", "_")

    for turn in range(config.max_turns):
        emit_step(
            emit,
            f"{agent_slug}_turn_{turn}",
            f"{config.name} thinking (turn {turn + 1}/{config.max_turns})…",
        )
        if emit:
            emit({
                "type": "agent_thinking",
                "agent": config.name,
                "turn": turn + 1,
                "message": f"Turn {turn + 1}/{config.max_turns} — observe → think → tool",
            })

        response = call_model(
            instructions=config.instructions,
            input_items=input_items,
            tools=responses_tools,
            temperature=config.temperature,
            agent=config.name,
            emit=emit,
        )
        if response is None:
            emit_step(
                emit,
                "llm_fallback",
                "LLM unavailable — model call skipped",
                "done",
            )
            break

        step_reply, calls = _parse_calls(response)
        if step_reply:
            reply_parts.append(step_reply)
            if emit:
                emit({"type": "agent_message", "agent": config.name, "content": step_reply})

        if not calls:
            if (
                config.stop_on_proposals
                and turn + 1 < config.max_turns
            ):
                _append_response_to_input(input_items, response)
                input_items.append({
                    "role": "user",
                    "content": (
                        "Call propose_* tools now for the human's edit request in context. "
                        "Plain text without tools is not enough."
                    ),
                })
                emit_step(emit, f"{agent_slug}_turn_{turn}", "No tools — retrying…", "done")
                continue
            emit_step(emit, f"{agent_slug}_turn_{turn}", "Response complete", "done")
            break

        immediate_calls: list[dict] = []
        propose_calls: list[dict] = []
        orch_calls: list[dict] = []
        unknown_calls: list[dict] = []

        for call in calls:
            name = call["name"]
            if name in config.orchestration_names:
                orch_calls.append(call)
            elif name in IMMEDIATE_TOOLS:
                immediate_calls.append(call)
            elif name in PROPOSE_TO_ACTION:
                propose_calls.append(call)
            else:
                logger.warning("%s: unknown tool %s", config.name, name)
                unknown_calls.append(call)

        _append_response_to_input(input_items, response)

        allowed = sorted(config.tool_names | config.orchestration_names | IMMEDIATE_TOOLS)
        for call in unknown_calls:
            emit_tool_call(emit, call["name"], call["args"])
            err = json.dumps({
                "error": f"Tool {call['name']!r} does not exist.",
                "hint": "Use search_library (not google:search), get_director_picks, or propose_* tools.",
                "allowed": allowed[:12],
            })
            emit_tool_result(emit, call["name"], f"Unknown tool — use search_library or propose_*")
            tool_trace.append({"tool": call["name"], "args": call["args"], "kind": "error"})
            input_items.append({
                "type": "function_call_output",
                "call_id": call["call_id"],
                "name": call["name"],
                "output": err,
            })

        for call in orch_calls:
            log_agent("tool", agent=config.name, name=call["name"])
            emit_tool_call(emit, call["name"], call["args"])
            orchestration[call["name"]] = call["args"]
            tool_trace.append({"tool": call["name"], "args": call["args"], "kind": "orchestration"})
            emit_tool_result(emit, call["name"], f"{call['name']} recorded")
            input_items.append({
                "type": "function_call_output",
                "call_id": call["call_id"],
                "name": call["name"],
                "output": json.dumps({"status": "ok", "recorded": call["name"]}),
            })

        for call in immediate_calls:
            log_agent("tool", agent=config.name, name=call["name"], kind="immediate")
            emit_tool_call(emit, call["name"], call["args"])
            output = run_immediate_tool(
                call["name"],
                call["args"],
                project_path=project_path,
                timeline_summary=timeline_summary,
                emit=emit,
            )
            emit_tool_result(emit, call["name"], summarize_tool_output(call["name"], output))
            tool_trace.append({"tool": call["name"], "args": call["args"], "kind": "immediate"})
            input_items.append({
                "type": "function_call_output",
                "call_id": call["call_id"],
                "name": call["name"],
                "output": output,
            })

        for call in propose_calls:
            log_agent("tool", agent=config.name, name=call["name"], kind="propose")
            emit_tool_call(emit, call["name"], call["args"])
            result = propose_from_call(call["name"], call["args"])
            if result is None:
                continue
            items = result if isinstance(result, list) else [result]
            for item in items:
                emit_proposal(emit, item.description, item.action)
                pending.append(item)
            tool_trace.append({"tool": call["name"], "args": call["args"], "kind": "propose"})
            emit_tool_result(emit, call["name"], f"{len(items)} proposal(s)")

        if orchestration.get("confirm_task") or (
            orchestration.get("submit_goals") and not immediate_calls and not propose_calls
        ):
            emit_step(emit, f"{agent_slug}_turn_{turn}", "Orchestration complete", "done")
            return AgentRunResult(
                reply="\n".join(reply_parts).strip(),
                pending_actions=pending,
                orchestration=orchestration,
                tool_trace=tool_trace,
                turns_used=turn + 1,
            )

        if propose_calls and config.stop_on_proposals:
            emit_step(
                emit,
                f"{agent_slug}_turn_{turn}",
                f"{len(pending)} proposal(s) ready",
                "done",
            )
            return AgentRunResult(
                reply="\n".join(reply_parts).strip(),
                pending_actions=pending,
                orchestration=orchestration,
                tool_trace=tool_trace,
                turns_used=turn + 1,
            )

        if immediate_calls or orch_calls or unknown_calls:
            continue

        emit_step(emit, f"{agent_slug}_turn_{turn}", "Turn complete", "done")
        break

    return AgentRunResult(
        reply="\n".join(reply_parts).strip(),
        pending_actions=pending,
        orchestration=orchestration,
        tool_trace=tool_trace,
        turns_used=config.max_turns,
    )
