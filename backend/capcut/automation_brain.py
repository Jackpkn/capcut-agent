"""Intent-driven CapCut automation — AI picks WHAT to do by purpose, not shortcut names."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from capcut.capabilities import (
    Capability,
    all_capabilities,
    capabilities_for_planner,
    capability_by_id,
    search_capabilities,
)

logger = logging.getLogger(__name__)

PLANNER_INSTRUCTIONS_DISK = """You are the CapCut Automation Brain. The user describes a GOAL in natural language.
You do NOT memorize keyboard shortcuts. You choose capabilities by their PURPOSE.

Rules:
1. Prefer layer=disk and layer=pipeline over layer=shortcut and layer=rpa (more reliable).
2. Use shortcut:* only when the goal is inherently a UI interaction (play preview, confirm dialog).
3. Use rpa:* only when disk cannot do it (CapCut AI UI, native cutout, library download).
4. For "edit everything" / "make it pro" → pipeline:full_edit or pipeline:bootstrap.
5. For captions → generate_captions (NOT rpa:auto_captions unless user insists on native CapCut).
6. Chain multiple steps when needed. Keep plans short (1–6 steps).
7. Include verify_project after substantive edits when user wants quality check.

Call plan_capcut_steps with capability ids from the catalog and params for each step."""

PLANNER_INSTRUCTIONS_UI = """You are the CapCut UI Automation Brain. The user wants CapCut controlled THROUGH THE APP UI
like a human — clicks, menus, shortcuts — NOT silent disk JSON edits.

Rules:
1. Prefer layer=ui, layer=shortcut, layer=rpa over layer=disk and layer=pipeline.
2. Use ui:<label> for discovered buttons/panels. Use rpa:search_library / download_asset for assets.
3. Use shortcut:* for timeline (split, play, save, export, transition).
4. Use rpa:auto_design, rpa:auto_captions, rpa:auto_cutout for CapCut native AI features.
5. Only use disk/pipeline if user explicitly asks for fast/background edit or UI is unavailable.
6. Chain 2–8 UI steps. Re-discover happens automatically in ui_automate loop.

