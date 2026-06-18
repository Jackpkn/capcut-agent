"""CapCut UI handoff — close project in-app, write disk, reopen (no full quit)."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

HOME_SCRIPT = r'''
tell application "CapCut" to activate
delay 0.6
tell application "System Events"
    tell process "CapCut"
        set frontmost to true
        delay 0.2
        -- CapCut 8.x: reliable menu item (toolbar "Home" is often not in the AX tree)
        try
            click menu bar item "CapCut" of menu bar 1
            delay 0.15
            click menu item "Back to home page" of menu "CapCut" of menu bar item "CapCut" of menu bar 1
            return "menu_ok"
        on error menuErr
            -- Fallback: Escape + visible Home/back controls
            repeat 3 times
                key code 53
                delay 0.3
            end repeat
            repeat with w in windows
                repeat with btn in buttons of w
                    try
                        set n to name of btn
                        if n contains "home" or n contains "back" then
                            click btn
                            return "btn_ok"
                        end if
                    end try
                end repeat
            end repeat
            return "fallback_failed: " & menuErr
        end try
    end tell
end tell
'''

OPEN_DRAFT_SCRIPT = r'''
on run argv
    set draftName to item 1 of argv
    tell application "CapCut" to activate
    delay 0.8
    tell application "System Events"
        tell process "CapCut"
            set frontmost to true
            set clicked to false
            repeat with w in windows
                repeat with txtElem in static texts of w
                    try
                        set n to name of txtElem
                        if n contains draftName then
                            click txtElem
                            set clicked to true
                            exit repeat
                        end if
                    end try
                end repeat
                if clicked then exit repeat
                repeat with grp in groups of w
                    repeat with txtElem in static texts of grp
                        try
                            set n to name of txtElem
                            if n contains draftName then
                                click txtElem
                                set clicked to true
                                exit repeat
                            end if
                        end try
                    end repeat
                    if clicked then exit repeat
                end repeat
            end repeat
            if clicked then
                return "opened"
            end if
        end tell
    end tell
    return "not_found"
end run
'''


def draft_name_from_path(project_path: str) -> str:
    meta = Path(project_path) / "draft_meta_info.json"
    if meta.exists():
        try:
            data = json.loads(meta.read_text())
            name = data.get("draft_name")
            if name:
                return str(name)
        except (json.JSONDecodeError, OSError):
            pass
    return Path(project_path).name


def is_project_locked(project_path: str) -> bool:
    return (Path(project_path) / ".locked").exists()


def _run_osascript(script: str, *args: str, timeout: float = 15) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["osascript", "-e", script, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (result.stdout or "").strip()
        if result.returncode != 0:
            logger.warning("osascript failed: %s", result.stderr)
            return False, out
        return True, out
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("osascript error: %s", e)
        return False, ""


def accessibility_enabled() -> bool:
    from capcut.accessibility import ui_automation_enabled

    return ui_automation_enabled()


def navigate_to_home() -> bool:
    if not accessibility_enabled():
        logger.warning("Accessibility disabled — cannot drive CapCut UI")
        return False
    ok, out = _run_osascript(HOME_SCRIPT)
    logger.info("navigate_to_home: ok=%s out=%s", ok, out)
    return ok


def open_draft_by_name(draft_name: str) -> bool:
    ok, out = _run_osascript(OPEN_DRAFT_SCRIPT, draft_name)
    logger.info("open_draft_by_name(%s): ok=%s out=%s", draft_name, ok, out)
    return ok and out == "opened"


def wait_until_unlocked(project_path: str, timeout_sec: float = 20) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if not is_project_locked(project_path):
            return True
        time.sleep(0.35)
    return not is_project_locked(project_path)


def prepare_project_for_write(project_path: str) -> bool:
    """Close the open project inside CapCut so draft files unlock (app may stay open)."""
    if not is_project_locked(project_path):
        logger.info("Project already unlocked: %s", project_path)
        return True

    logger.info("Project locked — navigating CapCut to Home…")
    navigate_to_home()
    if wait_until_unlocked(project_path):
        logger.info("Project unlocked on disk")
        return True

    if not accessibility_enabled():
        logger.warning("Project still locked — grant Accessibility to the app running uvicorn (Terminal or Cursor)")
    else:
        logger.warning("Project still locked after UI home navigation — click Home in CapCut manually")
    return False


def reopen_project(project_path: str) -> bool:
    name = draft_name_from_path(project_path)
    time.sleep(0.5)
    return open_draft_by_name(name)


def apply_with_ui_handoff(project_path: str, apply_fn) -> tuple[list[str], str]:
    """
    Close project in CapCut UI → run apply_fn() → reopen project.
    apply_fn should write draft_info and return result strings.
    """
    mode = "direct"
    if is_project_locked(project_path):
        mode = "ui_handoff"
        if not prepare_project_for_write(project_path):
            raise RuntimeError(
                "Could not unlock the project. Click Home in CapCut (top-left), "
                "or grant Accessibility permission to Terminal/Cursor."
            )

    results = apply_fn()
    time.sleep(0.8)

    if mode == "ui_handoff":
        if reopen_project(project_path):
            suffix = "\n\nProject reopened in CapCut with your edits."
        else:
            suffix = f"\n\nEdits saved. Open project **{draft_name_from_path(project_path)}** in CapCut."
    else:
        suffix = "\n\nEdits saved to disk."

    return results, suffix


def capcut_sync_hint(project_path: str, *, reopened: bool) -> str:
    """Short UX note after apply — shown in execute SSE and API replies."""
    name = draft_name_from_path(project_path)
    if reopened:
        return (
            "Project reopened in CapCut with your edits. Scrub the timeline — "
            "captions sit at the bottom in white. If anything looks missing, tap Home and reopen once."
        )
    return f"Edits saved on disk. From CapCut Home, open **{name}** to review."
