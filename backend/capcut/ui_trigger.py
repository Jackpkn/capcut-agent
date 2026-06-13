"""Trigger CapCut's native library search via macOS UI automation."""

from __future__ import annotations

import logging
import subprocess
import time

logger = logging.getLogger(__name__)

PANEL_NAMES = {
    "music": "VETreeMainCellItem:Music",
    "audio": "VETreeMainCellItem:Music",
    "effect": "VETreeMainCellItem:Sounds effects",
    "effects": "VETreeMainCellItem:Sounds effects",
    "transition": "VETreeMainCellItem:Music",
    "transitions": "VETreeMainCellItem:Music",
    "sticker": "VETreeMainCellItem:Music",
    "stickers": "VETreeMainCellItem:Music",
    "text_template": "VETreeMainCellItem:Music",
    "text": "VETreeMainCellItem:Music",
}

SEARCH_SCRIPT = r'''
on run argv
    set searchQuery to item 1 of argv
    set panelId to item 2 of argv

    tell application "CapCut" to activate
    delay 0.7

    tell application "System Events"
        tell process "CapCut"
            set frontmost to true
            delay 0.3

            set targetWindow to missing value
            repeat with w in windows
                if name of w contains "CapCut" then
                    set targetWindow to w
                    exit repeat
                end if
            end repeat
            if targetWindow is missing value then set targetWindow to window 1

            set panelClicked to false
            repeat with txtElem in static texts of targetWindow
                try
                    if name of txtElem is panelId then
                        click txtElem
                        set panelClicked to true
                        exit repeat
                    end if
                end try
            end repeat

            delay 0.8

            set searchDone to false
            repeat with tf in text fields of targetWindow
                try
                    click tf
                    set focused of tf to true
                    keystroke "a" using command down
                    delay 0.1
                    keystroke searchQuery
                    set searchDone to true
                    exit repeat
                end try
            end repeat

            if not searchDone then
                keystroke "f" using command down
                delay 0.2
                keystroke searchQuery
            end if

            delay 0.2
            keystroke return
            delay 2.0
            return "ok:" & panelId
        end tell
    end tell
end run
'''

SCRAPE_SCRIPT = r'''
on run argv
    set prefix to item 1 of argv

    tell application "System Events"
        tell process "CapCut"
            set targetWindow to missing value
            repeat with w in windows
                if name of w contains "CapCut" then
                    set targetWindow to w
                    exit repeat
                end if
            end repeat
            if targetWindow is missing value then set targetWindow to window 1

            set tracks to {}
            repeat with txtElem in static texts of targetWindow
                try
                    set n to name of txtElem
                    if n starts with prefix then
                        set trackName to text ((length of prefix) + 1) thru -1 of n
                        if trackName is not "" then set end of tracks to trackName
                    end if
                end try
            end repeat
            return tracks
        end tell
    end tell
end run
'''


def _check_accessibility() -> bool:
    from capcut.accessibility import ui_automation_enabled

    return ui_automation_enabled()


