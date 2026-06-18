"""Agent loop — Director → Planner → Specialists → QA → human approval."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Callable

from agent.qa_agent import review_all_tasks, review_task
from agent.specialists.router import execute_specialist
from agent.team_director import run_director
from agent.streaming import sse_line
from core.models import EditSession, SessionStatus, TaskStatus
from core.slices import get_timeline_summary
from core.task_queue import get_session, is_paused, update_session

EventEmitter = Callable[[dict], None]

_TASK_DONE_STATUSES = frozenset({
    TaskStatus.AWAITING_APPROVAL,
    TaskStatus.APPROVED,
    TaskStatus.REJECTED,
    TaskStatus.DONE,
})


def _answer_via_single_agent(session: EditSession, emit: EventEmitter | None) -> EditSession:
    """Model-driven Q&A when Director unavailable or chose answer intent."""
    from agent.brain import stream_agent_events

    result = stream_agent_events(
        session.human_message,
        session.project_path,
        emit=emit,
    )
    session.brief_markdown = result.reply
    session.goals = []
    session.tasks = []
    session.critic_notes = []
    session.status = SessionStatus.DONE
    update_session(session)
    return session


def _edit_via_single_agent(session: EditSession, emit: EventEmitter | None) -> EditSession:
    """Team planners produced nothing — fall back to direct edit agent + tools."""
    from agent.brain import stream_agent_events
    from agent.planner import pending_to_task
    from agent.runtime.agent_log import agent as log_agent
    from capcut.reader import get_project_summary

    log_agent("team fallback → edit agent", session_id=session.id)
    if emit:
        emit({
            "type": "step",
            "id": "edit_fallback",
            "status": "running",
            "label": "Edit agent — direct tool proposals…",
        })

    result = stream_agent_events(
        session.human_message,
        session.project_path,
        emit=emit,
        project_summary=get_project_summary(session.project_path),
    )
    if not result.pending_actions:
        session.brief_markdown = result.reply or (
            "Could not plan edits via team workflow — edit agent returned no proposals."
        )
        session.tasks = []
        session.status = SessionStatus.DONE
        update_session(session)
        return session

    session.tasks = [
        pending_to_task(item, session.project_path, 100 - i)
        for i, item in enumerate(result.pending_actions)
    ]
    session.brief_markdown = result.reply
    if result.reply and result.pending_actions:
        plan = "\n".join(f"  • {t.description}" for t in session.tasks)
        session.brief_markdown = (
            f"{result.reply}\n\n**Planned changes (awaiting approval):**\n{plan}"
        ).strip()
    session.status = SessionStatus.QUEUED
    update_session(session)
    return session


def plan_session(session: EditSession, emit: EventEmitter | None = None) -> EditSession:
    """Director (LLM) decides answer vs edit → Planner queues tasks."""
    from agent.runtime.agent_log import agent as log_agent
    from core.project_ledger import hydrate_session_memory

    log_agent("plan_session", session_id=session.id, auto_edit=session.auto_edit)

    session.session_memory = hydrate_session_memory(
        session.project_path,
        session.session_memory,
    )
    update_session(session)

    session.status = SessionStatus.PLANNING
    session.timeline_summary = get_timeline_summary(session.project_path)

    from agent.plan_guard import timeline_edit_blockers

    blocked, block_msg, block_warnings = timeline_edit_blockers(session.project_path)
    if blocked:
        session.brief_markdown = block_msg
        session.goals = []
        session.tasks = []
        session.critic_notes = block_warnings
        session.status = SessionStatus.DONE
        update_session(session)
        return session

    director = run_director(
        session.human_message,
        session.timeline_summary,
        session.project_path,
        emit=emit,
        auto_edit=session.auto_edit,
    )
    if director is None:
        return _answer_via_single_agent(session, emit)

    if director.answer_only:
        log_agent("director answer_only — falling back to chat agent", session_id=session.id)
        # Director has no present_timeline / segment data — use chat agent for Q&A visuals.
        return _answer_via_single_agent(session, emit)

    from agent.director import brief_to_markdown
    from agent.scene_planner import run_scene_planner
    brief = director.brief
    session.goals = director.goals
    session.chapters = director.chapters
    log_agent(
        "director edit plan",
        session_id=session.id,
        chapters=len(session.chapters),
        goals=len(session.goals),
    )
    from core.project_ledger import hydrate_session_memory
    from core.session_memory import SessionMemory

    session.session_memory = hydrate_session_memory(
        session.project_path,
        director.memory.to_dict(),
    )
    memory = SessionMemory.from_dict(session.session_memory)

    if emit:
        emit({
            "type": "chapter_map",
            "chapters": [c.to_dict() for c in session.chapters],
            "memory": session.session_memory,
        })

    all_tasks = []
    all_notes: list[str] = list(block_warnings)

    for chapter in session.chapters:
        chapter.status = "planning"
        log_agent(
            "scene_planner",
            chapter=chapter.label,
            index=f"{chapter.index}/{len(session.chapters)}",
        )
        if emit:
            emit({
                "type": "chapter_started",
                "chapter": chapter.to_dict(),
                "index": chapter.index,
                "total": len(session.chapters),
            })

        ch_tasks, ch_notes = run_scene_planner(
            brief,
            chapter,
            session.goals,
            session.human_message,
            session.project_path,
            session.timeline_summary,
            memory,
            emit=emit,
        )
        if chapter.index < len(session.chapters):
            time.sleep(1.5)
        chapter.status = "planned" if ch_tasks else "done"
        all_tasks.extend(ch_tasks)
        all_notes.extend(ch_notes)

        if emit:
            emit({
                "type": "chapter_planned",
                "chapter": chapter.to_dict(),
                "task_count": len(ch_tasks),
                "index": chapter.index,
                "total": len(session.chapters),
            })

    session.tasks = all_tasks
    session.critic_notes = all_notes
    session.session_memory = memory.to_dict()
    session.brief_markdown = brief_to_markdown(brief)
    if director.markdown:
        session.brief_markdown = director.markdown + "\n\n" + session.brief_markdown
    session.brief_data = brief.to_dict()
    if not all_tasks:
        rate_hint = ""
        if any("rate" in n.lower() or "limit" in n.lower() for n in all_notes):
            rate_hint = (
                " Model rate limit may be active — wait ~60s or switch LLM_PROVIDER."
            )
        log_agent("no team tasks — edit agent fallback", session_id=session.id)
        return _edit_via_single_agent(session, emit)
    session.status = SessionStatus.QUEUED
    update_session(session)
    log_agent(
        "plan_session done",
        session_id=session.id,
        tasks=len(all_tasks),
        chapters=len(session.chapters),
    )
    return session


def iter_team_sse(session_id: str) -> Iterator[str]:
    """Stream team workflow: plan → specialists → QA → awaiting approval."""
    session = get_session(session_id)
    if not session:
        yield sse_line({"type": "error", "message": f"Session not found: {session_id}"})
        return

    try:
        yield sse_line({
            "type": "team_start",
            "session_id": session_id,
            "message": session.human_message,
        })

        yield sse_line({
            "type": "step",
            "id": "director",
            "status": "running",
            "label": "Director Agent — understanding goal…",
        })

        import queue
        import threading

        plan_q: queue.Queue = queue.Queue()
        plan_box: dict = {}

        def plan_worker() -> None:
            plan_box["session"] = plan_session(session, emit=lambda ev: plan_q.put(ev))
            plan_q.put(None)

        if not session.tasks:
            threading.Thread(target=plan_worker, daemon=True).start()
            while True:
                ev = plan_q.get()
                if ev is None:
                    break
                yield sse_line(ev)
            session = plan_box["session"]

        if session.status == SessionStatus.DONE and not session.tasks:
            from agent.streaming import emit_text_chunks

            stream_events: list[dict] = []
            emit_text_chunks(stream_events.append, session.brief_markdown)
            for ev in stream_events:
                yield sse_line(ev)
            done_label = (
                "Planning incomplete — no tasks queued"
                if session.goals
                else "Answer ready"
            )
            yield sse_line({
                "type": "step",
                "id": "director",
                "status": "done",
                "label": done_label,
            })
            yield sse_line({
                "type": "done",
                "reply": session.brief_markdown,
                "session_id": session_id,
                "actions": [],
                "pending_actions": [],
            })
            return

        yield sse_line({
            "type": "director_brief",
            "markdown": session.brief_markdown,
            "goals": [g.to_dict() for g in session.goals],
        })
        yield sse_line({
            "type": "step",
            "id": "director",
            "status": "done",
            "label": f"Director — {len(session.goals)} goal(s) defined",
        })

        yield sse_line({
            "type": "step",
            "id": "planner",
            "status": "running",
            "label": "Planner Agent — building task queue…",
        })
        yield sse_line({
            "type": "task_queue",
            "tasks": [t.to_dict() for t in session.tasks],
            "count": len(session.tasks),
        })
        yield sse_line({
            "type": "step",
            "id": "planner",
            "status": "done",
            "label": f"Planner — {len(session.tasks)} task(s) queued",
        })

        for note in session.critic_notes:
            yield sse_line({"type": "critic_note", "content": note})

        session.status = SessionStatus.RUNNING
        update_session(session)

        from agent.runtime.stream_emit import is_live_sse_event
        from agent.streaming import should_surface_trace_event

        approved_tasks = []
        specialist_events: list[dict] = []

        def _yield_specialist_event(ev: dict) -> Iterator[str]:
            if is_live_sse_event(ev) or should_surface_trace_event(ev):
                yield sse_line(ev)

        def specialist_emit(event: dict) -> None:
            specialist_events.append(event)

        from agent.timeline_anchor import describe_timeline_target
        from agent.streaming import agent_activity

        total_tasks = len(session.tasks)
        for i, task in enumerate(session.tasks, start=1):
            if is_paused(session_id):
                yield sse_line({
                    "type": "loop_paused",
                    "reason": "Human paused the session",
                    "session_id": session_id,
                })
                session.status = SessionStatus.PAUSED
                update_session(session)
                return

            if task.status in _TASK_DONE_STATUSES:
                if task.status == TaskStatus.AWAITING_APPROVAL and task.qa_approved:
                    approved_tasks.append(task)
                continue

            task.status = TaskStatus.RUNNING
            from agent.runtime.agent_log import agent as log_agent
            log_agent(
                "specialist",
                task=f"{task.specialist}: {task.description[:50]}",
                index=f"{i}/{total_tasks}",
            )
            anchor = describe_timeline_target(
                task.action, task.params or {}, session.timeline_summary,
            )
            agent_activity(
                specialist_emit,
                agent=task.specialist,
                phase="working",
                detail=task.description,
                anchor=anchor or None,
                index=i,
                total=total_tasks,
            )
            while specialist_events:
                yield from _yield_specialist_event(specialist_events.pop(0))

            yield sse_line({
                "type": "task_started",
                "task": task.to_dict(),
                "index": i,
                "total": total_tasks,
                "anchor": anchor or None,
            })
            task = execute_specialist(task, session.project_path, emit=specialist_emit)
            while specialist_events:
                yield from _yield_specialist_event(specialist_events.pop(0))

            yield sse_line({
                "type": "step",
                "id": f"specialist_{task.id}",
                "status": "running",
                "label": f"{task.specialist}: {task.instruction[:60]}",
            })

            qa = review_task(task, session.project_path)
            task.qa_feedback = qa["issues"]
            task.qa_approved = qa["approved"]

            yield sse_line({
                "type": "step",
                "id": f"qa_{task.id}",
                "status": "done" if qa["approved"] else "error",
                "label": f"QA — {task.description[:48]}",
                "detail": "; ".join(qa["issues"]) if qa["issues"] else None,
            })

            if qa["approved"]:
                task.status = TaskStatus.AWAITING_APPROVAL
                approved_tasks.append(task)
                agent_activity(
                    specialist_emit,
                    agent=task.specialist,
                    phase="ready",
                    detail=task.description,
                    anchor=anchor or None,
                    index=i,
                    total=total_tasks,
                )
                yield sse_line({
                    "type": "task_proposed",
                    "task": task.to_dict(),
                    "action": task.action,
                    "params": task.params,
                    "anchor": anchor or None,
                })
            else:
                task.status = TaskStatus.REJECTED
                yield sse_line({
                    "type": "task_rejected",
                    "task": task.to_dict(),
                    "reason": "; ".join(qa["issues"]),
                })

            yield sse_line({
                "type": "step",
                "id": f"specialist_{task.id}",
                "status": "done" if qa["approved"] else "error",
                "label": f"{task.specialist} — {task.description[:50]}",
            })
            time.sleep(0.08)

        session.status = SessionStatus.AWAITING_APPROVAL
        update_session(session)

        actions = [
            {
                "action": t.action,
                "params": t.params,
                "description": t.description,
                "chapter_id": t.chapter_id,
            }
            for t in approved_tasks
        ]

        if actions:
            from core.project_ledger import record_proposed_edits

            record_proposed_edits(session.project_path, actions)

        rejected = [t for t in session.tasks if t.status == TaskStatus.REJECTED]
        team_plan = {
            "goals_count": len(session.goals),
            "queued_count": len(session.tasks),
            "approved_count": len(approved_tasks),
            "rejected_count": len(rejected),
            "brief": session.brief_data,
            "warnings": session.critic_notes,
            "approved_tasks": [t.to_dict() for t in approved_tasks],
            "rejected_tasks": [t.to_dict() for t in rejected],
            "chapters": [
                c.to_dict() if hasattr(c, "to_dict") else c for c in session.chapters
            ],
            "session_memory": session.session_memory,
        }
        reply = _format_team_reply(session, approved_tasks)
        edit_diff = None
        if actions:
            try:
                from agent.diff import compute_edit_diff
                edit_diff = compute_edit_diff(session.project_path, actions)
            except Exception:
                pass

        yield sse_line({
            "type": "team_plan",
            "plan": team_plan,
        })
        yield sse_line({
            "type": "awaiting_human",
            "session_id": session_id,
            "task_count": len(approved_tasks),
            "actions": actions,
        })
        yield sse_line({
            "type": "done",
            "reply": reply,
            "session_id": session_id,
            "actions": actions,
            "pending_actions": actions,
            "edit_diff": edit_diff,
            "team_plan": team_plan,
        })

    except Exception as e:
        session.status = SessionStatus.FAILED
        session.error = str(e)
        update_session(session)
        yield sse_line({"type": "error", "message": str(e)})


def _format_team_reply(session: EditSession, tasks: list) -> str:
    """Short fallback text; UI renders structured team_plan payload."""
    rejected = sum(1 for t in session.tasks if t.status == TaskStatus.REJECTED)
    if session.auto_edit:
        label = "Auto edit"
    else:
        label = session.brief_data.get("preset_label", "Edit plan")
    return (
        f"**{label}** — {len(tasks)} change(s) ready to apply"
        + (f", {rejected} skipped by QA" if rejected else "")
        + ". Review below and approve."
    )


def _record_applied_actions(session: EditSession, actions: list[dict]) -> None:
    """Persist applied edits to project ledger and sync session memory."""
    from core.project_ledger import record_applied_for_session

    record_applied_for_session(session, actions)


def _approved_tasks_for_apply(session: EditSession) -> list:
    return [
        t for t in session.tasks
        if t.qa_approved and t.status not in (TaskStatus.REJECTED, TaskStatus.DONE)
    ]


def apply_session_tasks(session_id: str) -> tuple[list[str], str]:
    """Apply all QA-approved tasks in one batch."""
    from agent.actions import execute_actions
    from capcut.project_ui import apply_with_ui_handoff
    from capcut.cdp import sync_capcut

    session = get_session(session_id)
    if not session:
        raise ValueError(f"Session not found: {session_id}")

    tasks = _approved_tasks_for_apply(session)
    if not tasks:
        raise ValueError("No approved tasks to apply")

    actions = [
        {"action": t.action, "params": t.params, "description": t.description}
        for t in tasks
    ]

    session.status = SessionStatus.APPLYING
    update_session(session)

    results, suffix = apply_with_ui_handoff(
        session.project_path,
        lambda: execute_actions(actions, session.project_path),
    )
    sync_capcut(session.project_path)

    for t, res in zip(tasks, results):
        if res.startswith("Failed to apply:"):
            t.status = TaskStatus.FAILED
            t.agent_reasoning += f" Error: {res}"
        else:
            t.status = TaskStatus.DONE

    _record_applied_actions(session, actions)
    from agent.runtime.agent_log import agent as log_agent
    log_agent("apply done", session_id=session.id, actions=len(actions))
    session.status = SessionStatus.DONE
    update_session(session)
    return results, suffix


def iter_apply_actions_sse(
    project_path: str,
    actions: list[dict],
    *,
    session_id: str | None = None,
) -> Iterator[str]:
    """Apply actions one-by-one with CDP reload (works without a live session)."""
    from agent.actions import execute_action
    from agent.brain import format_execute_reply
    from capcut.cdp import sync_capcut
    from capcut.project_ui import is_project_locked, reopen_project

    if not actions:
        yield sse_line({"type": "error", "message": "No actions to apply"})
        return

    session = get_session(session_id) if session_id else None
    if session:
        session.status = SessionStatus.APPLYING
        update_session(session)

    yield sse_line({
        "type": "agent_start",
        "message": f"Applying {len(actions)} task(s) one-by-one with live CapCut reload…",
    })

    results: list[str] = []
    try:
        for i, item in enumerate(actions, start=1):
            action = item["action"]
            params = item.get("params", {})
            desc = item.get("description") or action
            step_id = f"apply_{i}"
            yield sse_line({
                "type": "step",
                "id": step_id,
                "status": "running",
                "label": f"[{i}/{len(actions)}] {desc}",
            })
            cdp = None
            try:
                msg = execute_action(action, params, project_path)
                results.append(msg)

                if session:
                    for task in session.tasks:
                        if task.action == action and task.params == params:
                            task.status = TaskStatus.DONE
                            break
                    update_session(session)

                cdp = sync_capcut(project_path)
                yield sse_line({
                    "type": "step",
                    "id": step_id,
                    "status": "done",
                    "label": f"[{i}/{len(actions)}] {desc}",
                    "detail": msg,
                })
            except Exception as e:
                msg = f"Failed to apply: {e}"
                results.append(msg)
                if session:
                    for task in session.tasks:
                        if task.action == action and task.params == params:
                            task.status = TaskStatus.FAILED
                            task.agent_reasoning += f" Error: {e}"
                            break
                    update_session(session)
                yield sse_line({
                    "type": "step",
                    "id": step_id,
                    "status": "error",
                    "label": f"[{i}/{len(actions)}] {desc} (Failed)",
                    "detail": str(e),
                })

            yield sse_line({
                "type": "task_applied",
                "index": i,
                "total": len(actions),
                "result": msg,
                "cdp": cdp,
            })

        yield sse_line({
            "type": "step",
            "id": "reopen",
            "status": "running",
            "label": "Reopening project in CapCut…",
        })
        reopened = reopen_project(project_path)
        sync_capcut(project_path)
        yield sse_line({
            "type": "step",
            "id": "reopen",
            "status": "done" if reopened else "error",
            "label": "Project reopened in CapCut" if reopened else "Edits saved — open project in CapCut",
        })

        if session:
            _record_applied_actions(session, actions)
            session.status = SessionStatus.DONE
            update_session(session)
        else:
            from core.project_ledger import record_applied_edits

            record_applied_edits(project_path, actions)

        reply = format_execute_reply(results)
        if reopened:
            reply += (
                "\n\nProject reopened in CapCut. Scrub the timeline to verify each change."
            )

        skipped = sum(
            1 for r in results
            if "no change needed" in r.lower() or "skipped" in r.lower()
        )
        if skipped:
            reply += (
                f"\n\n_{skipped} step(s) made no visible change (already at target)._"
            )
        if is_project_locked(project_path):
            reply += (
                "\n\n**CapCut still has the project open** — edits are on disk but the "
                "preview may look unchanged. Click **Home** (top-left), wait 3 seconds, "
                "then reopen your project to refresh."
            )

        yield sse_line({
            "type": "done",
            "reply": reply,
            "results": results,
            "session_id": session_id,
        })
    except Exception as e:
        if session:
            session.status = SessionStatus.FAILED
            session.error = str(e)
            update_session(session)
        yield sse_line({"type": "error", "message": str(e)})


def resolve_team_apply_actions(
    session_id: str,
    project_path: str | None = None,
    actions: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    """Resolve project + actions from session or request body fallback."""
    session = get_session(session_id)
    if session:
        tasks = _approved_tasks_for_apply(session)
        if not tasks:
            raise ValueError("No approved tasks to apply")
        return session.project_path, [
            {"action": t.action, "params": t.params, "description": t.description}
            for t in tasks
        ]
    if project_path and actions:
        return project_path, actions
    raise ValueError(
        "Team session expired (server restarted). Resend your edit request, "
        "or approve again — the UI will resubmit the planned actions."
    )


def iter_apply_session_sse(session_id: str) -> Iterator[str]:
    """Apply QA-approved tasks one-by-one with CDP reload between each."""
    try:
        project_path, actions = resolve_team_apply_actions(session_id)
    except ValueError as e:
        yield sse_line({"type": "error", "message": str(e)})
        return
    yield from iter_apply_actions_sse(project_path, actions, session_id=session_id)
