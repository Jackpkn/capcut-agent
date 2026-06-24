"""Media ingest — import user clips into CapCut projects (Layer 3 bootstrap)."""

from __future__ import annotations

import copy
import json
import logging
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from capcut.reader import PROJECTS_PATH, get_all_projects, read_project
from capcut.writer import _new_id, _segment_template, write_project

logger = logging.getLogger(__name__)

UPLOAD_ROOT = Path.home() / ".capcut-agent" / "uploads"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac"}


def probe_media_file(path: str | Path) -> dict:
    """Return duration_us, width, height, media_type for a local file."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Media not found: {p}")

    ext = p.suffix.lower()
    if ext in IMAGE_EXT:
        media_type = "photo"
    elif ext in VIDEO_EXT:
        media_type = "video"
    elif ext in AUDIO_EXT:
        media_type = "audio"
    else:
        media_type = "video"

    duration_us = 3_000_000 if media_type == "photo" else 5_000_000
    width, height = 1080, 1920

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", str(p),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            fmt = data.get("format", {})
            if fmt.get("duration"):
                duration_us = int(float(fmt["duration"]) * 1_000_000)
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    width = int(stream.get("width") or width)
                    height = int(stream.get("height") or height)
                    break
    except Exception as exc:
        logger.warning("ffprobe failed for %s: %s", p, exc)

    return {
        "path": str(p),
        "name": p.name,
        "media_type": media_type,
        "duration_us": max(duration_us, 500_000),
        "width": width,
        "height": height,
    }


def _primary_video_track(data: dict) -> dict:
    for track in data.get("tracks", []):
        if track.get("type") == "video":
            return track
    track = {"id": _new_id(), "type": "video", "segments": [], "attribute": 0}
    data.setdefault("tracks", []).insert(0, track)
    return track


def _video_material_blueprint(data: dict) -> dict:
    for item in data.get("materials", {}).get("videos", []):
        if item.get("path"):
            return copy.deepcopy(item)
    return {
        "type": "video",
        "width": 1080,
        "height": 1920,
        "category_name": "local",
        "check_flag": 1,
        "source": 0,
        "source_platform": 0,
    }


def _timeline_end_us(data: dict, track_type: str = "video") -> int:
    end = 0
    for track in data.get("tracks", []):
        if track.get("type") != track_type:
            continue
        for seg in track.get("segments", []):
            tr = seg.get("target_timerange") or {}
            seg_end = int(tr.get("start", 0)) + int(tr.get("duration", 0))
            end = max(end, seg_end)
    return end


def clear_editable_timeline(data: dict) -> None:
    """Remove clips/effects/audio/text for a fresh import."""
    for track in data.get("tracks", []):
        if track.get("type") in ("video", "audio", "text", "effect", "filter"):
            track["segments"] = []

    materials = data.setdefault("materials", {})
    for key in (
        "videos", "audios", "texts", "transitions", "video_effects",
        "stickers", "audio_fades",
    ):
        if key in materials:
            materials[key] = []

    data["duration"] = 0


def add_media_clip(
    project_path: str,
    file_path: str,
    *,
    start_sec: float | None = None,
    duration_sec: float | None = None,
    track_index: int = 0,
) -> dict:
    """Append a local video/photo (or audio on audio track) to the timeline."""
    probe = probe_media_file(file_path)
    data = read_project(project_path)

    if probe["media_type"] == "audio":
        return _add_audio_clip(data, project_path, probe, start_sec, duration_sec)

    duration_us = int((duration_sec or probe["duration_us"] / 1_000_000) * 1_000_000)
    start_us = int((start_sec if start_sec is not None else _timeline_end_us(data) / 1_000_000) * 1_000_000)

    material_id = _new_id()
    segment_id = _new_id()
    blueprint = _video_material_blueprint(data)
    material = copy.deepcopy(blueprint)
    material.update({
        "id": material_id,
        "type": probe["media_type"],
        "path": probe["path"],
        "material_name": probe["name"],
        "name": probe["name"],
        "duration": probe["duration_us"],
        "width": probe["width"],
        "height": probe["height"],
    })
    data["materials"].setdefault("videos", []).append(material)

    seg_template = _segment_template(data, "video") or {
        "visible": True,
        "speed": 1.0,
        "volume": 1.0,
        "extra_material_refs": [],
        "clip": {
            "alpha": 1.0,
            "scale": {"x": 1.0, "y": 1.0},
            "transform": {"x": 0.0, "y": 0.0},
            "rotation": 0.0,
            "flip": {"vertical": False, "horizontal": False},
        },
    }
    segment = copy.deepcopy(seg_template)
    segment.update({
        "id": segment_id,
        "material_id": material_id,
        "target_timerange": {"start": start_us, "duration": duration_us},
        "source_timerange": {"start": 0, "duration": duration_us},
    })

    video_tracks = [t for t in data.get("tracks", []) if t.get("type") == "video"]
    if not video_tracks:
        video_tracks = [_primary_video_track(data)]
    track = video_tracks[min(track_index, len(video_tracks) - 1)]
    track.setdefault("segments", []).append(segment)

    total_end = _timeline_end_us(data)
    data["duration"] = max(int(data.get("duration") or 0), total_end)

    write_project(project_path, data)
    return {
        "segment_id": segment_id,
        "material_id": material_id,
        "name": probe["name"],
        "media_type": probe["media_type"],
        "at_sec": start_us / 1_000_000,
        "duration_sec": duration_us / 1_000_000,
    }


def _add_audio_clip(
    data: dict,
    project_path: str,
    probe: dict,
    start_sec: float | None,
    duration_sec: float | None,
) -> dict:
    audios = data.get("materials", {}).get("audios", [])
    template = copy.deepcopy(audios[0]) if audios else {
        "type": "extract_music",
        "category_name": "local",
        "source": 0,
        "source_platform": 0,
    }

    duration_us = int((duration_sec or probe["duration_us"] / 1_000_000) * 1_000_000)
    start_us = int((start_sec if start_sec is not None else 0) * 1_000_000)
    material_id = _new_id()
    segment_id = _new_id()

    template.update({
        "id": material_id,
        "name": probe["name"],
        "path": probe["path"],
        "duration": probe["duration_us"],
        "type": "extract_music",
    })
    data["materials"].setdefault("audios", []).append(template)

    audio_track = next((t for t in data.get("tracks", []) if t.get("type") == "audio"), None)
    if not audio_track:
        audio_track = {"id": _new_id(), "type": "audio", "segments": [], "attribute": 0}
        data.setdefault("tracks", []).append(audio_track)

    seg_template = _segment_template(data, "audio") or {"visible": True, "speed": 1.0, "volume": 1.0}
    segment = copy.deepcopy(seg_template)
    segment.update({
        "id": segment_id,
        "material_id": material_id,
        "target_timerange": {"start": start_us, "duration": duration_us},
        "source_timerange": {"start": 0, "duration": duration_us},
        "clip": None,
    })
    audio_track["segments"].append(segment)
    write_project(project_path, data)
    return {
        "segment_id": segment_id,
        "material_id": material_id,
        "name": probe["name"],
        "media_type": "audio",
        "at_sec": start_us / 1_000_000,
        "duration_sec": duration_us / 1_000_000,
    }


def import_clips(
    project_path: str,
    file_paths: list[str],
    *,
    photo_duration_sec: float = 3.0,
) -> dict:
    """Import multiple files sequentially on the primary video (or audio) track."""
    imported: list[dict] = []
    for path in file_paths:
        probe = probe_media_file(path)
        dur = photo_duration_sec if probe["media_type"] == "photo" else None
        imported.append(
            add_media_clip(project_path, path, duration_sec=dur)
        )
    summary_end = _timeline_end_us(read_project(project_path)) / 1_000_000
    return {
        "imported_count": len(imported),
        "clips": imported,
        "timeline_duration_sec": summary_end,
    }


def _pick_template_project() -> Path:
    projects = get_all_projects()
    if not projects:
        raise ValueError("No CapCut projects found to use as template — create one in CapCut first")
    # Prefer project 0610 (test project) or smallest by name
    for p in projects:
        if p.get("name") == "0610":
            return Path(p["path"])
    return Path(projects[-1]["path"])


def create_project_from_media(
    file_paths: list[str],
    *,
    project_name: str | None = None,
    photo_duration_sec: float = 3.0,
) -> dict:
    """Clone a template CapCut folder, clear timeline, import user media."""
    if not file_paths:
        raise ValueError("At least one media file is required")

    for fp in file_paths:
        if not Path(fp).expanduser().exists():
            raise FileNotFoundError(f"Media not found: {fp}")

    template_path = _pick_template_project()
    stamp = int(time.time())
    safe_name = (project_name or f"agent-{stamp}").strip().replace("/", "-")[:48]
    dest_path = PROJECTS_PATH / safe_name
    if dest_path.exists():
        safe_name = f"{safe_name}-{stamp}"
        dest_path = PROJECTS_PATH / safe_name

    def _ignore(dir_path: str, names: list[str]) -> list[str]:
        ignored = []
        for n in names:
            if n.startswith("draft_info.backup") or n.endswith(".bak"):
                ignored.append(n)
        return ignored

    shutil.copytree(template_path, dest_path, ignore=_ignore)

    new_draft_id = str(uuid.uuid4()).upper()
    meta_path = dest_path / "draft_meta_info.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        meta["draft_id"] = new_draft_id
        meta["draft_name"] = safe_name
        meta["draft_fold_path"] = str(dest_path)
        meta["tm_draft_modified"] = int(time.time() * 1_000_000)
        meta["tm_draft_create"] = meta["tm_draft_modified"]
        meta_path.write_text(json.dumps(meta, indent=2))

    data = read_project(str(dest_path))
    data["id"] = new_draft_id
    data["name"] = safe_name
    clear_editable_timeline(data)
    write_project(str(dest_path), data)

    import_result = import_clips(
        str(dest_path),
        file_paths,
        photo_duration_sec=photo_duration_sec,
    )

    return {
        "project_id": new_draft_id,
        "project_name": safe_name,
        "project_path": str(dest_path),
        "template_used": str(template_path),
        **import_result,
    }


def save_upload(file_name: str, content: bytes) -> str:
    """Persist an uploaded file; return absolute path."""
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    session_dir = UPLOAD_ROOT / str(int(time.time()))
    session_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file_name).name.replace("..", "_")
    dest = session_dir / safe_name
    dest.write_bytes(content)
    return str(dest.resolve())
