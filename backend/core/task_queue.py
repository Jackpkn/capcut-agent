"""In-memory edit sessions and task queue."""

from __future__ import annotations

import time
from typing import Iterator

from core.models import EditSession, SessionStatus, Task, TaskStatus, new_id

_sessions: dict[str, EditSession] = {}
_paused: set[str] = set()


def start_session(
    project_path: str,
    human_message: str,
    *,
    auto_edit: bool = False,
) -> EditSession:
    session = EditSession(
        id=new_id(),
        project_path=project_path,
        human_message=human_message,
        auto_edit=auto_edit,
    )
    _sessions[session.id] = session
    return session


def get_session(session_id: str) -> EditSession | None:
    return _sessions.get(session_id)


def list_sessions() -> list[dict]:
    return [s.to_dict() for s in sorted(_sessions.values(), key=lambda x: -x.updated_at)]


def update_session(session: EditSession) -> None:
    session.updated_at = time.time()
    _sessions[session.id] = session


def pause_session(session_id: str) -> bool:
    if session_id not in _sessions:
        return False
    _paused.add(session_id)
    session = _sessions[session_id]
    session.status = SessionStatus.PAUSED
    update_session(session)
    return True


def resume_session(session_id: str) -> bool:
    _paused.discard(session_id)
    session = _sessions.get(session_id)
    if not session:
        return False
    if session.status == SessionStatus.PAUSED:
        session.status = SessionStatus.QUEUED
    update_session(session)
    return True


def is_paused(session_id: str) -> bool:
    return session_id in _paused


def set_human_feedback(session_id: str, feedback: str) -> EditSession | None:
    session = get_session(session_id)
    if not session:
        return None
    session.human_feedback = feedback
    update_session(session)
    return session


def approve_all_tasks(session_id: str) -> EditSession | None:
    session = get_session(session_id)
    if not session:
        return None
    for task in session.tasks:
        if task.status == TaskStatus.AWAITING_APPROVAL and task.qa_approved:
            task.status = TaskStatus.APPROVED
    session.status = SessionStatus.APPLYING
    update_session(session)
    return session


def reject_task(session_id: str, task_id: str, reason: str = "") -> Task | None:
    session = get_session(session_id)
    if not session:
        return None
    for task in session.tasks:
        if task.id == task_id:
            task.status = TaskStatus.REJECTED
            task.qa_feedback.append(reason or "Rejected by human")
            update_session(session)
            return task
    return None


def pending_tasks(session: EditSession) -> Iterator[Task]:
    ordered = sorted(session.tasks, key=lambda t: (-t.priority, t.id))
    for task in ordered:
        if task.status in (TaskStatus.PENDING, TaskStatus.APPROVED):
            yield task


def actionable_tasks(session: EditSession) -> list[Task]:
    return [
        t for t in session.tasks
        if t.status in (TaskStatus.APPROVED, TaskStatus.AWAITING_APPROVAL)
        and t.qa_approved
        and t.status != TaskStatus.REJECTED
    ]
