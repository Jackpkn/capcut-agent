"""Layer 2 — OS GUI / RPA specialist for CapCut desktop features.

Drives CapCut UI for operations that cannot be done via draft_info.json alone:
auto cutout, native auto-captions UI, export, smart reframe, etc.

Free alternatives to paid CapCut Pro features:
  - captions  → prefer agent Whisper path (generate_captions) before RPA
  - color     → built-in filter presets (apply_color_preset / add_filter)
  - beat sync → sync_video_to_beats (disk)
  - cutout    → RPA triggers CapCut native cutout (or future local rembg engine)
"""

from __future__ import annotations

import logging
import subprocess
import time
from typing import Any

from capcut.accessibility import accessibility_status
from capcut.project_ui import reopen_project

logger = logging.getLogger(__name__)

# AppleScript templates — CapCut 8.x; selectors may drift on app updates.
_FOCUS_SCRIPT = r'''
tell application "CapCut" to activate
delay 0.5
tell application "System Events"
    tell process "CapCut"
        set frontmost to true
    end tell
end tell
return "focused"
'''

_EXPORT_SCRIPT = r'''
on run argv
    set outPath to item 1 of argv
    tell application "CapCut" to activate
    delay 0.6
    tell application "System Events"
        tell process "CapCut"
            set frontmost to true
            -- Export shortcut (CapCut desktop)
            keystroke "e" using {command down}
            delay 1.2
            -- Best-effort: confirm export dialog
            try
                keystroke return
            end try
        end tell
    end tell
    return "export_triggered"
end run
'''

_CUTOUT_SCRIPT = r'''
on run argv
    set clipLabel to item 1 of argv
    tell application "CapCut" to activate
    delay 0.6
    tell application "System Events"
        tell process "CapCut"
            set frontmost to true
            delay 0.3
            -- Select clip by name fragment in timeline (best-effort)
            try
                set found to false
                repeat with w in windows
                    repeat with grp in groups of w
                        repeat with el in UI elements of grp
                            try
                                set t to value of el
                                if t contains clipLabel then
                                    click el
                                    set found to true
                                    exit repeat
                                end if
                            end try
                        end repeat
                        if found then exit repeat
                    end repeat
                    if found then exit repeat
                end repeat
            end try
            delay 0.5
            -- Tab through right panel — user may need to confirm cutout manually on drift
            return "cutout_attempted"
        end tell
    end tell
end run
'''

_AUTO_CAPTIONS_SCRIPT = r'''
tell application "CapCut" to activate
delay 0.6
tell application "System Events"
    tell process "CapCut"
        set frontmost to true
        delay 0.3
        -- CapCut: Text panel → Auto captions (labels vary by locale/version)
        try
            click menu bar item "Text" of menu bar 1
            delay 0.4
        end try
    end tell
end tell
return "auto_captions_panel_attempted"
'''

_AUTO_DESIGN_SCRIPT = r'''
on run argv
    set mode to item 1 of argv
    tell application "CapCut" to activate
    delay 0.8
    tell application "System Events"
        tell process "CapCut"
            set frontmost to true
            delay 0.4
            set clicked to false
            set needles to {"AutoCut", "Auto Cut", "Smart", "AI", "Template", "Design"}
            if mode is "home" then
                try
                    click menu bar item "CapCut" of menu bar 1
                    delay 0.2
                    click menu item "Back to home page" of menu "CapCut" of menu bar item "CapCut" of menu bar 1
                    delay 1.0
                end try
            end if
            repeat with w in windows
                repeat with txtElem in static texts of w
                    try
                        set n to name of txtElem
                        repeat with needle in needles
                            if n contains needle then
                                click txtElem
                                set clicked to true
                                exit repeat
                            end if
                        end repeat
                        if clicked then exit repeat
                    end try
                end repeat
                if clicked then exit repeat
            end repeat
            if clicked then return "auto_design_clicked"
            return "auto_design_not_found"
        end tell
    end tell
end run
'''


def _run_applescript(script: str, *args: str, timeout: float = 45.0) -> dict[str, Any]:
    cmd = ["osascript", "-e", script, *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timeout", "hint": "CapCut UI action timed out"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return {
            "success": False,
            "error": err or out or "osascript failed",
            "hint": "Grant Accessibility to Terminal/Cursor in System Settings",
        }
    return {"success": True, "detail": out or "ok"}


def rpa_focus() -> dict[str, Any]:
    ax = accessibility_status()
    if not ax.get("granted"):
        return {
            "success": False,
            "error": "accessibility_disabled",
            "hint": ax.get("hint"),
            "checklist": ax.get("checklist", []),
        }
    result = _run_applescript(_FOCUS_SCRIPT)
    result["action"] = "focus"
    return result