Call plan_capcut_steps with capability ids — favor UI paths."""

PLANNER_INSTRUCTIONS = PLANNER_INSTRUCTIONS_DISK

PLAN_TOOL = [{
    "type": "function",
    "name": "plan_capcut_steps",
    "description": "Plan CapCut automation steps by user goal and capability purposes.",
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "One sentence — what you will accomplish",
            },
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "capability_id": {"type": "string"},
                        "params": {"type": "object"},
                        "reason": {
                            "type": "string",
                            "description": "Why this capability matches the user's goal",
                        },
                    },
                    "required": ["capability_id", "reason"],
                },
            },
        },
        "required": ["summary", "steps"],
    },
}]


@dataclass
class PlanStep:
    capability_id: str
    params: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass
class AutomationPlan:
    summary: str
    steps: list[PlanStep]
    source: str  # "llm" | "rules"


def _parse_plan(response) -> AutomationPlan | None:
    for item in response.output:
        if item.type != "function_call" or item.name != "plan_capcut_steps":
            continue
        try:
            args = json.loads(item.arguments)
        except json.JSONDecodeError:
            continue
        steps = [
            PlanStep(
                capability_id=str(s.get("capability_id", "")),
                params=dict(s.get("params") or {}),
                reason=str(s.get("reason") or ""),
            )
            for s in (args.get("steps") or [])
            if s.get("capability_id")
        ]
        if not steps:
            continue
        return AutomationPlan(
            summary=str(args.get("summary") or ""),
            steps=steps,
            source="llm",
        )
    return None


def _rule_plan(goal: str, project_path: str | None) -> AutomationPlan:
    """Offline fallback — score capabilities by intent, build a sensible chain."""
    goal_l = goal.lower()
    steps: list[PlanStep] = []

    def add(cap_id: str, params: dict | None = None, reason: str = "") -> None:
        steps.append(PlanStep(cap_id, params or {}, reason or f"Matched: {cap_id}"))

    if any(w in goal_l for w in ("bootstrap", "new project", "from clips", "import and edit")):
        add("pipeline:bootstrap", {}, "Create project from media and full edit")
    elif any(w in goal_l for w in ("full edit", "auto edit", "polish", "professional", "everything")):
        add("pipeline:full_edit", {}, "Full disk edit pipeline")
    else:
        ranked = search_capabilities(goal, limit=5)
        for r in ranked:
            if r.get("score", 0) < 2:
                continue
            add(r["id"], {}, r.get("purpose", ""))

    if any(w in goal_l for w in ("save", "persist", "store")) and not any(
        s.capability_id == "shortcut:save" for s in steps
    ):
        add("shortcut:save", {}, "Persist project to disk via CapCut")

    if any(w in goal_l for w in ("export", "render", "output")):
        add("shortcut:export", {}, "Open export dialog")

    if any(w in goal_l for w in ("verify", "check", "qa")):
        add("verify_project", {}, "QA verify timeline")

    if not steps:
        add("pipeline:full_edit", {}, "Default — full edit when intent unclear")

    return AutomationPlan(
        summary=f"Rule-based plan for: {goal[:80]}",
        steps=steps[:6],
        source="rules",
    )


def plan_automation(
    goal: str,
    project_path: str | None = None,
    *,
    timeline_summary: dict | None = None,
    ui_elements: list[dict] | None = None,
    strategy: str = "hybrid",
) -> AutomationPlan:
    """LLM plans by purpose; falls back to intent scoring."""
    from agent.runtime.model import call_model, llm_available

    goal = (goal or "").strip()
    if not goal:
        return AutomationPlan("Empty goal", [], "rules")

    strat = (strategy or "hybrid").lower()
    if strat == "ui_first":
        return _rule_plan_ui(goal)

    instructions = PLANNER_INSTRUCTIONS_UI if strat == "ui_only" else PLANNER_INSTRUCTIONS_DISK

    if llm_available():
        catalog = capabilities_for_planner(include_ui=ui_elements)
        context = {
            "goal": goal,
            "strategy": strat,
            "project_path": project_path,
            "timeline": timeline_summary or {},
            "capabilities": catalog[:80],
            "ui_discovered": (ui_elements or [])[:30],
        }
        try:
            response = call_model(
                instructions=instructions,
                input_items=[{"role": "user", "content": json.dumps(context, indent=2)}],
                tools=PLAN_TOOL,
                temperature=0.15,
                max_output_tokens=1024,
                agent="automation_brain",
            )
            if response:
                parsed = _parse_plan(response)
                if parsed and parsed.steps:
                    return parsed
        except Exception as exc:
            logger.warning("Automation brain LLM failed: %s", exc)

    if strat in ("ui_first", "ui_only"):
        return _rule_plan_ui(goal)
    return _rule_plan(goal, project_path)


def _rule_plan_ui(goal: str) -> AutomationPlan:
    """UI-first rule plan — shortcuts, RPA, discovered clicks."""
    from capcut.ui_agent import _playbook_steps

    steps = [
        PlanStep(
            f"ui_action:{s.action}:{s.target}",
            {"action": s.action, "target": s.target},
            s.reason,
        )
        for s in _playbook_steps(goal)
    ]
    if not steps:
        steps = [
            PlanStep("rpa:focus", {}, "Focus CapCut"),
            PlanStep("shortcut:search_library", {}, "Open library search"),
        ]
    return AutomationPlan(
        summary=f"UI-first plan: {goal[:80]}",
        steps=steps,
        source="ui_rules",
    )


def execute_capability(
    cap: Capability,
    params: dict[str, Any],
    project_path: str,
) -> dict[str, Any]:
    """Dispatch one capability to the right layer."""
    merged = {**cap.default_params, **params}

    if cap.layer == "shortcut":
        from capcut.shortcuts import run_shortcut

        name = merged.get("shortcut_name") or cap.id.removeprefix("shortcut:")
        return run_shortcut(name, repeat=int(merged.get("repeat", 1)))

    if cap.layer == "rpa":
        from capcut.rpa import execute_rpa

        return execute_rpa(
            merged.get("rpa_action", ""),
            project_path,
            clip_name=str(merged.get("clip_name", "")),
            output_path=merged.get("output_path"),
            shortcut_name=str(merged.get("shortcut_name", "")),
            query=str(merged.get("query", "")),
            asset_type=str(merged.get("asset_type", "music")),
            item_name=str(merged.get("item_name", "")),
            from_home=bool(merged.get("from_home", True)),
        )

    if cap.layer == "pipeline":
        if cap.action == "run_edit_pipeline":
            from capcut.pipeline import run_edit_pipeline

            return run_edit_pipeline(project_path, **{k: v for k, v in merged.items() if k != "media_paths"})
        if cap.action == "bootstrap_and_edit":
            from capcut.pipeline import bootstrap_and_edit

            paths = merged.get("media_paths") or []
            if not paths:
                return {"success": False, "error": "media_paths required for bootstrap"}
            return bootstrap_and_edit(paths, **{k: v for k, v in merged.items() if k != "media_paths"})

    if cap.layer == "ui" or cap.id.startswith("ui:"):
        from capcut.ui_discover import click_ui_element

        label = merged.get("label") or cap.id.removeprefix("ui:")
        return click_ui_element(label)

    if cap.id.startswith("ui_action:"):
        from capcut.ui_agent import UiStep, execute_ui_action

        parts = cap.id.split(":", 3)
        action = parts[1] if len(parts) > 1 else merged.get("action", "click")
        target = parts[2] if len(parts) > 2 else merged.get("target", "")
        return execute_ui_action(UiStep(action, target), merged.get("labels") or [])

    if cap.layer == "disk" or cap.layer == "script":
        from agent.actions import execute_action

        detail = execute_action(cap.action, merged, project_path)
        return {"success": True, "detail": detail, "action": cap.action}

    return {"success": False, "error": f"Unknown layer {cap.layer}"}


def execute_plan(
    plan: AutomationPlan,
    project_path: str,
) -> dict[str, Any]:
    """Run each planned step; collect results."""
    results: list[dict[str, Any]] = []
    for i, step in enumerate(plan.steps):
        cap = capability_by_id(step.capability_id)
        if not cap and step.capability_id.startswith("ui:"):
            cap = Capability(
                id=step.capability_id,
                layer="ui",
                purpose=f"Click {step.capability_id}",
                intents=[],
                mechanism="ui click",
                action="ui_click",
                default_params={"label": step.capability_id.removeprefix("ui:")},
            )
        if not cap:
            results.append({
                "step": i + 1,
                "capability_id": step.capability_id,
                "ok": False,
                "error": "unknown capability",
                "reason": step.reason,
            })
            continue

        try:
            out = execute_capability(cap, step.params, project_path)
            ok = out.get("success", True) if isinstance(out, dict) else True
            results.append({
                "step": i + 1,
                "capability_id": step.capability_id,
                "purpose": cap.purpose,
                "reason": step.reason,
                "ok": ok,
                "result": out,
            })
        except Exception as exc:
            logger.warning("Step %s failed: %s", step.capability_id, exc)
            results.append({
                "step": i + 1,
                "capability_id": step.capability_id,
                "ok": False,
                "error": str(exc),
                "reason": step.reason,
            })

    failed = [r for r in results if not r.get("ok")]
    return {
        "success": len(failed) == 0,
        "summary": plan.summary,
        "plan_source": plan.source,
        "steps_executed": len(results),
        "failed": len(failed),
        "results": results,
    }


def automate(
    goal: str,
    project_path: str,
    *,
    discover_ui: bool = True,
    media_paths: list[str] | None = None,
    strategy: str = "hybrid",
) -> dict[str, Any]:
    """
    End-to-end automation.

    strategy:
      - ui_first: drive CapCut UI loop (clicks/menus/shortcuts) — your 101% path
      - ui_only: plan UI capabilities only
      - hybrid: disk when reliable, UI when needed (default)
      - disk: legacy disk-first pipeline
    """
    if (strategy or "hybrid").lower() in ("ui_first", "ui"):
        from capcut.ui_agent import ui_automate

        ui_result = ui_automate(goal, project_path, max_steps=14)
        return {
            "goal": goal,
            "project_path": project_path,
            "strategy": "ui_first",
            "ui_automation": ui_result,
        }

    from capcut.reader import get_project_summary
    from capcut.ui_discover import discover_capcut_ui

    ui_data = discover_capcut_ui() if discover_ui else {"elements": []}
    ui_elements = ui_data.get("elements") or []
    summary = get_project_summary(project_path)

    plan = plan_automation(
        goal,
        project_path,
        timeline_summary=summary,
        ui_elements=ui_elements,
        strategy=strategy,
    )

    # Inject media_paths into bootstrap step if provided
    if media_paths:
        for step in plan.steps:
            if step.capability_id == "pipeline:bootstrap":
                step.params["media_paths"] = media_paths

    execution = execute_plan(plan, project_path)
    return {
        "goal": goal,
        "project_path": project_path,
        "strategy": strategy,
        "ui_discovered": ui_data.get("count", 0),
        "plan": {
            "summary": plan.summary,
            "source": plan.source,
            "steps": [
                {"capability_id": s.capability_id, "reason": s.reason, "params": s.params}
                for s in plan.steps
            ],
        },
        "execution": execution,
        "timeline_after": get_project_summary(project_path),
    }
