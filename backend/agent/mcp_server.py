from mcp.server.fastmcp import FastMCP
import logging
import sys

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("CapCutAgentMCP")

mcp = FastMCP("CapCutAgent")


def resolve_project_path(project_path: str | None = None) -> str:
    if project_path:
        return project_path
    from capcut.reader import get_all_projects
    projects = get_all_projects()
    if not projects:
        raise ValueError("No CapCut projects found in drafts directory.")
    return projects[0]["path"]


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


if __name__ == "__main__":
    mcp.run()
