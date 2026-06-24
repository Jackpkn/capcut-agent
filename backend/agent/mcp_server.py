import logging
import os
import sys
from pathlib import Path

# `uv run agent/mcp_server.py` puts backend/agent on sys.path, not backend/.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_STR = str(_BACKEND_ROOT)
if _BACKEND_STR not in sys.path:
    sys.path.insert(0, _BACKEND_STR)
# Ensure child processes / late imports see backend (fixes "No module named capcut").
os.environ.setdefault("PYTHONPATH", _BACKEND_STR)

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("CapCutAgentMCP")

mcp = FastMCP("CapCutAgent")


def _startup_check() -> None:
    try:
        import capcut  # noqa: F401
        logger.info("MCP startup OK — capcut importable from %s", _BACKEND_STR)
    except ImportError as exc:
        logger.error(
            "MCP startup FAILED: %s — PYTHONPATH=%s sys.path[0]=%s",
            exc,
            os.environ.get("PYTHONPATH"),
            sys.path[0] if sys.path else "",
        )


_startup_check()


def resolve_project_path(project_path: str | None = None) -> str:
    if project_path:
        return project_path
    from capcut.reader import get_all_projects
    projects = get_all_projects()
    if not projects:
        raise ValueError("No CapCut projects found in drafts directory.")
    return projects[0]["path"]


@mcp.tool()
def mcp_health() -> dict:
    """
    Diagnose MCP — confirms capcut imports, projects path, accessibility, LLM.
    Call this first if other MCP tools fail with import errors.
    """
    import capcut

    from capcut.accessibility import accessibility_status
    from capcut.guard import is_capcut_running

    health: dict = {
        "ok": True,
        "backend_root": str(_BACKEND_ROOT),
        "pythonpath": os.environ.get("PYTHONPATH"),
        "capcut_module": capcut.__file__,
        "capcut_running": is_capcut_running(),
        "accessibility": accessibility_status(),
    }
    try:
        from agent.runtime.model import llm_available, provider_order

        health["llm"] = llm_available()
        health["llm_providers"] = provider_order()
    except Exception as exc:
        health["llm"] = False
        health["llm_error"] = str(exc)
    try:
        from capcut.reader import get_all_projects

        projects = get_all_projects()
        health["project_count"] = len(projects)
        health["latest_project"] = projects[0]["name"] if projects else None
    except Exception as exc:
        health["ok"] = False
        health["project_error"] = str(exc)
    return health


@mcp.tool()
def list_projects() -> list[dict]:
    """
    List all local CapCut drafts in the user's drafts directory,
    sorted by last modified time (newest first).
    """
    from capcut.reader import get_all_projects
    return get_all_projects()


@mcp.tool()
def get_timeline_summary(project_path: str = None) -> dict:
    """
    Get a complete summary of the CapCut project timeline, including tracks,
    video clips, audio clips, text overlays, transitions, and effects.
    If project_path is omitted, it defaults to the most recently modified project.
    """
    from capcut.reader import get_project_summary
    path = resolve_project_path(project_path)
    return get_project_summary(path)


@mcp.tool()
def sync_video_to_beats(project_path: str = None, bpm: float = 120.0) -> dict:
    """
    Align video clip boundaries (cuts) to background music beats/peaks.
    If project_path is omitted, it defaults to the most recently modified project.
    """
    from capcut.writer import sync_video_to_beats as capcut_sync
    path = resolve_project_path(project_path)
    return capcut_sync(path, bpm=bpm)


@mcp.tool()
def duck_audio(project_path: str = None, volume: float = 0.2, music_segment_id: str = None) -> str:
    """
    Duck the background music volume under voice overlay segments.
    If project_path is omitted, it defaults to the most recently modified project.
    """
    from capcut.writer import duck_audio as capcut_duck
    path = resolve_project_path(project_path)
    result = capcut_duck(path, volume=volume, music_segment_id=music_segment_id)
    return f"Ducked music segment to {int(result['volume'] * 100)}% volume"


