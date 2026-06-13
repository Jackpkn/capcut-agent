"""Detect whether UI automation can drive CapCut (macOS Accessibility)."""

from __future__ import annotations

import os
import subprocess

# GUI apps that commonly host `uv run uvicorn` — user must enable Accessibility here.
_HOST_APPS = {
    "Cursor": "Cursor",
    "cursor": "Cursor",
    "Terminal": "Terminal",
    "iTerm2": "iTerm",
    "Code": "Visual Studio Code",
    "Electron": "Cursor",  # Cursor helper processes
}


def _parent_pid(pid: int) -> int | None:
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "ppid="],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        line = out.stdout.strip()
        return int(line) if line.isdigit() else None
    except (OSError, ValueError):
        return None


def _process_name(pid: int) -> str:
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        return out.stdout.strip()
    except OSError:
        return ""


def automation_host_app() -> str:
    """Name of the app macOS will attribute UI automation to (walk parent chain)."""
    pid = os.getpid()
    seen: set[int] = set()
    for _ in range(20):
        if pid in seen or pid <= 1:
            break
        seen.add(pid)
        name = _process_name(pid)
        for key, label in _HOST_APPS.items():
            if key in name:
                return label
        nxt = _parent_pid(pid)
        if nxt is None:
            break
        pid = nxt
    return "Terminal or Cursor"


def ui_automation_enabled() -> bool:
    script = '''
    tell application "System Events"
        return UI elements enabled
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and "true" in result.stdout.lower()
    except (subprocess.TimeoutExpired, OSError):
        return False


def accessibility_report() -> dict:
    host = automation_host_app()
    enabled = ui_automation_enabled()
    return {
        "enabled": enabled,
        "host_app": host,
        "capcut_note": (
            "CapCut does not need Accessibility for the agent. "
            f"Enable **{host}** — the app where you run `uvicorn`."
        ),
        "steps": [
            "Open **System Settings → Privacy & Security → Accessibility**.",
            f"Enable **{host}** (the app running `uv run uvicorn main:app`).",
            "If you use an external Terminal window, enable **Terminal** — not only Cursor.",
            "Quit and reopen that app after toggling the permission.",
            "In **Privacy & Security → Automation**, allow the same app to control **System Events** (required for menu automation).",
            "Click **Approve** again; the agent will press Home in CapCut automatically.",
        ],
        "quick_test": (
            f'Run in the same terminal as uvicorn: '
            f'`osascript -e \'tell application "System Events" to return UI elements enabled\'` '
            f'— should print **true**.'
        ),
    }
