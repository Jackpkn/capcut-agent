"""Tests for UI-first automation."""

from capcut.ui_agent import UI_PLAYBOOK, _playbook_steps, execute_ui_action, UiStep


def test_playbook_captions():
    steps = _playbook_steps("add subtitles and captions")
    assert any(s.action == "menu" and "caption" in s.target.lower() for s in steps)


def test_playbook_export():
    steps = _playbook_steps("export the final video")
    assert any(s.action == "shortcut" and s.target == "export" for s in steps)


def test_playbook_save():
    steps = _playbook_steps("save my project")
    assert any(s.target == "save" for s in steps)


def test_playbook_has_entries():
    assert len(UI_PLAYBOOK) >= 8


def test_execute_done_action():
    out = execute_ui_action(UiStep("done", "", "finished"), [])
    assert out.get("success") is True
