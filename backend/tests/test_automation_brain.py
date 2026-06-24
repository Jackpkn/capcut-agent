"""Tests for intent-driven automation."""

from capcut.capabilities import (
    all_capabilities,
    capability_by_id,
    score_capability,
    search_capabilities,
)
from capcut.automation_brain import _rule_plan, execute_plan, AutomationPlan, PlanStep


def test_capability_registry_has_layers():
    caps = all_capabilities()
    layers = {c.layer for c in caps}
    assert "disk" in layers
    assert "shortcut" in layers
    assert "pipeline" in layers
    ids = {c.id for c in caps}
    assert "shortcut:save" in ids
    assert "pipeline:full_edit" in ids


def test_save_matched_by_intent_not_name():
    results = search_capabilities("persist my project so I don't lose edits")
    top_ids = [r["id"] for r in results[:3]]
    assert "shortcut:save" in top_ids


def test_captions_prefers_disk_over_rpa():
    results = search_capabilities("add subtitles from speech")
    top_ids = [r["id"] for r in results[:3]]
    assert "generate_captions" in top_ids


def test_rule_plan_full_edit():
    plan = _rule_plan("make a professional full auto edit", "/fake")
    assert any(s.capability_id == "pipeline:full_edit" for s in plan.steps)


def test_execute_plan_unknown_step():
    plan = AutomationPlan("test", [PlanStep("not_real_id")], "rules")
    out = execute_plan(plan, "/fake")
    assert out["failed"] == 1


def test_shortcut_capability_has_purpose():
    cap = capability_by_id("shortcut:save")
    assert cap is not None
    assert "persist" in cap.purpose.lower() or "disk" in cap.purpose.lower()
    assert score_capability(cap, "save my work") > 0