@mcp.tool()
def set_audio_fade(project_path: str = None, segment_id: str = None, fade_in_sec: float = 0.0, fade_out_sec: float = 0.0) -> str:
    """
    Set custom audio fade-in and/or fade-out durations for a specific audio segment.
    If project_path is omitted, it defaults to the most recently modified project.
    """
    if not segment_id:
        raise ValueError("segment_id is required")
    from capcut.writer import set_audio_fade as capcut_fade
    path = resolve_project_path(project_path)
    result = capcut_fade(path, segment_id=segment_id, fade_in_sec=fade_in_sec, fade_out_sec=fade_out_sec)
    return f"Applied fade properties to audio segment {result['segment_id'][:8]}… (in: {fade_in_sec}s, out: {fade_out_sec}s)"


@mcp.tool()
def fade_project_music(project_path: str = None, fade_in_sec: float = 2.0, fade_out_sec: float = 3.0) -> str:
    """
    Apply automated music fading (fade-in at project start, fade-out at project end)
    for the primary background music track.
    If project_path is omitted, it defaults to the most recently modified project.
    """
    from capcut.writer import fade_project_music as capcut_fade_proj
    path = resolve_project_path(project_path)
    result = capcut_fade_proj(path, fade_in_sec=fade_in_sec, fade_out_sec=fade_out_sec)
    return f"Applied fade-in ({result['fade_in_sec']}s) and fade-out ({result['fade_out_sec']}s) to project music track"


@mcp.tool()
def apply_audio_crossfades(project_path: str = None, crossfade_sec: float = 1.0) -> str:
    """
    Apply audio crossfades at adjacent background music clip boundaries to smooth transitions.
    If project_path is omitted, it defaults to the most recently modified project.
    """
    from capcut.writer import apply_audio_crossfades as capcut_crossfade
    path = resolve_project_path(project_path)
    result = capcut_crossfade(path, crossfade_sec=crossfade_sec)
    return f"Applied crossfades to {result['crossfades_applied']} audio boundary cuts"


@mcp.tool()
def apply_color_preset(project_path: str = None, preset: str = None, start_sec: float = 0.0, duration_sec: float = None, bind_segment_id: str = None) -> str:
    """
    Apply a cinematic color grading filter preset (e.g. cinematic, warm, cool, vintage, vivid, teal_orange, moody).
    If project_path is omitted, it defaults to the most recently modified project.
    """
    if not preset:
        raise ValueError("preset is required")
    from capcut.writer import apply_color_preset as capcut_preset
    path = resolve_project_path(project_path)
    result = capcut_preset(
        path,
        preset=preset,
        start_sec=start_sec,
        duration_sec=duration_sec,
        bind_segment_id=bind_segment_id,
    )
    return f'Applied color preset "{preset}" — effect "{result["name"]}"'


@mcp.tool()
def add_transition(project_path: str = None, clip_index: int = None, clip_name: str = None, query: str = "") -> str:
    """
    Add a transition after a specific clip index or name.
    If project_path is omitted, it defaults to the most recently modified project.
    """
    from agent.actions import execute_action
    path = resolve_project_path(project_path)
    params = {}
    if clip_index is not None:
        params["clip_index"] = clip_index
    if clip_name is not None:
        params["clip_name"] = clip_name
    if query:
        params["query"] = query
    return execute_action("add_transition", params, path)


@mcp.tool()
def add_effect(project_path: str = None, query: str = "", start_sec: float = 0.0, duration_sec: float = 3.0) -> str:
    """
    Add a visual effect to the timeline.
    If project_path is omitted, it defaults to the most recently modified project.
    """
    from agent.actions import execute_action
    path = resolve_project_path(project_path)
    params = {
        "query": query,
        "start_sec": start_sec,
        "duration_sec": duration_sec,
    }
    return execute_action("add_effect", params, path)


@mcp.tool()
def generate_captions(project_path: str = None, style: str = "travel") -> str:
    """
    Generate speech-synced caption overlays across the video timeline.
    If project_path is omitted, it defaults to the most recently modified project.
    """
    from agent.actions import execute_action
    path = resolve_project_path(project_path)
    params = {"style": style}
    return execute_action("generate_captions", params, path)


@mcp.tool()
def update_text(project_path: str = None, text_id: str = None, new_content: str = None) -> str:
    """
    Update the content of a specific text overlay segment.
    If project_path is omitted, it defaults to the most recently modified project.
    """
    if not text_id or not new_content:
        raise ValueError("text_id and new_content are required")
    from agent.actions import execute_action
    path = resolve_project_path(project_path)
    params = {
        "text_id": text_id,
        "new_content": new_content,
    }
    return execute_action("update_text", params, path)


