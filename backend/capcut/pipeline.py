"""One-shot disk edit pipeline — full timeline polish via MCP without manual CapCut clicks."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def run_edit_pipeline(
    project_path: str,
    *,
    captions: bool = True,
    caption_style: str = "travel",
    color_preset: str = "cinematic",
    music_fade_in: float = 2.0,
    music_fade_out: float = 3.0,
    duck_volume: float = 0.25,
    sync_beats: bool = False,
    bpm: float = 120.0,
    save_in_capcut: bool = True,
    verify: bool = True,
) -> dict[str, Any]:
    """
    Apply a publish-ready edit stack on disk, then sync CapCut + optional save shortcut.

    Order: captions → duck music → fade music → color grade → beat sync → CDP reload → save → verify.
    """
    from agent.actions import execute_action
    from capcut.cdp import sync_capcut
    from capcut.reader import get_project_summary
    from capcut.shortcuts import run_shortcut
    from capcut.verify import verify_project

    steps: list[dict[str, Any]] = []

    def _run(name: str, fn) -> None:
        try:
            detail = fn()
            steps.append({"step": name, "ok": True, "detail": detail})
        except Exception as exc:
            logger.warning("Pipeline step %s failed: %s", name, exc)
            steps.append({"step": name, "ok": False, "error": str(exc)})

    if captions:
        _run(
            "generate_captions",
            lambda: execute_action(
                "generate_captions",
                {"style": caption_style},
                project_path,
            ),
        )

    _run(
        "duck_audio",
        lambda: execute_action(
            "duck_audio",
            {"volume": duck_volume},
            project_path,
        ),
    )

    _run(
        "fade_project_music",
        lambda: execute_action(
            "fade_project_music",
            {"fade_in_sec": music_fade_in, "fade_out_sec": music_fade_out},
            project_path,
        ),
    )

    if color_preset:
        _run(
            "apply_color_preset",
            lambda: execute_action(
                "apply_color_preset",
                {"preset": color_preset},
                project_path,
            ),
        )

    if sync_beats:
        from capcut.writer import sync_video_to_beats

        _run(
            "sync_video_to_beats",
            lambda: sync_video_to_beats(project_path, bpm=bpm),
        )

    sync_result = sync_capcut(project_path)
    steps.append({"step": "cdp_sync", "ok": bool(sync_result.get("connected")), "detail": sync_result})

    if save_in_capcut:
        save = run_shortcut("save")
        steps.append({"step": "capcut_save_shortcut", "ok": save.get("success", False), "detail": save})

    summary = get_project_summary(project_path)
    verification = None
    if verify:
        expectations: dict[str, Any] = {
            "min_video_clips": 1,
        }
        if color_preset:
            expectations["filter_name"] = color_preset
        if captions:
            expectations["min_captions"] = 1
        verification = verify_project(project_path, expectations)
        steps.append({
            "step": "verify",
            "ok": verification.get("passed", False),
            "detail": verification,
        })

    failed = [s["step"] for s in steps if not s.get("ok")]
    return {
        "project_path": project_path,
        "success": len(failed) == 0,
        "failed_steps": failed,
        "steps": steps,
        "summary": {
            "duration_sec": summary.get("overview", {}).get("duration_sec"),
            "video_clips": summary.get("overview", {}).get("video_clip_count"),
            "captions": summary.get("overview", {}).get("text_overlay_count"),
        },
        "verification": verification,
    }


def bootstrap_and_edit(
    media_paths: list[str],
    *,
    project_name: str | None = None,
    photo_duration_sec: float = 3.0,
    **pipeline_kwargs: Any,
) -> dict[str, Any]:
    """Create project from media, then run the full edit pipeline."""
    from capcut.ingest import create_project_from_media

    created = create_project_from_media(
        media_paths,
        project_name=project_name,
        photo_duration_sec=photo_duration_sec,
    )
    pipeline = run_edit_pipeline(created["project_path"], **pipeline_kwargs)
    return {**created, "pipeline": pipeline}
