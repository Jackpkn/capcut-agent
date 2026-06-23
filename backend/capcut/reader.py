import json
from pathlib import Path

PROJECTS_PATH = Path.home() / "Movies/CapCut/User Data/Projects/com.lveditor.draft"
MICROSECONDS = 1_000_000


def _parse_text_content(content: str, recognize_text: str = "") -> str:
    if recognize_text:
        return recognize_text
    if not content:
        return ""
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "text" in data:
            return data["text"]
        if isinstance(data, dict) and "styles" in data:
            return data.get("text", "")
    except (json.JSONDecodeError, TypeError):
        pass
    return content


def _to_seconds(microseconds: int | None) -> float:
    if microseconds is None:
        return 0.0
    return round(microseconds / MICROSECONDS, 2)


def _index_materials(data: dict) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for items in data.get("materials", {}).values():
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    lookup[item["id"]] = item
    return lookup


def _resolve_text_entry(segment: dict, materials: dict, texts: list) -> tuple[dict | None, str | None]:
    material_id = segment.get("material_id")
    texts_by_id = {t["id"]: t for t in texts}

    if material_id in texts_by_id:
        return texts_by_id[material_id], material_id

    if len(texts) == 1:
        return texts[0], texts[0]["id"]

    template = materials.get(material_id)
    if template and template.get("type") == "text_template":
        for ref in segment.get("extra_material_refs", []):
            if ref in texts_by_id:
                return texts_by_id[ref], ref

    return None, None


def _build_text_overlays(data: dict) -> list[dict]:
    materials = _index_materials(data)
    texts = data.get("materials", {}).get("texts", [])
    overlays = []

    for track_index, track in enumerate(data.get("tracks", [])):
        if track.get("type") != "text":
            continue
        for segment in track.get("segments", []):
            text_entry, edit_id = _resolve_text_entry(segment, materials, texts)
            timerange = segment.get("target_timerange") or {}
            template = materials.get(segment.get("material_id", ""))
            overlays.append({
                "index": len(overlays) + 1,
                "text_id": edit_id,
                "segment_id": segment["id"],
                "content": _parse_text_content(
                    text_entry.get("content", "") if text_entry else "",
                    text_entry.get("recognize_text", "") if text_entry else "",
                ),
                "at_sec": _to_seconds(timerange.get("start")),
                "duration_sec": _to_seconds(timerange.get("duration")),
                "track_index": track_index,
                "template_name": template.get("name") if template else None,
            })

    overlays.sort(key=lambda o: o["at_sec"])
    for i, overlay in enumerate(overlays, 1):
        overlay["index"] = i
    return overlays


def _build_video_clips(data: dict) -> list[dict]:
    materials = _index_materials(data)
    transitions_by_id = {t["id"]: t for t in data.get("materials", {}).get("transitions", [])}
    clips = []

    for track_index, track in enumerate(data.get("tracks", [])):
        if track.get("type") != "video":
            continue
        for segment in track.get("segments", []):
            video = materials.get(segment.get("material_id", ""), {})
            timerange = segment.get("target_timerange") or {}
            transition_ids = {
                ref for ref in segment.get("extra_material_refs", [])
                if ref in transitions_by_id
            }
            transition_name = None
            if transition_ids:
                t = transitions_by_id.get(next(iter(transition_ids)))
                if t:
                    transition_name = t.get("name")
            clips.append({
                "index": len(clips) + 1,
                "segment_id": segment["id"],
                "material_id": segment.get("material_id"),
                "name": video.get("material_name") or video.get("name") or "Clip",
                "at_sec": _to_seconds(timerange.get("start")),
                "duration_sec": _to_seconds(timerange.get("duration")),
                "speed": segment.get("speed", 1.0),
                "volume": segment.get("volume", 1.0),
                "track_index": track_index,
                "transition": transition_name,
            })

    clips.sort(key=lambda c: c["at_sec"])
    for i, clip in enumerate(clips, 1):
        clip["index"] = i
    return clips


