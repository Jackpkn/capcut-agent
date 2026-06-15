"""Persist edit ledger per CapCut project — survives restarts and single/team sessions."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from core.edit_ledger import EditLedger
from core.models import EditSession
from core.session_memory import SessionMemory
from core.task_queue import update_session

logger = logging.getLogger(__name__)

LEDGER_ROOT = Path.home() / ".capcut-agent" / "ledgers"


def _ledger_path(project_path: str) -> Path:
    key = hashlib.sha256(project_path.encode()).hexdigest()[:24]
    return LEDGER_ROOT / f"{key}.json"


def load_ledger(project_path: str) -> EditLedger:
    path = _ledger_path(project_path)
    if not path.is_file():
        return EditLedger()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return EditLedger.from_dict(data)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read ledger for %s: %s", project_path, exc)
        return EditLedger()


def save_ledger(project_path: str, ledger: EditLedger) -> None:
    LEDGER_ROOT.mkdir(parents=True, exist_ok=True)
    path = _ledger_path(project_path)
    payload = ledger.to_dict()
    payload["_meta"] = {"project_path": project_path}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _at_sec_from_action(item: dict) -> float | None:
    if item.get("at_sec") is not None:
        try:
            return float(item["at_sec"])
        except (TypeError, ValueError):
            pass
    params = item.get("params") or {}
    for key in ("at_sec", "start_sec", "time_sec", "position_sec"):
        if key in params:
            try:
                return float(params[key])
            except (TypeError, ValueError):
                continue
    return None


def _recent_descriptions(ledger: EditLedger, *, window: int = 30) -> set[str]:
    return {e.get("description", "") for e in ledger.entries[-window:]}


def record_proposed_edits(project_path: str, actions: list[dict]) -> EditLedger:
    """Log agent proposals so later calls do not repeat blindly."""
    if not project_path or not actions:
        return load_ledger(project_path)

    ledger = load_ledger(project_path)
    recent = _recent_descriptions(ledger)
    for item in actions:
        desc = (item.get("description") or item.get("action") or "").strip()
        if not desc or desc in recent:
            continue
        ledger.record(
            action=item.get("action", ""),
            description=desc,
            chapter_id=item.get("chapter_id", ""),
            segment_id=item.get("segment_id", ""),
            at_sec=_at_sec_from_action(item),
            status="proposed",
        )
        recent.add(desc)
    save_ledger(project_path, ledger)
    return ledger


def record_applied_edits(project_path: str, actions: list[dict]) -> EditLedger:
    """Mark proposals as applied and append any new applied entries."""
    if not project_path or not actions:
        return load_ledger(project_path)

    ledger = load_ledger(project_path)
    descriptions: list[str] = []
    for item in actions:
        desc = (item.get("description") or item.get("action") or "").strip()
        if desc:
            descriptions.append(desc)

    ledger.mark_applied(descriptions)

    applied_descs = {
        e.get("description")
        for e in ledger.entries
        if e.get("status") == "applied"
    }
    for item in actions:
        desc = (item.get("description") or item.get("action") or "").strip()
        if not desc or desc in applied_descs:
            continue
        ledger.record(
            action=item.get("action", ""),
            description=desc,
            chapter_id=item.get("chapter_id", ""),
            segment_id=item.get("segment_id", ""),
            at_sec=_at_sec_from_action(item),
            status="applied",
        )
        applied_descs.add(desc)

    save_ledger(project_path, ledger)
    logger.info("Recorded %d applied edit(s) for project ledger", len(actions))
    return ledger


def hydrate_session_memory(project_path: str, memory_dict: dict | None) -> dict:
    """Load persisted ledger into an in-memory session snapshot."""
    memory = SessionMemory.from_dict(memory_dict)
    memory.edit_ledger = load_ledger(project_path)
    memory.completed_edits = [
        {
            "chapter_id": e.get("chapter_id", ""),
            "action": e.get("action", ""),
            "description": e.get("description", ""),
            "at_sec": e.get("at_sec"),
            "status": "applied",
        }
        for e in memory.edit_ledger.entries
        if e.get("status") == "applied"
    ][-50:]
    return memory.to_dict()


def sync_session_ledger(session: EditSession) -> None:
    """Refresh session memory from disk after apply."""
    session.session_memory = hydrate_session_memory(
        session.project_path,
        session.session_memory,
    )
    update_session(session)


def record_applied_for_session(session: EditSession, actions: list[dict]) -> None:
    """Persist applied edits to disk and sync live team session memory."""
    record_applied_edits(session.project_path, actions)
    sync_session_ledger(session)
