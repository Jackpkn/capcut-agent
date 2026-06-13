"""Ensure CapCut is not running before writing draft files."""

from __future__ import annotations

import subprocess
from pathlib import Path


def is_capcut_running() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-x", "CapCut"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except OSError:
        return False


def is_project_locked(project_path: str) -> bool:
    return (Path(project_path) / ".locked").exists()


def can_write_safely(project_path: str) -> bool:
    """True when the project is not open in the CapCut editor (no .locked file)."""
    return not is_project_locked(project_path)


def assert_safe_to_write(project_path: str) -> None:
    from capcut.project_ui import accessibility_enabled, prepare_project_for_write

    if can_write_safely(project_path):
        return
    if prepare_project_for_write(project_path):
        return
    from capcut.accessibility import automation_host_app

    host = automation_host_app()
    if not accessibility_enabled():
        raise RuntimeError(
            f"Accessibility is off for **{host}** (the app running uvicorn — not CapCut). "
            f"System Settings → Privacy & Security → Accessibility → enable **{host}**, "
            f"quit and reopen {host}, then Approve again. "
            f"Or click **Home** in CapCut — queued edits apply when the project unlocks. "
            f"Check GET /accessibility on the backend for a full checklist."
        )
    raise RuntimeError(
        "Project is still open in CapCut. Click **Home** (top-left) to leave the editor — "
        "queued edits apply within a few seconds. Accessibility is on but Home navigation "
        "did not unlock the project (CapCut UI may differ on your version)."
    )