def scrape_capcut_results(prefix: str = "MTLSText:") -> list[str]:
    """Read visible library item names from CapCut's accessibility tree."""
    if not _check_accessibility():
        return []

    try:
        result = subprocess.run(
            ["osascript", "-e", SCRAPE_SCRIPT, prefix],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []

        lines = [ln.strip() for ln in result.stdout.split(",") if ln.strip()]
        # osascript returns comma-separated list for AppleScript lists
        if len(lines) == 1 and lines[0].startswith("{"):
            lines = [x.strip().strip('"') for x in lines[0].strip("{}").split(",") if x.strip()]

        return [name for name in lines if name and name != "missing value"]
    except Exception as e:
        logger.debug("Scrape failed: %s", e)
        return []


DOWNLOAD_SCRIPT = r'''
on run argv
    set searchQuery to item 1 of argv
    set panelId to item 2 of argv
    set itemName to item 3 of argv

    tell application "CapCut" to activate
    delay 0.7

    tell application "System Events"
        tell process "CapCut"
            set frontmost to true
            delay 0.3

            set targetWindow to missing value
            repeat with w in windows
                if name of w contains "CapCut" then
                    set targetWindow to w
                    exit repeat
                end if
            end repeat
            if targetWindow is missing value then set targetWindow to window 1

            repeat with txtElem in static texts of targetWindow
                try
                    if name of txtElem is panelId then
                        click txtElem
                        exit repeat
                    end if
                end try
            end repeat

            delay 0.8

            repeat with tf in text fields of targetWindow
                try
                    click tf
                    set focused of tf to true
                    keystroke "a" using command down
                    delay 0.1
                    keystroke searchQuery
                    exit repeat
                end try
            end repeat

            delay 0.2
            keystroke return
            delay 2.0

            set clicked to false
            repeat with txtElem in static texts of targetWindow
                try
                    set n to name of txtElem
                    if n starts with "MTLSText:" then
                        set label to text 11 thru -1 of n
                        if itemName is not "" then
                            if label contains itemName or itemName contains label then
                                click txtElem
                                set clicked to true
                                exit repeat
                            end if
                        else
                            click txtElem
                            set clicked to true
                            exit repeat
                        end if
                    end if
                end try
            end repeat

            if clicked then
                delay 1.5
                keystroke return
                return "downloaded:" & panelId
            end if
            return "no_match"
        end tell
    end tell
end run
'''


def download_asset_ui(
    query: str,
    asset_type: str = "music",
    item_name: str | None = None,
) -> dict:
    """Search CapCut library, click the matching item to trigger download."""
    query = (query or "music").strip()
    panel = PANEL_NAMES.get(asset_type, PANEL_NAMES["music"])
    match_name = (item_name or query).strip()

    if not _check_accessibility():
        return {
            "success": False,
            "error": "accessibility_disabled",
            "hint": "Grant Accessibility permission to Terminal/Cursor in System Settings",
        }

    try:
        result = subprocess.run(
            ["osascript", "-e", DOWNLOAD_SCRIPT, query, panel, match_name],
            capture_output=True,
            text=True,
            timeout=35,
        )
        out = (result.stdout or "").strip()
        if result.returncode != 0:
            return {
                "success": False,
                "error": (result.stderr or out or "osascript failed")[:200],
            }
        if out == "no_match":
            return {
                "success": False,
                "error": "no_match",
                "hint": f'No library result matched "{match_name}" in CapCut — open the project and try manually',
            }
        return {
            "success": True,
            "method": "ui_download",
            "panel": panel,
            "query": query,
            "detail": out,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timeout"}
    except Exception as e:
        logger.exception("UI download error")
        return {"success": False, "error": str(e)}


def trigger_capcut_search(query: str, asset_type: str = "music") -> dict:
    """Open CapCut's library panel and run a search."""
    query = (query or "music").strip()
    panel = PANEL_NAMES.get(asset_type, PANEL_NAMES["music"])

    if not _check_accessibility():
        return {
            "success": False,
            "method": "ui_automation",
            "panel": panel,
            "query": query,
            "error": "accessibility_disabled",
            "hint": (
                "Grant Accessibility permission to Terminal/Cursor in "
                "System Settings → Privacy & Security → Accessibility, then retry"
            ),
        }

    try:
        result = subprocess.run(
            ["osascript", "-e", SEARCH_SCRIPT, query, panel],
            capture_output=True,
            text=True,
            timeout=25,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "osascript failed").strip()
            logger.warning("CapCut UI trigger failed: %s", err)
            return {
                "success": False,
                "method": "ui_automation",
                "panel": panel,
                "query": query,
                "error": err[:200],
                "hint": "Make sure CapCut is open with a project and the window is visible",
            }

        scraped = scrape_capcut_results()
        return {
            "success": True,
            "method": "ui_automation",
            "panel": panel,
            "query": query,
            "detail": (result.stdout or "triggered").strip(),
            "scraped_count": len(scraped),
            "scraped_preview": scraped[:5],
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "method": "ui_automation",
            "panel": panel,
            "query": query,
            "error": "timeout",
            "hint": "CapCut did not respond in time — ensure it is open and focused",
        }
    except Exception as e:
        logger.exception("UI trigger error")
        return {
            "success": False,
            "method": "ui_automation",
            "panel": panel,
            "query": query,
            "error": str(e),
        }
