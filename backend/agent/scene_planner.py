"""Layer 2 — Scene Planner: one chapter → atomic tasks."""

from __future__ import annotations

import json
import logging

from agent.agents.definitions import scene_planner_config
from agent.brain import PendingAction
from agent.critic import critique_plan
from agent.director import EditBrief
from agent.planner import pending_to_task
from agent.runtime.loop import run_agent
from agent.runtime.model import llm_available
from agent.streaming import EventEmitter
from capcut.reader import get_project_summary
from core.chapters import Chapter, chapter_timeline_slice
from core.models import Goal, Task
from core.retrieve_context import retrieve_context
from core.session_memory import SessionMemory

logger = logging.getLogger(__name__)


def run_scene_planner(
  brief: EditBrief,
  chapter: Chapter,
  goals: list[Goal],
  user_message: str,
  project_path: str,
  timeline_summary: dict,
  memory: SessionMemory,
  emit: EventEmitter | None = None,
) -> tuple[list[Task], list[str]]:
  """Tactical planner for a single chapter — chunked context only."""
  if not goals:
    return [], []

  if not llm_available():
    return [], [
      f"Scene planner unavailable for {chapter.label} — set GROQ_API_KEY or GEMINI_API_KEY.",
    ]

  from agent.runtime.groq_rate_state import rate_limit_hint

  hint = rate_limit_hint()
  if hint:
    return [], [f"{chapter.label}: {hint}"]

  slice_data = chapter_timeline_slice(timeline_summary, chapter)
  if slice_data["clip_count"] == 0 and chapter.index > 1:
    return [], [f"No video clips in {chapter.label} ({chapter.start_sec:.0f}–{chapter.end_sec:.0f}s) — skipped."]

  retrieved = retrieve_context(
    project_path,
    user_message,
    chapter=chapter,
    ledger=memory.edit_ledger,
  )

  goals_block = json.dumps([g.to_dict() for g in goals], indent=2)
  context = (
    f"{memory.prompt_block()}\n\n"
    f"CREATIVE BRIEF:\n{json.dumps(brief.to_dict(), indent=2)}\n\n"
    f"{retrieved.to_prompt_block()}\n\n"
    f"GOALS (session-wide):\n{goals_block}\n\n"
    f"ORIGINAL REQUEST:\n{user_message}\n\n"
    "Use segment_id and text_id ONLY from WORKING SLICE above."
  )

  result = run_agent(
    scene_planner_config(),
    f"Plan edits for chapter «{chapter.label}» ({chapter.start_sec:.0f}s–{chapter.end_sec:.0f}s).",
    context=context,
    project_path=project_path,
    timeline_summary=timeline_summary,
    emit=emit,
  )

  pending: list[PendingAction] = result.pending_actions
  if not pending:
    return [], [f"Scene planner: no tasks for {chapter.label}."]

  full_summary = get_project_summary(project_path)
  tasks: list[Task] = []
  priority = 100 - chapter.index
  for item in pending:
    task = pending_to_task(item, project_path, priority)
    task.chapter_id = chapter.id
    task.instruction = f"[{chapter.label}] {task.instruction}"
    task.description = f"[{chapter.label}] {task.description}"
    priority -= 1
    tasks.append(task)

  from core.task_deps import order_tasks as sort_chapter_tasks

  tasks = sort_chapter_tasks(tasks)

  critic_notes = critique_plan(brief, pending, full_summary)
  if result.reply:
    critic_notes.insert(0, f"{chapter.label}: {result.reply[:200]}")

  memory.record_chapter_planned(chapter.id, len(tasks), chapter.notes)
  return tasks, critic_notes
