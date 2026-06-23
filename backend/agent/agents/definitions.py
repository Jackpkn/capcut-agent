"""Agent personas — instructions + tool scopes (no external orchestration libs)."""

from __future__ import annotations

from agent.prompts import (
    AUDIO_INSTRUCTIONS,
    DIRECTOR_INSTRUCTIONS,
    FX_INSTRUCTIONS,
    PLANNER_INSTRUCTIONS,
    SCENE_PLANNER_INSTRUCTIONS,
    TEXT_INSTRUCTIONS,
    VIDEO_INSTRUCTIONS,
)
from agent.runtime.loop import AgentConfig
from agent.runtime.tools import (
    AUDIO_TOOLS,
    FX_TOOLS,
    PLANNER_TOOLS,
    TEXT_TOOLS,
    VIDEO_TOOLS,
)


def director_config() -> AgentConfig:
    return AgentConfig(
        name="Director Agent",
        instructions=DIRECTOR_INSTRUCTIONS,
        tool_names=set(),
        orchestration_names={"submit_goals"},
        max_turns=4,
        stop_on_proposals=False,
    )


def planner_config() -> AgentConfig:
    return AgentConfig(
        name="Planner Agent",
        instructions=PLANNER_INSTRUCTIONS,
        tool_names=PLANNER_TOOLS,
        max_turns=8,
        stop_on_proposals=True,
    )


def scene_planner_config() -> AgentConfig:
    return AgentConfig(
        name="Scene Planner Agent",
        instructions=SCENE_PLANNER_INSTRUCTIONS,
        tool_names=PLANNER_TOOLS,
        max_turns=8,
        stop_on_proposals=True,
    )


def specialist_config(domain: str) -> AgentConfig:
    tool_map = {
        "video": VIDEO_TOOLS,
        "audio": AUDIO_TOOLS,
        "text": TEXT_TOOLS,
        "effects": FX_TOOLS,
    }
    instr_map = {
        "video": VIDEO_INSTRUCTIONS,
        "audio": AUDIO_INSTRUCTIONS,
        "text": TEXT_INSTRUCTIONS,
        "effects": FX_INSTRUCTIONS,
    }
    names = {
        "video": "Video Agent",
        "audio": "Audio Agent",
        "text": "Text Agent",
        "effects": "FX Agent",
    }
    return AgentConfig(
        name=names.get(domain, "Specialist Agent"),
        instructions=instr_map.get(domain, VIDEO_INSTRUCTIONS),
        tool_names=tool_map.get(domain, VIDEO_TOOLS),
        orchestration_names={"confirm_task"},
        max_turns=5,
        stop_on_proposals=False,
    )
