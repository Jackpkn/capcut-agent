"""Discover what CapCut currently exposes in its UI — dynamic, not hardcoded."""

from __future__ import annotations

import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

DISCOVER_SCRIPT = r'''
tell application "System Events"
    tell process "CapCut"
        set targetWindow to missing value
        repeat with w in windows
            if name of w contains "CapCut" then
                set targetWindow to w
                exit repeat
            end if
        end repeat
        if targetWindow is missing value then return "[]"

        set found to {}
        -- Static text labels (panels, library items, tabs)
        repeat with txtElem in static texts of targetWindow
            try
                set n to name of txtElem
                if n is not "" and n is not "missing value" then
                    set end of found to "text:" & n
                end if
            end try
        end repeat
        -- Buttons
        repeat with btn in buttons of targetWindow
            try
                set n to name of btn
                if n is not "" and n is not "missing value" then
                    set end of found to "button:" & n
                end if
            end try
        end repeat
        -- Menu bar items
        try
            repeat with mi in menu bar items of menu bar 1
                try
                    set n to name of mi
                    if n is not "" then set end of found to "menu:" & n
                end try
            end repeat
        end try
        return found
    end tell
end tell
'''


def _parse_applescript_list(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw or raw == "[]":
        return []
    if raw.startswith("{") and raw.endswith("}"):
        inner = raw[1:-1]
        return [x.strip().strip('"') for x in inner.split(",") if x.strip()]
    return [ln.strip() for ln in raw.split(",") if ln.strip()]


def discover_capcut_ui(*, max_items: int = 80) -> dict[str, Any]:
    """Scan CapCut accessibility tree for clickable / visible features."""
    from capcut.accessibility import accessibility_status

    ax = accessibility_status()
    if not ax.get("granted"):
        return {
            "success": False,
            "error": "accessibility_disabled",
            "hint": ax.get("hint"),
            "elements": [],
        }

    try:
        proc = subprocess.run(
            ["osascript", "-e", DISCOVER_SCRIPT],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timeout", "elements": []}
    except Exception as exc:
        return {"success": False, "error": str(exc), "elements": []}

    if proc.returncode != 0:
        return {
            "success": False,
            "error": (proc.stderr or proc.stdout or "discover failed").strip(),
            "elements": [],
        }

    raw_items = _parse_applescript_list(proc.stdout)
    elements: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_items:
        if ":" not in item:
            continue
        kind, label = item.split(":", 1)
        label = label.strip()
        if not label or label in seen:
            continue
        seen.add(label)
        elements.append({"kind": kind, "label": label, "id": f"ui:{label[:64]}"})
        if len(elements) >= max_items:
            break

    return {
        "success": True,
        "count": len(elements),
        "elements": elements,
        "hint": "Pass elements to capcut_automate — planner can click ui:<label> when no disk action fits.",
    }


def click_ui_element(label: str) -> dict[str, Any]:
    """Best-effort click on a discovered label in CapCut."""
    from capcut.accessibility import accessibility_status

    ax = accessibility_status()
    if not ax.get("granted"):
        return {"success": False, "error": "accessibility_disabled", "hint": ax.get("hint")}

    safe = label.replace('"', '\\"')[:80]
    script = f'''
tell application "CapCut" to activate
delay 0.5
tell application "System Events"
    tell process "CapCut"
        set frontmost to true
        set needle to "{safe}"
        repeat with w in windows
            repeat with txtElem in static texts of w
                try
                    if name of txtElem contains needle then
                        click txtElem
                        return "clicked_text"
                    end if
                end try
            end repeat
            repeat with btn in buttons of w
                try
                    if name of btn contains needle then
                        click btn
                        return "clicked_button"
                    end if
                end try
            end repeat
        end repeat
        return "not_found"
    end tell
end tell
'''
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=20)
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    detail = (proc.stdout or "").strip()
    ok = proc.returncode == 0 and detail in ("clicked_text", "clicked_button")
    return {
        "success": ok,
        "detail": detail,
        "label": label,
        "error": None if ok else (detail or proc.stderr or "click failed"),
    }


def run_menu_path(path: list[str]) -> dict[str, Any]:
    """Navigate menu bar: path like ['Text', 'Auto captions'] or ['CapCut', 'Back to home page']."""
    from capcut.accessibility import accessibility_status

    ax = accessibility_status()
    if not ax.get("granted"):
        return {"success": False, "error": "accessibility_disabled", "hint": ax.get("hint")}

    if len(path) < 1:
        return {"success": False, "error": "menu path empty"}

    safe_parts = [p.replace('"', '\\"')[:60] for p in path]
    lines = [
        'tell application "CapCut" to activate',
        "delay 0.6",
        'tell application "System Events"',
        '    tell process "CapCut"',
        "        set frontmost to true",
        "        delay 0.3",
    ]
    top = safe_parts[0]
    lines.append(f'        click menu bar item "{top}" of menu bar 1')
    lines.append("        delay 0.25")
    if len(safe_parts) == 1:
        lines.append('        return "menu_top"')
    else:
        parent = f'menu bar item "{top}" of menu bar 1'
        menu_ref = f'menu "{top}" of {parent}'
        for i, item in enumerate(safe_parts[1:]):
            lines.append(f'        click menu item "{item}" of {menu_ref}')
            lines.append("        delay 0.3")
            if i < len(safe_parts) - 2:
                menu_ref = (
                    f'menu "{item}" of menu item "{item}" of {menu_ref}'
                )
        lines.append('        return "menu_ok"')
    lines.extend(["    end tell", "end tell"])

    script = "\n".join(lines)
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=25)
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    detail = (proc.stdout or "").strip()
    ok = proc.returncode == 0 and detail in ("menu_ok", "menu_top")
    return {
        "success": ok,
        "detail": detail,
        "path": path,
        "error": None if ok else (proc.stderr or detail or "menu failed"),
    }


def type_text(text: str, *, submit: bool = False) -> dict[str, Any]:
    """Type into the focused CapCut text field."""
    from capcut.accessibility import accessibility_status

    ax = accessibility_status()
    if not ax.get("granted"):
        return {"success": False, "error": "accessibility_disabled", "hint": ax.get("hint")}

    safe = text.replace("\\", "\\\\").replace('"', '\\"')[:200]
    submit_line = "\n            keystroke return" if submit else ""
    script = f'''
tell application "CapCut" to activate
delay 0.3
tell application "System Events"
    tell process "CapCut"
        set frontmost to true
        keystroke "{safe}"{submit_line}
        return "typed"
    end tell
end tell
'''
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    ok = proc.returncode == 0 and "typed" in (proc.stdout or "")
    return {"success": ok, "detail": proc.stdout.strip(), "text": text[:50]}
