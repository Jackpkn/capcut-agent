"""Queue edits and auto-apply when CapCut is no longer running."""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from capcut.cdp import sync_capcut
from capcut.guard import can_write_safely
from capcut.project_ui import prepare_project_for_write, reopen_project

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 1.5


@dataclass
class QueuedApply:
    project_path: str
    actions: list[dict]
    queued_at: float = field(default_factory=time.time)
    status: str = "waiting"  # waiting | applying | done | failed
    message: str = ""
    results: list[str] = field(default_factory=list)


_queue: QueuedApply | None = None
_lock = threading.Lock()
_on_change: Callable[[QueuedApply | None], None] | None = None
_poller_started = False


def set_queue_listener(callback: Callable[[QueuedApply | None], None] | None) -> None:
    global _on_change
    _on_change = callback


def _notify() -> None:
    if _on_change and _queue:
        _on_change(_queue)
    elif _on_change:
        _on_change(None)


def get_queue() -> QueuedApply | None:
    with _lock:
        return _queue


def clear_queue() -> None:
    global _queue
    with _lock:
        _queue = None
    _notify()


def queue_apply(project_path: str, actions: list[dict]) -> QueuedApply:
    global _queue
    item = QueuedApply(project_path=project_path, actions=actions)
    with _lock:
        _queue = item
    logger.info("Queued %d action(s) for %s", len(actions), project_path)
    _notify()
    return item


def open_capcut() -> bool:
    try:
        subprocess.run(
            ["open", "-a", "CapCut"],
            check=False,
            capture_output=True,
        )
        return True
    except OSError as e:
        logger.warning("Could not open CapCut: %s", e)
        return False


def _apply_now(item: QueuedApply) -> None:
    from agent.actions import execute_actions
    from agent.brain import format_execute_reply, record_assistant_reply

    item.status = "applying"
    _notify()
    try:
        results = execute_actions(item.actions, item.project_path)
        sync_capcut(item.project_path)
        item.results = results
        item.status = "done"
        item.message = format_execute_reply(results)
        record_assistant_reply(item.message)
        logger.info("Auto-applied %d action(s)", len(results))
        if reopen_project(item.project_path):
            item.message += "\n\nProject reopened in CapCut with your edits."
        else:
            open_capcut()
            item.message += f"\n\nEdits saved — open project in CapCut."
    except Exception as e:
        logger.exception("Auto-apply failed")
        item.status = "failed"
        item.message = str(e)


def _poll_loop() -> None:
    global _queue
    while True:
        time.sleep(POLL_INTERVAL_SEC)
        with _lock:
            item = _queue
            if item is None or item.status != "waiting":
                continue
            if not can_write_safely(item.project_path):
                prepare_project_for_write(item.project_path)
                continue
            if not can_write_safely(item.project_path):
                continue
        logger.info("Project unlocked — auto-applying queued edits")
        _apply_now(item)
        _notify()


def start_apply_poller() -> None:
    global _poller_started
    if _poller_started:
        return
    _poller_started = True
    thread = threading.Thread(target=_poll_loop, daemon=True, name="apply-queue-poller")
    thread.start()
    logger.info("Apply queue poller started (interval %.1fs)", POLL_INTERVAL_SEC)