def rpa_export(output_path: str | None = None) -> dict[str, Any]:
    """Trigger CapCut export dialog (Cmd+E). output_path is advisory for future automation."""
    ax = accessibility_status()
    if not ax.get("granted"):
        return {"success": False, "error": "accessibility_disabled", "hint": ax.get("hint")}

    args = (output_path or "",)
    result = _run_applescript(_EXPORT_SCRIPT, *args, timeout=60.0)
    result["action"] = "export"
    result["output_path"] = output_path
    return result


def rpa_auto_cutout(clip_name: str = "") -> dict[str, Any]:
    """Best-effort UI path to CapCut Auto Cutout on the selected clip."""
    ax = accessibility_status()
    if not ax.get("granted"):
        return {"success": False, "error": "accessibility_disabled", "hint": ax.get("hint")}

    label = (clip_name or "clip")[:40]
    result = _run_applescript(_CUTOUT_SCRIPT, label, timeout=60.0)
    result["action"] = "auto_cutout"
    result["clip_name"] = clip_name
    result["hint"] = (
        "If cutout did not apply, select the clip in CapCut and open Video → Cutout → Auto cutout. "
        "For a free offline alternative, use generate_captions + disk edits until rembg engine ships."
    )
    return result


def rpa_auto_captions_native() -> dict[str, Any]:
    """Open CapCut native auto-captions UI (paid feature in some regions).

    Prefer agent path: generate_captions (Whisper) — free and fully automated on disk.
    """
    ax = accessibility_status()
    if not ax.get("granted"):
        return {"success": False, "error": "accessibility_disabled", "hint": ax.get("hint")}

    result = _run_applescript(_AUTO_CAPTIONS_SCRIPT, timeout=45.0)
    result["action"] = "auto_captions_native"
    result["free_alternative"] = "generate_captions (Whisper) via MCP or agent"
    return result


def rpa_auto_design(from_home: bool = True) -> dict[str, Any]:
    """Best-effort: open CapCut AI / AutoCut / Smart template UI (version-dependent)."""
    ax = accessibility_status()
    if not ax.get("granted"):
        return {"success": False, "error": "accessibility_disabled", "hint": ax.get("hint")}

    mode = "home" if from_home else "editor"
    result = _run_applescript(_AUTO_DESIGN_SCRIPT, mode, timeout=60.0)
    result["action"] = "auto_design"
    result["hint"] = (
        "CapCut AI design labels change by version. If nothing clicked, use "
        "create_project_from_media + run_edit_pipeline for full disk automation."
    )
    if "not_found" in (result.get("detail") or ""):
        result["success"] = False
        result["error"] = "auto_design_not_found"
    return result


def rpa_shortcut(shortcut_name: str, repeat: int = 1) -> dict[str, Any]:
    from capcut.shortcuts import run_shortcut

    out = run_shortcut(shortcut_name, repeat=repeat)
    out["action"] = "shortcut"
    return out


def execute_rpa(
    action: str,
    project_path: str | None = None,
    *,
    clip_name: str = "",
    output_path: str | None = None,
    shortcut_name: str = "",
    repeat: int = 1,
    from_home: bool = True,
    query: str = "",
    asset_type: str = "music",
    item_name: str = "",
) -> dict[str, Any]:
    """Dispatch Layer-2 RPA actions."""
    action = (action or "").lower().strip().replace("-", "_")

    if action in ("focus", "activate"):
        return rpa_focus()

    if action in ("export", "render"):
        out = rpa_export(output_path)
        if out.get("success") and project_path:
            time.sleep(0.5)
            out["reopened"] = reopen_project(project_path)
        return out

    if action in ("auto_cutout", "cutout", "background_removal"):
        out = rpa_auto_cutout(clip_name)
        if out.get("success") and project_path:
            out["reopened"] = reopen_project(project_path)
        return out

    if action in ("auto_captions", "native_captions"):
        return rpa_auto_captions_native()

    if action in ("auto_design", "smart_template", "ai_design"):
        return rpa_auto_design(from_home=from_home)

    if action in ("shortcut", "hotkey", "key"):
        if not shortcut_name:
            raise ValueError("shortcut_name is required for shortcut action")
        return rpa_shortcut(shortcut_name, repeat=repeat)

    if action == "save":
        return rpa_shortcut("save")

    if action in ("search_library", "library_search"):
        from capcut.ui_trigger import trigger_capcut_search

        return trigger_capcut_search(query or "music", asset_type=asset_type)

    if action in ("download_asset", "library_download"):
        from capcut.ui_trigger import download_asset_ui

        return download_asset_ui(query or "music", asset_type=asset_type, item_name=item_name or None)

    known = (
        "focus, export, save, shortcut, auto_cutout, auto_captions, auto_design, "
        "search_library, download_asset"
    )
    raise ValueError(f"Unknown RPA action '{action}'. Known: {known}")
