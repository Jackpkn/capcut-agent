"""CapCut desktop keyboard shortcuts — drive via MCP / RPA (macOS)."""

from __future__ import annotations

import subprocess
from typing import Any

# Names → (keys, description). Keys: list of (char, modifiers).
# Modifiers: command, shift, option, control
CAPCUT_SHORTCUTS: dict[str, dict[str, Any]] = {
    # File
    "new_project": {"keys": [("n", ["command"])], "desc": "New project"},
    "open_project": {"keys": [("o", ["command"])], "desc": "Open project"},
    "save": {"keys": [("s", ["command"])], "desc": "Save project"},
    "save_as": {"keys": [("s", ["command", "shift"])], "desc": "Save as"},
    "export": {"keys": [("e", ["command"])], "desc": "Open export dialog"},
    # Edit
    "undo": {"keys": [("z", ["command"])], "desc": "Undo"},
    "redo": {"keys": [("z", ["command", "shift"])], "desc": "Redo"},
    "copy": {"keys": [("c", ["command"])], "desc": "Copy"},
    "cut": {"keys": [("x", ["command"])], "desc": "Cut"},
    "paste": {"keys": [("v", ["command"])], "desc": "Paste"},
    "duplicate": {"keys": [("d", ["command"])], "desc": "Duplicate clip"},
    "delete": {"keys": [("\u0003", [])], "desc": "Delete (forward delete key)"},
    "backspace_delete": {"keys": [("\b", [])], "desc": "Delete (backspace)"},
    # Playback
    "play_pause": {"keys": [(" ", [])], "desc": "Play / pause"},
    "play_forward": {"keys": [("l", [])], "desc": "Play forward (J/K/L)"},
    "play_backward": {"keys": [("j", [])], "desc": "Play backward"},
    "stop": {"keys": [("k", [])], "desc": "Stop playback"},
    # Timeline tools
    "split": {"keys": [("b", ["command"])], "desc": "Split clip at playhead"},
    "split_blade": {"keys": [("c", [])], "desc": "Blade / cut tool"},
    "select_tool": {"keys": [("v", [])], "desc": "Selection tool"},
    "default_transition": {"keys": [("d", ["command", "shift"])], "desc": "Apply default transition"},
    "add_marker": {"keys": [("m", [])], "desc": "Add marker"},
    "in_point": {"keys": [("i", [])], "desc": "Set in point"},
    "out_point": {"keys": [("o", [])], "desc": "Set out point"},
    # Panels (best-effort — version may vary)
    "search_library": {"keys": [("f", ["command"])], "desc": "Focus library search"},
    "confirm": {"keys": [("\r", [])], "desc": "Confirm dialog (Return)"},
    "escape": {"keys": [("\u001b", [])], "desc": "Cancel / close (Escape)"},
}

_MODIFIER_MAP = {
    "command": "command down",
    "shift": "shift down",
    "option": "option down",
    "control": "control down",
}


def list_shortcuts() -> list[dict[str, str]]:
    return [
        {"name": name, "description": meta["desc"]}
        for name, meta in sorted(CAPCUT_SHORTCUTS.items())
    ]


def _build_keystroke_applescript(keys: list[tuple[str, list[str]]], delay: float = 0.15) -> str:
    lines = [
        'tell application "CapCut" to activate',
        f"delay {delay}",
        'tell application "System Events"',
        '    tell process "CapCut"',
        "        set frontmost to true",
        f"        delay {delay}",
    ]
    for char, mods in keys:
        mod_str = ""
        if mods:
            mod_parts = ", ".join(_MODIFIER_MAP[m] for m in mods)
            mod_str = f" using {{{mod_parts}}}"
        if char == " ":
            lines.append(f"        keystroke space{mod_str}")
        elif char == "\r":
            lines.append("        keystroke return")
        elif char == "\u001b":
            lines.append("        key code 53")  # Escape
        elif char == "\b":
            lines.append("        key code 51")  # Delete backspace
        elif char == "\u0003":
            lines.append("        key code 117")  # Forward delete
        else:
            lines.append(f'        keystroke "{char}"{mod_str}')
        lines.append(f"        delay {delay}")
    lines.extend(["    end tell", "end tell", 'return "ok"'])
    return "\n".join(lines)


def run_shortcut(name: str, *, repeat: int = 1) -> dict[str, Any]:
    """Send a named CapCut shortcut via Accessibility (macOS)."""
    from capcut.accessibility import accessibility_status

    key = (name or "").lower().strip().replace("-", "_").replace(" ", "_")
    meta = CAPCUT_SHORTCUTS.get(key)
    if not meta:
        return {
            "success": False,
            "error": f"Unknown shortcut '{name}'",
            "known": sorted(CAPCUT_SHORTCUTS.keys()),
        }

    ax = accessibility_status()
    if not ax.get("granted"):
        return {
            "success": False,
            "error": "accessibility_disabled",
            "hint": ax.get("hint"),
            "shortcut": key,
        }

    keys = meta["keys"] * max(1, min(repeat, 20))
    script = _build_keystroke_applescript(keys)
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timeout", "shortcut": key}
    except Exception as exc:
        return {"success": False, "error": str(exc), "shortcut": key}

    if proc.returncode != 0:
        return {
            "success": False,
            "error": (proc.stderr or proc.stdout or "osascript failed").strip(),
            "shortcut": key,
            "hint": "Grant Accessibility to Terminal/Cursor",
        }
    return {
        "success": True,
        "shortcut": key,
        "description": meta["desc"],
        "repeat": repeat,
        "detail": (proc.stdout or "ok").strip(),
    }
