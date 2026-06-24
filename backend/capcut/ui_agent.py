"""UI-first CapCut automation — drive the app like a human, step by step.

Loop: discover visible UI → LLM picks next action → execute → re-discover → repeat.
This is the path to near-100% CapCut coverage (every feature CapCut exposes in UI).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from capcut.ui_discover import click_ui_element, discover_capcut_ui, run_menu_path, type_text

logger = logging.getLogger(__name__)

UiActionType = Literal["click", "shortcut", "menu", "type_text", "wait", "done"]

UI_AGENT_INSTRUCTIONS = """You are a CapCut UI automation agent. You control CapCut ONLY through its desktop UI
(clicks, menus, keyboard shortcuts, typing) — like a human editor.

Each turn you see:
- The user's GOAL
- Currently VISIBLE UI elements (buttons, menus, labels) — use these for clicks
- Steps already taken

Pick ONE next action. Prefer:
1. Menu paths when you know the feature location (Text → Auto captions, Video → Filters)
2. Clicks on discovered labels that match the goal
3. Shortcuts for timeline ops (split, play_pause, save, export, undo)
4. type_text for search boxes after focusing library (Cmd+F)

When the goal is achieved or no safe next step exists, action=done.

Do NOT invent UI labels — only click labels from the discovered list or standard CapCut menus."""

UI_STEP_TOOL = [{
    "type": "function",
    "name": "ui_next_step",
    "description": "Next UI action toward the user's goal in CapCut.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["click", "shortcut", "menu", "type_text", "wait", "done"],
            },
            "target": {
                "type": "string",
                "description": "Label to click, shortcut name, menu path (a>b>c), or text to type",
            },
            "reason": {"type": "string"},
            "done_summary": {
                "type": "string",
                "description": "When action=done — what was accomplished",
            },
        },
        "required": ["action", "reason"],
    },
}]


@dataclass
class UiStep:
    action: UiActionType
    target: str = ""
    reason: str = ""
    result: dict[str, Any] = field(default_factory=dict)


# Known CapCut menu paths for common goals (UI-native, not disk)
UI_PLAYBOOK: list[dict[str, Any]] = [
    {
        "goal_intents": ["caption", "subtitle", "transcribe"],
        "steps": [
            {"action": "menu", "target": "Text>Auto captions", "reason": "Open native auto captions"},
        ],
    },
    {
        "goal_intents": ["filter", "color", "cinematic", "grade"],
        "steps": [
            {"action": "click", "target": "Filters", "reason": "Open filters panel"},
        ],
    },
    {
        "goal_intents": ["music", "audio", "soundtrack"],
        "steps": [
            {"action": "click", "target": "Music", "reason": "Open music library"},
            {"action": "shortcut", "target": "search_library", "reason": "Focus search"},
        ],
    },
    {
        "goal_intents": ["effect", "visual effect"],
        "steps": [
            {"action": "click", "target": "Effects", "reason": "Open effects panel"},
        ],
    },
    {
        "goal_intents": ["export", "render", "output"],
        "steps": [
            {"action": "shortcut", "target": "export", "reason": "Open export dialog"},
            {"action": "shortcut", "target": "confirm", "reason": "Confirm export"},
        ],
    },
    {
        "goal_intents": ["save", "persist"],
        "steps": [
            {"action": "shortcut", "target": "save", "reason": "Save project"},
        ],
    },
    {
        "goal_intents": ["auto design", "autocut", "smart template", "ai edit"],
        "steps": [
            {"action": "menu", "target": "CapCut>Back to home page", "reason": "Go to home for AI templates"},
        ],
    },
    {
        "goal_intents": ["cutout", "remove background"],
        "steps": [
            {"action": "menu", "target": "Video>Cutout", "reason": "Open cutout panel"},
        ],
    },
    {
        "goal_intents": ["transition"],
        "steps": [
            {"action": "shortcut", "target": "default_transition", "reason": "Apply default transition"},
        ],
    },
    {
        "goal_intents": ["split", "cut clip"],
        "steps": [
            {"action": "shortcut", "target": "split", "reason": "Split at playhead"},
        ],
    },
]


def _parse_ui_step(response) -> dict[str, Any] | None:
    for item in response.output:
        if item.type != "function_call" or item.name != "ui_next_step":
            continue
        try:
            return json.loads(item.arguments)
        except json.JSONDecodeError:
            continue
    return None


def _playbook_steps(goal: str) -> list[UiStep]:
    """Rule-based UI playbook when LLM offline."""
    goal_l = goal.lower()
    steps: list[UiStep] = []
    for play in UI_PLAYBOOK:
        if any(intent in goal_l for intent in play["goal_intents"]):
            for s in play["steps"]:
                steps.append(UiStep(s["action"], s.get("target", ""), s.get("reason", "")))
    if not steps and any(w in goal_l for w in ("edit", "automate", "everything")):
        steps = [
            UiStep("shortcut", "play_pause", "Preview timeline"),
            UiStep("click", "Text", "Open text panel"),
            UiStep("shortcut", "save", "Save work"),
        ]
    return steps[:8]


def execute_ui_action(step: UiStep, discovered_labels: list[str]) -> dict[str, Any]:
    """Run one UI action."""
    action = step.action
    target = (step.target or "").strip()

    if action == "done":
        return {"success": True, "action": "done", "detail": target or "complete"}

    if action == "wait":
        time.sleep(min(float(target or 1.0), 5.0))
        return {"success": True, "action": "wait", "detail": f"slept {target}s"}

    if action == "shortcut":
        from capcut.shortcuts import run_shortcut

        return run_shortcut(target)

    if action == "menu":
        parts = [p.strip() for p in target.replace(">", "/").split("/") if p.strip()]
        if len(parts) < 2:
            parts = [p.strip() for p in target.split(">") if p.strip()]
        return run_menu_path(parts)

    if action == "type_text":
        return type_text(target)

    if action == "click":
        # Fuzzy match against discovered labels
        label = target
        if discovered_labels:
            lower = target.lower()
            for d in discovered_labels:
                if lower in d.lower() or d.lower() in lower:
                    label = d
                    break
        return click_ui_element(label)

    return {"success": False, "error": f"unknown action {action}"}


def _llm_next_step(
    goal: str,
    ui_elements: list[dict],
    history: list[UiStep],
) -> dict[str, Any] | None:
    from agent.runtime.model import call_model, llm_available

    if not llm_available():
        return None

    labels = [e.get("label", "") for e in ui_elements[:40]]
    context = {
        "goal": goal,
        "visible_ui": ui_elements[:40],
        "visible_labels": labels,
        "steps_done": [
            {"action": s.action, "target": s.target, "reason": s.reason, "ok": s.result.get("success")}
            for s in history
        ],
        "known_shortcuts": [
            "save", "export", "undo", "split", "play_pause", "default_transition",
            "search_library", "confirm",
        ],
    }
    try:
        response = call_model(
            instructions=UI_AGENT_INSTRUCTIONS,
            input_items=[{"role": "user", "content": json.dumps(context, indent=2)}],
            tools=UI_STEP_TOOL,
            temperature=0.1,
            max_output_tokens=512,
            agent="ui_agent",
        )
        if response:
            return _parse_ui_step(response)
    except Exception as exc:
        logger.warning("UI agent LLM step failed: %s", exc)
    return None


def ui_automate(
    goal: str,
    project_path: str | None = None,
    *,
    max_steps: int = 12,
    rediscover_each_step: bool = True,
) -> dict[str, Any]:
    """
    UI-first automation loop — discover → act → re-discover until goal done.

    This drives CapCut like a human. Use for 100% UI-native coverage.
    """
    from capcut.rpa import rpa_focus
    from capcut.project_ui import reopen_project

    goal = (goal or "").strip()
    if not goal:
        return {"success": False, "error": "goal is required"}

    focus = rpa_focus()
    if project_path:
        reopen_project(project_path)

    history: list[UiStep] = []
    playbook = _playbook_steps(goal)
    playbook_idx = 0
    done_summary = ""
    labels: list[str] = []

    for step_num in range(max_steps):
        ui_data = discover_capcut_ui(max_items=100)
        elements = ui_data.get("elements") or []
        labels = [e["label"] for e in elements if e.get("label")]

        # Playbook first (fast path), then LLM
        if playbook_idx < len(playbook):
            step = playbook[playbook_idx]
            playbook_idx += 1
        else:
            llm_step = _llm_next_step(goal, elements, history)
            if llm_step:
                if llm_step.get("action") == "done":
                    done_summary = llm_step.get("done_summary") or llm_step.get("reason", "")
                    history.append(UiStep("done", "", done_summary, {"success": True}))
                    break
                step = UiStep(
                    llm_step.get("action", "click"),
                    str(llm_step.get("target", "")),
                    str(llm_step.get("reason", "")),
                )
            elif step_num == 0 and playbook:
                continue
            else:
                break

        result = execute_ui_action(step, labels)
        step.result = result
        history.append(step)

        if not rediscover_each_step:
            time.sleep(0.4)
        if step.action == "done":
            break
        if not result.get("success") and step.action == "click":
            # Retry LLM on next iteration instead of playbook
            playbook_idx = len(playbook)

    success = any(s.action == "done" for s in history) or sum(
        1 for s in history if s.result.get("success")
    ) >= max(1, len(history) // 2)

    return {
        "success": success,
        "strategy": "ui_first",
        "goal": goal,
        "project_path": project_path,
        "steps": [
            {
                "action": s.action,
                "target": s.target,
                "reason": s.reason,
                "ok": s.result.get("success", False),
                "detail": s.result.get("detail") or s.result.get("error"),
            }
            for s in history
        ],
        "done_summary": done_summary or (history[-1].reason if history else ""),
        "ui_elements_seen": len(labels) if history else 0,
        "focus": focus,
    }
