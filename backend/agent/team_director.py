"""Director Agent (CEO) — strategic layer; LLM only."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.chapters import Chapter
from core.models import Goal
from core.session_memory import SessionMemory

from agent.director import EditBrief


@dataclass
class DirectorResult:
    brief: EditBrief
    markdown: str
    goals: list[Goal]
    chapters: list[Chapter] = field(default_factory=list)
    memory: SessionMemory = field(default_factory=SessionMemory)
    answer_only: bool = False


def run_director(
    user_message: str,
    timeline_summary: dict,
    project_path: str,
    emit=None,
) -> DirectorResult | None:
    """Director LLM (strategic). Returns None if model unavailable."""
    from agent.agents.director_agent import run_llm_director

    return run_llm_director(user_message, timeline_summary, project_path, emit=emit)