def _build_audio_clips(data: dict) -> list[dict]:
    materials = _index_materials(data)
    clips = []

    for track in data.get("tracks", []):
        if track.get("type") != "audio":
            continue
        for segment in track.get("segments", []):
            audio = materials.get(segment.get("material_id", ""), {})
            timerange = segment.get("target_timerange") or {}
            clips.append({
                "segment_id": segment["id"],
                "name": audio.get("name") or "Audio",
                "at_sec": _to_seconds(timerange.get("start")),
                "duration_sec": _to_seconds(timerange.get("duration")),
                "volume": segment.get("volume", 1.0),
            })

    return sorted(clips, key=lambda c: c["at_sec"])


def get_all_projects():
    if not PROJECTS_PATH.exists():
        return []
    projects = []
    for folder in PROJECTS_PATH.iterdir():
        if not folder.is_dir():
            continue
        meta_file = folder / "draft_meta_info.json"
        if meta_file.exists():
            with open(meta_file) as f:
                meta = json.load(f)
            projects.append({
                "id": meta.get("draft_id"),
                "name": meta.get("draft_name"),
                "path": str(folder),
                "modified": meta.get("tm_draft_modified"),
            })
    return sorted(projects, key=lambda p: p.get("modified") or 0, reverse=True)


def get_draft_write_paths(project_path: str) -> list[Path]:
    """All draft_info.json files that must stay in sync (root + Timelines/*)."""
    base = Path(project_path)
    paths: list[Path] = []
    root = base / "draft_info.json"
    if root.exists():
        paths.append(root)
    timelines = base / "Timelines"
    if timelines.is_dir():
        for folder in timelines.iterdir():
            if folder.is_dir():
                tl = folder / "draft_info.json"
                if tl.exists() and tl not in paths:
                    paths.append(tl)
    return paths


def read_project(project_path: str):
    from capcut.writer import get_batch_state

    batch = get_batch_state(project_path)
    if batch is not None:
        return batch

    draft_file = Path(project_path) / "draft_info.json"
    with open(draft_file) as f:
        return json.load(f)


def list_video_segments_for_captions(data: dict) -> list[dict]:
    """Video segments with paths and source/timeline timing for Whisper caption sync."""
    materials = _index_materials(data)
    clips = []

    for track_index, track in enumerate(data.get("tracks", [])):
        if track.get("type") != "video":
            continue
        for segment in track.get("segments", []):
            video = materials.get(segment.get("material_id", ""), {})
            path = video.get("path", "")
            if not path:
                continue
            target = segment.get("target_timerange") or {}
            source = segment.get("source_timerange") or {}
            speed = segment.get("speed") or 1.0
            duration_sec = _to_seconds(target.get("duration"))
            source_duration = _to_seconds(source.get("duration"))
            if not source_duration:
                source_duration = duration_sec * speed
            clips.append({
                "segment_id": segment["id"],
                "material_id": segment.get("material_id"),
                "path": path,
                "name": video.get("material_name") or video.get("name") or "Clip",
                "at_sec": _to_seconds(target.get("start")),
                "duration_sec": duration_sec,
                "source_start_sec": _to_seconds(source.get("start")),
                "source_duration_sec": source_duration,
                "speed": speed,
                "track_index": track_index,
            })

    clips.sort(key=lambda c: (c["at_sec"], c["track_index"]))
    return clips


def get_project_summary(project_path: str):
    data = read_project(project_path)
    text_overlays = _build_text_overlays(data)
    video_clips = _build_video_clips(data)
    audio_clips = _build_audio_clips(data)

    return {
        "overview": {
            "duration_sec": _to_seconds(data.get("duration")),
            "fps": data.get("fps"),
            "text_overlay_count": len(text_overlays),
            "video_clip_count": len(video_clips),
            "audio_clip_count": len(audio_clips),
            "transition_count": len(data["materials"].get("transitions", [])),
            "effect_count": len(data["materials"].get("video_effects", [])),
        },
        "text_overlays": text_overlays,
        "video_clips": video_clips,
        "audio_clips": audio_clips,
        "transitions": [
            {
                "id": t["id"],
                "name": t["name"],
                "duration_sec": _to_seconds(t.get("duration")),
            }
            for t in data["materials"].get("transitions", [])
        ],
        "effects": [
            {
                "id": e["id"],
                "name": e["name"],
                "type": e.get("type"),
            }
            for e in data["materials"].get("video_effects", [])
        ],
    }
