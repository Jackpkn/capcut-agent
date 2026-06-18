"""Unified apply path — CapCut handoff, ledger, episodic memory, sync hints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApplyOutcome:
    results: list[str]
    reply: str
    sync_hint: str
    reopened: bool


def record_apply_outcome(
    project_path: str,
    actions: list[dict],
    *,
    record_ledger: bool = True,
    record_episodic: bool = True,
) -> None:
    from core.episodic_memory import record_approval
    from core.project_ledger import record_applied_edits

    if record_ledger:
        record_applied_edits(project_path, actions)
    if record_episodic:
        record_approval(project_path, actions)


def build_apply_reply(
    project_path: str,
    results: list[str],
    *,
    reopened: bool,
    extra_lines: list[str] | None = None,
) -> tuple[str, str]:
    from agent.brain import format_execute_reply
    from capcut.project_ui import capcut_sync_hint

    sync_hint = capcut_sync_hint(project_path, reopened=reopened)
    reply = format_execute_reply(results) + f"\n\n{sync_hint}"
    for line in extra_lines or []:
        if line and line not in reply:
            reply += f"\n\n{line}"
    return reply, sync_hint


def apply_edits_immediate(project_path: str, actions: list[dict]) -> ApplyOutcome:
    """Close CapCut if needed → execute → ledger → episodic → CDP sync → reopen."""
    from agent.actions import execute_actions
    from capcut.cdp import sync_capcut
    from capcut.project_ui import apply_with_ui_handoff, reopen_project
    from core.task_deps import order_action_dicts

    actions = order_action_dicts(actions)

    results, _suffix, reopened = apply_with_ui_handoff(
        project_path,
        lambda: execute_actions(actions, project_path),
    )
    record_apply_outcome(project_path, actions)
    sync_capcut(project_path)
    if not reopened:
        reopened = reopen_project(project_path)
    reply, sync_hint = build_apply_reply(project_path, results, reopened=reopened)
    return ApplyOutcome(results=results, reply=reply, sync_hint=sync_hint, reopened=reopened)


def finalize_stream_apply(
    project_path: str,
    actions: list[dict],
    results: list[str],
    *,
    reopened: bool,
    extra_lines: list[str] | None = None,
    record_ledger: bool = True,
    record_episodic: bool = True,
) -> ApplyOutcome:
    """Bookkeeping after SSE apply steps already wrote to disk."""
    from capcut.cdp import sync_capcut

    record_apply_outcome(
        project_path,
        actions,
        record_ledger=record_ledger,
        record_episodic=record_episodic,
    )
    sync_capcut(project_path)
    reply, sync_hint = build_apply_reply(
        project_path,
        results,
        reopened=reopened,
        extra_lines=extra_lines,
    )
    return ApplyOutcome(results=results, reply=reply, sync_hint=sync_hint, reopened=reopened)
