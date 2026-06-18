"""Orchestrator routing tests (no LLM calls)."""

from agent.orchestrator import RouteDecision, decide_route


def test_force_team_does_not_override_edit(monkeypatch):
    monkeypatch.setattr(
        "agent.orchestrator.llm_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "agent.orchestrator._llm_route",
        lambda *args, **kwargs: RouteDecision(
            mode="edit",
            reason="Add a transition at the end.",
            ui_label="Add transition",
        ),
    )
    route = decide_route(
        "add a transition at the end",
        {"video_clip_count": 2},
        "/tmp/fake-project",
        force_team=True,
    )
    assert route.mode == "edit"


def test_force_team_when_orchestrator_picks_team(monkeypatch):
    monkeypatch.setattr("agent.orchestrator.llm_available", lambda: True)
    monkeypatch.setattr(
        "agent.orchestrator._llm_route",
        lambda *args, **kwargs: RouteDecision(
            mode="team",
            reason="Full re-edit.",
            ui_label="Team",
        ),
    )
    route = decide_route(
        "re-edit everything",
        {"video_clip_count": 12},
        "/tmp/fake-project",
        force_team=True,
    )
    assert route.mode == "team"


def test_force_team_without_parse_uses_team(monkeypatch):
    monkeypatch.setattr("agent.orchestrator.llm_available", lambda: True)
    monkeypatch.setattr("agent.orchestrator._llm_route", lambda *args, **kwargs: None)
    route = decide_route(
        "make it cinematic",
        {"video_clip_count": 4},
        "/tmp/fake-project",
        force_team=True,
    )
    assert route.mode == "team"