@mcp.tool()
def split_clip(project_path: str = None, segment_id: str = None, at_sec: float = 0.0) -> str:
    """
    Split a video/audio clip at a timeline position (seconds).
    If project_path is omitted, it defaults to the most recently modified project.
    """
    if not segment_id:
        raise ValueError("segment_id is required")
    from agent.actions import execute_action
    path = resolve_project_path(project_path)
    params = {
        "segment_id": segment_id,
        "at_sec": at_sec,
    }
    return execute_action("split_clip", params, path)


@mcp.tool()
def trim_clip(project_path: str = None, segment_id: str = None, start_sec: float = None, end_sec: float = None) -> str:
    """
    Trim a video/audio clip segment (sets start and/or end time in seconds).
    If project_path is omitted, it defaults to the most recently modified project.
    """
    if not segment_id:
        raise ValueError("segment_id is required")
    from agent.actions import execute_action
    path = resolve_project_path(project_path)
    params = {"segment_id": segment_id}
    if start_sec is not None:
        params["start_sec"] = start_sec
    if end_sec is not None:
        params["end_sec"] = end_sec
    return execute_action("trim_clip", params, path)


@mcp.tool()
def reorder_clips(project_path: str = None, order: list[int] = None) -> str:
    """
    Reorder video clips on the primary video track.
    If project_path is omitted, it defaults to the most recently modified project.
    """
    if not order:
        raise ValueError("order is required")
    from agent.actions import execute_action
    path = resolve_project_path(project_path)
    params = {"order": order}
    return execute_action("reorder_clips", params, path)


@mcp.tool()
def execute_capcut_script(
    project_path: str = None,
    code: str = None,
    timeout_sec: float = 30.0,
) -> dict:
    """
    Layer 3 dynamic scripting — run sandboxed Python against the CapCut draft.

  Available in script scope: project_path, read_project, write_project, get_summary,
  primitives (keyframes, transforms, zoom_pulse, shake_segment), filters, draft_ops,
  add_filter, apply_color_preset, duck_audio, fade_project_music, trim_clip, split_clip, etc.
  Set `result = ...` to return a value from the script.

  Example:
    seg = get_summary()["video_clips"][0]["segment_id"]
    primitives.zoom_pulse(project_path, seg, peak_scale=1.2, duration_sec=3)
    result = "zoom applied"
    """
    if not code:
        raise ValueError("code is required")
    from capcut.scripting import execute_capcut_script as run_script
    path = resolve_project_path(project_path)
    return run_script(path, code, timeout_sec=timeout_sec)


@mcp.tool()
def rpa_capcut(
    rpa_action: str,
    project_path: str = None,
    clip_name: str = "",
    output_path: str = None,
    shortcut_name: str = "",
    repeat: int = 1,
    query: str = "",
    asset_type: str = "music",
    item_name: str = "",
    from_home: bool = True,
) -> dict:
    """
    Layer 2 OS GUI / RPA — drive CapCut desktop (shortcuts, export, AI UI, library).

    Actions:
      focus, save, export, shortcut, auto_cutout, auto_captions, auto_design,
      search_library, download_asset

    For shortcuts use rpa_action="shortcut" + shortcut_name (or use capcut_shortcut).
    Prefer generate_captions (Whisper) over auto_captions — free and fully on disk.
    Requires Accessibility permission for Terminal/Cursor.
    """
    from capcut.rpa import execute_rpa
    path = resolve_project_path(project_path) if project_path else None
    return execute_rpa(
        rpa_action,
        path,
        clip_name=clip_name,
        output_path=output_path,
        shortcut_name=shortcut_name,
        repeat=repeat,
        query=query,
        asset_type=asset_type,
        item_name=item_name,
        from_home=from_home,
    )


