"""Tool registry — propose, immediate, and orchestration tools for agent loops."""

from __future__ import annotations

import json
from collections.abc import Callable

from agent.actions import describe_action
from agent.brain import (
    IMMEDIATE_TOOLS,
    PROPOSE_TO_ACTION,
    TOOLS,
    PendingAction,
    _execute_immediate_tool,
    _tool_to_pending,
)
ToolHandler = Callable[[dict], str]

_TOOL_ALIASES = {
    "search": "search_library",
    "google_search": "search_library",
    "web_search": "search_library",
    "library_search": "search_library",
    "director_picks": "get_director_picks",
}


def normalize_tool_name(name: str) -> str:
    """Map hallucinated or prefixed tool names to registered tools."""
    raw = (name or "").split("<|")[0].strip()
    if "/" in raw:
        raw = raw.rsplit("/", 1)[-1].strip()
    if raw and not raw.startswith("propose_"):
        candidate = f"propose_{raw}"
        if candidate in PROPOSE_TO_ACTION:
            return candidate
    if ":" in raw:
        suffix = raw.split(":")[-1].strip()
        if suffix in _TOOL_ALIASES:
            return _TOOL_ALIASES[suffix]
        if suffix in IMMEDIATE_TOOLS or suffix in PROPOSE_TO_ACTION:
            return suffix
        if suffix.startswith("propose_"):
            return suffix
    if raw in _TOOL_ALIASES:
        return _TOOL_ALIASES[raw]
    return raw


def to_responses_tools(tool_defs: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "name": tool["function"]["name"],
            "description": tool["function"]["description"],
            "parameters": tool["function"]["parameters"],
        }
        for tool in tool_defs
    ]


def tools_by_names(names: set[str]) -> list[dict]:
    return [t for t in TOOLS if t["function"]["name"] in names]


def propose_from_call(tool_name: str, args: dict) -> PendingAction | list[PendingAction] | None:
    if tool_name not in PROPOSE_TO_ACTION:
        return None
    return _tool_to_pending(tool_name, args)


def run_immediate_tool(
    name: str,
    args: dict,
    *,
    project_path: str | None = None,
    timeline_summary: dict | None = None,
    emit=None,
) -> str:
    return _execute_immediate_tool(
        name,
        args,
        project_path=project_path,
        timeline_summary=timeline_summary,
        emit=emit,
    )


# --- Domain tool sets (specialists only see their slice + matching propose_* tools) ---

VIDEO_TOOLS = {
    "propose_update_clip_speed",
    "propose_trim_clip",
    "propose_reorder_clips",
    "propose_move_segment",
    "propose_set_segment_visibility",
    "propose_sync_video_to_beats",
}

AUDIO_TOOLS = {
    "propose_update_volume",
    "propose_add_music",
    "propose_replace_music",
    "search_library",
    "get_director_picks",
}

TEXT_TOOLS = {
    "propose_update_text",
    "propose_batch_update_texts",
    "propose_generate_captions",
    "propose_add_text_template",
}

FX_TOOLS = {
    "propose_add_transition",
    "propose_update_transition",
    "propose_add_effect",
    "propose_remove_effect",
    "propose_add_sticker",
    "search_library",
    "get_director_picks",
}

PLANNER_TOOLS = set(PROPOSE_TO_ACTION) | IMMEDIATE_TOOLS

ACTION_TO_PROPOSE = {v: k for k, v in PROPOSE_TO_ACTION.items()}


def propose_tool_for_action(action: str) -> str | None:
    return ACTION_TO_PROPOSE.get(action)


# --- Orchestration tools (director / planner meta-actions) ---

SUBMIT_GOALS_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_goals",
        "description": (
            "Submit your decision after reading the human request and timeline. "
            "Use intent=answer for questions/inspection (any language); intent=edit for timeline changes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": ["answer", "edit"],
                    "description": "answer = respond with project facts only; edit = plan timeline changes",
                },
                "preset_hint": {
                    "type": "string",
                    "description": "When intent=edit: blog, travel_vlog, cinematic, tiktok_viral, energetic, or custom",
                },
                "brief_markdown": {
                    "type": "string",
                    "description": "intent=answer: full answer with tables/lists from timeline. intent=edit: creative brief.",
                },
                "goals": {
                    "type": "array",
                    "description": "Required when intent=edit (2–6 goals). Empty when intent=answer.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": ["video", "audio", "text", "effects"],
                            },
                            "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                        },
                        "required": ["description", "type"],
                    },
                },
                "chapters": {
                    "type": "array",
                    "description": "When intent=edit: narrative chapters (time ranges only, no segment IDs).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"},
                            "start_sec": {"type": "number"},
                            "end_sec": {"type": "number"},
                            "label": {"type": "string"},
                            "pacing": {"type": "string", "enum": ["slow", "medium", "fast"]},
                            "notes": {"type": "string"},
                        },
                        "required": ["start_sec", "end_sec", "label"],
                    },
                },
                "constraints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Style rules for session memory",
                },
                "avoid": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Things to avoid (session memory)",
                },
            },
            "required": ["intent", "brief_markdown"],
        },
    },
}

CONFIRM_TASK_TOOL = {
    "type": "function",
    "function": {
        "name": "confirm_task",
        "description": (
            "Confirm the final action after verifying IDs and params against the domain slice. "
            "Use the matching propose_* tool first if params need changes; then confirm."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reasoning": {
                    "type": "string",
                    "description": "Why these params are correct for this timeline slice",
                },
                "action": {"type": "string"},
                "params": {"type": "object"},
                "description": {"type": "string"},
            },
            "required": ["reasoning", "action", "params", "description"],
        },
    },
}

ORCHESTRATION_TOOL_NAMES = frozenset({"submit_goals", "confirm_task"})