@mcp.tool()
def capcut_automate(
    goal: str,
    project_path: str = None,
    media_paths: list[str] = None,
    discover_ui: bool = True,
    strategy: str = "ui_first",
) -> dict:
    """
    **Main intelligent automation** — describe WHAT you want in plain language.

    strategy (recommended: ui_first):
      - ui_first — drive CapCut app UI (clicks, menus, shortcuts) like a human
      - hybrid — disk edits when fast, UI when needed
      - disk — silent JSON timeline edits only

    Examples:
      goal="add auto captions through capcut ui and export"
      goal="open filters and apply cinematic look"
      goal="capcut ai autocut design"
    """
    from capcut.automation_brain import automate

    path = resolve_project_path(project_path) if project_path or not media_paths else None
    if not path and not media_paths:
        path = resolve_project_path(None)
    if not path and media_paths:
        goal = f"{goal} (bootstrap from media)"
        from capcut.ingest import create_project_from_media

        created = create_project_from_media(media_paths)
        path = created["project_path"]

    if not path:
        raise ValueError("project_path or media_paths required")

    return automate(
        goal,
        path,
        discover_ui=discover_ui,
        media_paths=media_paths,
        strategy=strategy,
    )


@mcp.tool()
def capcut_ui_automate(
    goal: str,
    project_path: str = None,
    max_steps: int = 14,
) -> dict:
    """
    **101% UI automation** — only drives CapCut desktop (no disk JSON edits).

    Loop: scan visible UI → click/menu/shortcut/type → re-scan → repeat.
    Use for CapCut AI, native captions, filters panel, library, export dialogs.

    Requires CapCut open + Accessibility permission for Cursor/Terminal.
    """
    from capcut.ui_agent import ui_automate

    path = resolve_project_path(project_path) if project_path else None
    return ui_automate(goal, path, max_steps=max_steps)


@mcp.tool()
def capcut_ui_click(label: str) -> dict:
    """Click a visible CapCut button or panel label (from discover_capcut_ui)."""
    from capcut.ui_discover import click_ui_element

    return click_ui_element(label)


@mcp.tool()
def capcut_ui_menu(path: str) -> dict:
    """Navigate CapCut menu bar. path format: 'Text>Auto captions' or 'Video>Cutout'."""
    from capcut.ui_discover import run_menu_path

    parts = [p.strip() for p in path.replace("/", ">").split(">") if p.strip()]
    return run_menu_path(parts)


@mcp.tool()
def plan_capcut_automation(goal: str, project_path: str = None) -> dict:
    """
    Plan only (no execute) — see which capabilities the brain would run and why.
    Useful to preview before applying edits.
    """
    from capcut.automation_brain import plan_automation
    from capcut.capabilities import capability_by_id
    from capcut.reader import get_project_summary
    from capcut.ui_discover import discover_capcut_ui

    path = resolve_project_path(project_path)
    ui = discover_capcut_ui()
    plan = plan_automation(
        goal,
        path,
        timeline_summary=get_project_summary(path),
        ui_elements=ui.get("elements"),
    )
    return {
        "goal": goal,
        "project_path": path,
        "summary": plan.summary,
        "source": plan.source,
        "steps": [
            {
                "capability_id": s.capability_id,
                "reason": s.reason,
                "params": s.params,
                "purpose": (capability_by_id(s.capability_id).purpose if capability_by_id(s.capability_id) else None),
            }
            for s in plan.steps
        ],
    }


@mcp.tool()
def search_capcut_capabilities(goal: str, limit: int = 10) -> list[dict]:
    """
    Find CapCut capabilities ranked by semantic match to your goal.
    Shows PURPOSE of each — why you'd use it, not just key names.
    """
    from capcut.capabilities import search_capabilities

    return search_capabilities(goal, limit=limit)


@mcp.tool()
def discover_capcut_ui() -> dict:
    """
    Scan CapCut's live UI (menus, buttons, panels) — infinite features appear here.
    The automation brain uses this to click things disk JSON cannot express.
    """
    from capcut.ui_discover import discover_capcut_ui as discover

    return discover()


@mcp.tool()
def list_capcut_shortcuts() -> list[dict]:
    """List CapCut keyboard shortcuts you can fire via capcut_shortcut / rpa_capcut."""
    from capcut.shortcuts import list_shortcuts

    return list_shortcuts()


@mcp.tool()
def capcut_shortcut(shortcut_name: str, repeat: int = 1) -> dict:
    """
    Press a CapCut desktop shortcut (macOS Accessibility).

    Examples: save, undo, redo, export, play_pause, split, default_transition,
    search_library, duplicate, copy, paste, delete.
    Call list_capcut_shortcuts() for the full list.
    """
    from capcut.shortcuts import run_shortcut

    return run_shortcut(shortcut_name, repeat=repeat)


@mcp.tool()
def search_capcut_library(query: str, asset_type: str = "music") -> dict:
    """
    Open CapCut's in-app library panel and search (music, effect, filter, transition, sticker).
    Requires CapCut open + Accessibility permission.
    """
    from capcut.ui_trigger import trigger_capcut_search

    return trigger_capcut_search(query, asset_type=asset_type)


@mcp.tool()
def download_capcut_asset(query: str, asset_type: str = "music", item_name: str = "") -> dict:
    """Search CapCut library and click to download an asset into the local cache."""
    from capcut.ui_trigger import download_asset_ui

    return download_asset_ui(query, asset_type=asset_type, item_name=item_name or None)


@mcp.tool()
def run_edit_pipeline(
    project_path: str = None,
    captions: bool = True,
    caption_style: str = "travel",
    color_preset: str = "cinematic",
    music_fade_in: float = 2.0,
    music_fade_out: float = 3.0,
    duck_volume: float = 0.25,
    sync_beats: bool = False,
    bpm: float = 120.0,
    verify: bool = True,
) -> dict:
    """
    One-shot full edit on disk — captions, duck, fade, color, optional beat sync, CDP reload, save, verify.

    Use after import_clips or on any existing project. No manual CapCut clicking needed for these steps.
    """
    from capcut.pipeline import run_edit_pipeline as pipeline_run

    path = resolve_project_path(project_path)
    return pipeline_run(
        path,
        captions=captions,
        caption_style=caption_style,
        color_preset=color_preset,
        music_fade_in=music_fade_in,
        music_fade_out=music_fade_out,
        duck_volume=duck_volume,
        sync_beats=sync_beats,
        bpm=bpm,
        verify=verify,
    )


@mcp.tool()
def bootstrap_project_and_edit(
    media_paths: list[str] = None,
    project_name: str = None,
    photo_duration_sec: float = 3.0,
    caption_style: str = "travel",
    color_preset: str = "cinematic",
) -> dict:
    """
    End-to-end: create CapCut project from local files → full edit pipeline.

    Example MCP flow:
      1. Put clips at /path/clip1.mp4, /path/clip2.mp4
      2. bootstrap_project_and_edit(media_paths=[...])
      3. rpa_capcut("export") when done
    """
    if not media_paths:
        raise ValueError("media_paths is required")
    from capcut.pipeline import bootstrap_and_edit

    return bootstrap_and_edit(
        media_paths,
        project_name=project_name,
        photo_duration_sec=photo_duration_sec,
        caption_style=caption_style,
        color_preset=color_preset,
    )


@mcp.tool()
def verify_project(project_path: str = None, expectations: dict = None) -> dict:
    """
    Layer 1 QA — verify timeline state after edits.

    expectations (optional): duration_sec, min_video_clips, filter_name,
    min_captions, music_present, segment_ids, etc.
    """
    from capcut.verify import verify_project as capcut_verify
    path = resolve_project_path(project_path)
    return capcut_verify(path, expectations or {})


@mcp.tool()
def import_clips(
    project_path: str = None,
    media_paths: list[str] = None,
    photo_duration_sec: float = 3.0,
) -> dict:
    """
    Import local video/photo/audio files onto a CapCut project timeline.
    Use after upload or when adding clips to an existing project.
    """
    if not media_paths:
        raise ValueError("media_paths is required")
    from capcut.ingest import import_clips as capcut_import

    path = resolve_project_path(project_path)
    return capcut_import(path, media_paths, photo_duration_sec=photo_duration_sec)


@mcp.tool()
def create_project_from_media(
    media_paths: list[str] = None,
    project_name: str = None,
    photo_duration_sec: float = 3.0,
) -> dict:
    """
    Create a new CapCut project from local media files (clone template + import).
    Returns project_path for subsequent edits.
    """
    if not media_paths:
        raise ValueError("media_paths is required")
    from capcut.ingest import create_project_from_media as capcut_create

    return capcut_create(
        media_paths,
        project_name=project_name,
        photo_duration_sec=photo_duration_sec,
    )


if __name__ == "__main__":
    mcp.run()
