import copy
import json
import logging
import shutil
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from capcut.catalog import asset_exists_on_disk, find_bundle_path, get_asset
from capcut.downloader import ensure_asset_cached
from capcut.reader import PROJECTS_PATH, get_draft_write_paths, read_project

logger = logging.getLogger(__name__)

_batch_state: dict | None = None
_batch_path: str | None = None


def get_batch_state(project_path: str) -> dict | None:
    if _batch_path == str(project_path) and _batch_state is not None:
        return _batch_state
    return None


@contextmanager
def batch_edits(project_path: str):
    """Apply many edits in memory, then write once to all draft files."""
    global _batch_state, _batch_path
    _batch_path = str(project_path)
    draft_file = Path(project_path) / "draft_info.json"
    with open(draft_file) as f:
        _batch_state = json.load(f)
    try:
        yield _batch_state
    finally:
        if _batch_state is not None:
            _flush_project(project_path, _batch_state)
        _batch_state = None
        _batch_path = None


def backup_project(project_path: str) -> str:
    draft_file = Path(project_path) / "draft_info.json"
    backup_file = Path(project_path) / (
        f"draft_info.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    shutil.copy2(draft_file, backup_file)
    return str(backup_file)


def _touch_meta_modified(project_path: str) -> None:
    meta_file = Path(project_path) / "draft_meta_info.json"
    if not meta_file.exists():
        return
    try:
        meta = json.loads(meta_file.read_text())
        meta["tm_draft_modified"] = int(time.time() * 1_000_000)
        meta_file.write_text(json.dumps(meta, indent=2))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not update draft_meta_info.json: %s", e)


def _flush_project(project_path: str, data: dict) -> bool:
    from capcut.draft_repair import repair_draft_data

    repair_draft_data(data)
    paths = get_draft_write_paths(project_path)
    if not paths:
        raise FileNotFoundError(f"No draft_info.json under {project_path}")

    backup_project(project_path)
    payload = json.dumps(data, indent=2)
    for draft_file in paths:
        draft_file.write_text(payload)
        logger.info("Wrote %s", draft_file)

    _touch_meta_modified(project_path)
    return True


def write_project(project_path: str, data: dict) -> bool:
    global _batch_state, _batch_path
    if _batch_path == str(project_path) and _batch_state is not None:
        _batch_state = data
        return True
    return _flush_project(project_path, data)


def _update_segment_speed(data: dict, seg: dict, speed: float) -> None:
    seg["speed"] = speed
    speed_by_id = {s["id"]: s for s in data["materials"].get("speeds", [])}
    updated = False
    for ref in seg.get("extra_material_refs", []):
        if ref in speed_by_id:
            speed_by_id[ref]["speed"] = speed
            updated = True
    if not updated:
        speed_id = _new_id()
        data["materials"].setdefault("speeds", []).append({
            "id": speed_id,
            "type": "speed",
            "mode": 0,
            "speed": speed,
            "curve_speed": None,
        })
        seg.setdefault("extra_material_refs", []).append(speed_id)


def _segment_has_transition(data: dict, seg: dict) -> bool:
    transition_ids = {t["id"] for t in data["materials"].get("transitions", [])}
    return any(ref in transition_ids for ref in seg.get("extra_material_refs", []))


def _attach_transition_ref(seg: dict, transition_id: str) -> None:
    """Insert transition ref where CapCut expects it (after speeds + placeholder_infos)."""
    refs = seg.setdefault("extra_material_refs", [])
    if transition_id in refs:
        return
    refs.insert(min(2, len(refs)), transition_id)


def _find_segment(data: dict, segment_id: str) -> dict | None:
    for track in data["tracks"]:
        for seg in track["segments"]:
            if seg["id"] == segment_id:
                return seg
    return None


def update_transition(
    project_path: str,
    transition_id: str,
    duration: int | None = None,
    name: str | None = None,
):
    data = read_project(project_path)
    for t in data["materials"]["transitions"]:
        if t["id"] == transition_id:
            if duration is not None:
                t["duration"] = duration
            if name is not None:
                t["name"] = name
    write_project(project_path, data)
    return data


def update_text(project_path: str, text_id: str, new_content: str):
    data = read_project(project_path)
    for t in data["materials"]["texts"]:
        if t["id"] == text_id:
            t["content"] = new_content
    write_project(project_path, data)
    return data


def batch_update_texts(project_path: str, updates: list[dict]):
    data = read_project(project_path)
    by_id = {t["id"]: t for t in data["materials"]["texts"]}
    for item in updates:
        text = by_id.get(item["text_id"])
        if text:
            text["content"] = item["content"]
    write_project(project_path, data)
    return data


def update_clip_speed(project_path: str, segment_id: str, speed: float):
    data = read_project(project_path)
    seg = _find_segment(data, segment_id)
    if not seg:
        raise ValueError(f"Video segment not found: {segment_id}")
    _update_segment_speed(data, seg, speed)
    write_project(project_path, data)
    return data


def update_volume(project_path: str, segment_id: str, volume: float):
    data = read_project(project_path)
    seg = _find_segment(data, segment_id)
    if seg:
        seg["volume"] = volume
        seg["last_nonzero_volume"] = volume
    write_project(project_path, data)
    return data


def trim_clip(
    project_path: str,
    segment_id: str,
    start: int | None = None,
    duration: int | None = None,
):
    data = read_project(project_path)
    seg = _find_segment(data, segment_id)
    if seg:
        if start is not None:
            seg["source_timerange"]["start"] = start
            seg["target_timerange"]["start"] = start
        if duration is not None:
            seg["source_timerange"]["duration"] = duration
            seg["target_timerange"]["duration"] = duration
    write_project(project_path, data)
    return data


def move_segment(
    project_path: str,
    segment_id: str,
    start: int,
    duration: int | None = None,
):
    data = read_project(project_path)
    seg = _find_segment(data, segment_id)
    if seg:
        seg["target_timerange"]["start"] = start
        if duration is not None:
            seg["target_timerange"]["duration"] = duration
    write_project(project_path, data)
    return data


def set_segment_visibility(project_path: str, segment_id: str, visible: bool):
    data = read_project(project_path)
    seg = _find_segment(data, segment_id)
    if seg:
        seg["visible"] = visible
    write_project(project_path, data)
    return data


def remove_effect(project_path: str, effect_id: str):
    data = read_project(project_path)
    effects = data["materials"].get("video_effects", [])
    data["materials"]["video_effects"] = [e for e in effects if e["id"] != effect_id]

    for track in data["tracks"]:
        if track.get("type") == "effect":
            track["segments"] = [
                seg for seg in track["segments"] if seg.get("material_id") != effect_id
            ]

    write_project(project_path, data)
    return data


def _new_id() -> str:
    return str(uuid.uuid4()).upper()


def _find_material_template(
    material_key: str,
    resource_id: str,
    project_path: str | None = None,
) -> dict | None:
    search_paths = []
    if project_path:
        search_paths.append(Path(project_path) / "draft_info.json")
    if PROJECTS_PATH.exists():
        for folder in PROJECTS_PATH.iterdir():
            draft = folder / "draft_info.json"
            if draft.exists() and draft not in search_paths:
                search_paths.append(draft)

    for draft in search_paths:
        try:
            data = json.loads(draft.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for item in data.get("materials", {}).get(material_key, []):
            if str(item.get("resource_id")) == str(resource_id) or str(item.get("effect_id")) == str(resource_id):
                return copy.deepcopy(item)
        if material_key == "text_templates":
            for tmpl in data.get("materials", {}).get("text_templates", []):
                for res in tmpl.get("resources", []):
                    if str(res.get("resource_id")) == str(resource_id) and res.get("panel") == "sticker":
                        return copy.deepcopy(tmpl)
    return None


def _segment_template(data: dict, track_type: str) -> dict | None:
    for track in data.get("tracks", []):
        if track.get("type") == track_type and track.get("segments"):
            return copy.deepcopy(track["segments"][0])
    return None


def _resolve_asset(params: dict, asset_type: str, project_path: str | None = None) -> dict:
    asset = None
    if params.get("resource_id"):
        asset = get_asset(resource_id=str(params["resource_id"]), asset_type=asset_type)
    if not asset and params.get("name"):
        asset = get_asset(name=params["name"], asset_type=asset_type)
    if not asset and params.get("query"):
        asset = get_asset(name=params["query"], asset_type=asset_type)
    
    if not asset:
        # Fallback logic to prevent crash when specific transition/effect/etc is not found in local catalog
        from capcut.catalog import search_catalog
        if asset_type == "transition":
            hits = search_catalog("", "transition", limit=20)
            if hits:
                query_str = (params.get("query") or params.get("name") or "").lower()
                matched = None
                if query_str:
                    for h in hits:
                        if h.get("name") and any(word in h["name"].lower() for word in query_str.split()):
                            matched = h
                            break
                asset = matched or hits[0]
                logger.warning(f"Transition '{params}' not found in catalog. Using fallback: '{asset['name']}' ({asset['resource_id']})")
        elif asset_type == "effect":
            hits = search_catalog("", "effect", limit=20)
            if hits:
                query_str = (params.get("query") or params.get("name") or "").lower()
                matched = None
                if query_str:
                    for h in hits:
                        if h.get("name") and any(word in h["name"].lower() for word in query_str.split()):
                            matched = h
                            break
                asset = matched or hits[0]
                logger.warning(f"Effect '{params}' not found in catalog. Using fallback: '{asset['name']}' ({asset['resource_id']})")
        elif asset_type == "sticker":
            hits = search_catalog("", "sticker", limit=1)
            if hits:
                asset = hits[0]
                logger.warning(f"Sticker '{params}' not found in catalog. Using fallback: '{asset['name']}' ({asset['resource_id']})")
        elif asset_type == "text_template":
            hits = search_catalog("", "text_template", limit=1)
            if hits:
                asset = hits[0]
                logger.warning(f"Text template '{params}' not found in catalog. Using fallback: '{asset['name']}' ({asset['resource_id']})")

    if not asset:
        raise ValueError(f"{asset_type} not found in catalog: {params}")

    if asset_exists_on_disk(asset):
        path = asset.get("path")
        if not path or not Path(path).exists():
            path = find_bundle_path(str(asset["resource_id"]), asset["type"])
            if path:
                asset["path"] = path
                asset["cached"] = True
        return asset

    return ensure_asset_cached(asset, project_path=project_path)


def add_transition(
    project_path: str,
    segment_id: str,
    resource_id: str | None = None,
    name: str | None = None,
    query: str | None = None,
    duration_us: int | None = None,
):
    params = {"resource_id": resource_id, "name": name, "query": query}
    asset = _resolve_asset({k: v for k, v in params.items() if v}, "transition", project_path)
    data = read_project(project_path)

    template = _find_material_template("transitions", asset["resource_id"], project_path)
    if not template:
        template = {
            "type": "transition",
            "effect_id": asset["resource_id"],
            "resource_id": asset["resource_id"],
            "third_resource_id": asset["resource_id"],
            "source_platform": 1,
            "platform": "all",
            "category_name": asset.get("category_name") or "Transitions",
            "is_overlap": asset.get("is_overlap", False),
            "is_ai_transition": False,
            "video_path": "",
            "task_id": "",
        }

    transition_id = _new_id()
    material = copy.deepcopy(template)
    material.update({
        "id": transition_id,
        "name": asset["name"],
        "path": asset["path"],
        "effect_id": asset["resource_id"],
        "resource_id": asset["resource_id"],
        "third_resource_id": asset["resource_id"],
        "duration": duration_us or asset.get("duration_us") or template.get("duration") or 66666,
    })
    data["materials"].setdefault("transitions", []).append(material)

    seg = _find_segment(data, segment_id)
    if not seg:
        raise ValueError(f"Video segment not found: {segment_id}")
    if _segment_has_transition(data, seg):
        return {"transition_id": None, "name": asset["name"], "segment_id": segment_id, "skipped": True}
    _attach_transition_ref(seg, transition_id)

    write_project(project_path, data)
    return {"transition_id": transition_id, "name": asset["name"], "segment_id": segment_id}


def add_effect(
    project_path: str,
    resource_id: str | None = None,
    name: str | None = None,
    query: str | None = None,
    start_sec: float = 0,
    duration_sec: float | None = None,
    bind_segment_id: str | None = None,
):
    params = {"resource_id": resource_id, "name": name, "query": query}
    asset = _resolve_asset({k: v for k, v in params.items() if v}, "effect", project_path)
    data = read_project(project_path)

    template = _find_material_template("video_effects", asset["resource_id"], project_path)
    if not template:
        template = {
            "type": "video_effect",
            "sub_type": 0,
            "bind_segment_id": bind_segment_id or "",
            "transparent_params": "",
            "value": 1.0,
            "platform": "all",
            "apply_target_type": 2,
            "source_platform": 1,
            "adjust_params": [],
            "common_keyframes": [],
            "enable_mask": True,
            "effect_mask": [],
        }

    material_id = _new_id()
    segment_id = _new_id()
    duration_us = int((duration_sec or 3.0) * 1_000_000)
    start_us = int(start_sec * 1_000_000)

    material = copy.deepcopy(template)
    material.update({
        "id": material_id,
        "name": asset["name"],
        "path": asset["path"],
        "effect_id": asset["resource_id"],
        "resource_id": asset["resource_id"],
        "category_name": asset.get("category_name") or template.get("category_name"),
    })
    if bind_segment_id:
        material["bind_segment_id"] = bind_segment_id
    data["materials"].setdefault("video_effects", []).append(material)

    seg_template = _segment_template(data, "effect")
    if not seg_template:
        seg_template = {
            "desc": "",
            "state": 0,
            "speed": 1.0,
            "is_loop": False,
            "visible": True,
            "volume": 1.0,
            "last_nonzero_volume": 1.0,
            "extra_material_refs": [],
            "keyframe_refs": [],
            "render_index": 11001,
            "track_render_index": 1,
            "track_attribute": 0,
            "template_scene": "default",
            "enable_color_curves": True,
            "enable_hsl_curves": True,
            "enable_color_wheels": True,
        }

    segment = copy.deepcopy(seg_template)
    segment.update({
        "id": segment_id,
        "material_id": material_id,
        "source_timerange": None,
        "target_timerange": {"start": start_us, "duration": duration_us},
        "render_timerange": {"start": 0, "duration": 0},
    })

    effect_track = next((t for t in data["tracks"] if t.get("type") == "effect"), None)
    if not effect_track:
        effect_track = {"type": "effect", "segments": [], "attribute": 0}
        data["tracks"].append(effect_track)
    effect_track["segments"].append(segment)

    write_project(project_path, data)
    return {"material_id": material_id, "segment_id": segment_id, "name": asset["name"]}


def add_sticker(
    project_path: str,
    resource_id: str | None = None,
    name: str | None = None,
    query: str | None = None,
    start_sec: float = 0,
    duration_sec: float = 3.0,
):
    params = {"resource_id": resource_id, "name": name, "query": query}
    asset = _resolve_asset({k: v for k, v in params.items() if v}, "sticker", project_path)
    data = read_project(project_path)

    material_id = _new_id()
    segment_id = _new_id()
    start_us = int(start_sec * 1_000_000)
    duration_us = int(duration_sec * 1_000_000)

    sticker_material = {
        "id": material_id,
        "type": "sticker",
        "name": asset["name"],
        "path": asset["path"],
        "resource_id": asset["resource_id"],
        "effect_id": asset["resource_id"],
        "source_platform": 1,
        "platform": "all",
    }
    data["materials"].setdefault("stickers", []).append(sticker_material)

    seg_template = _segment_template(data, "sticker") or _segment_template(data, "video") or {
        "desc": "",
        "state": 0,
        "speed": 1.0,
        "visible": True,
        "volume": 1.0,
        "last_nonzero_volume": 1.0,
        "clip": {
            "scale": {"x": 1.0, "y": 1.0},
            "rotation": 0.0,
            "transform": {"x": 0.0, "y": 0.0},
            "flip": {"vertical": False, "horizontal": False},
            "alpha": 1.0,
        },
        "uniform_scale": {"on": True, "value": 1.0},
        "extra_material_refs": [],
        "keyframe_refs": [],
        "render_index": 0,
    }

    segment = copy.deepcopy(seg_template)
    segment.update({
        "id": segment_id,
        "material_id": material_id,
        "source_timerange": None,
        "target_timerange": {"start": start_us, "duration": duration_us},
        "render_timerange": {"start": 0, "duration": 0},
    })

    sticker_track = next((t for t in data["tracks"] if t.get("type") == "sticker"), None)
    if not sticker_track:
        sticker_track = {"type": "sticker", "segments": [], "attribute": 0}
        data["tracks"].append(sticker_track)
    sticker_track["segments"].append(segment)

    write_project(project_path, data)
    return {"material_id": material_id, "segment_id": segment_id, "name": asset["name"]}


def add_text_template(
    project_path: str,
    resource_id: str | None = None,
    name: str | None = None,
    query: str | None = None,
    start_sec: float = 0,
    duration_sec: float = 3.0,
    text_content: str | None = None,
):
    params = {"resource_id": resource_id, "name": name, "query": query}
    asset = _resolve_asset({k: v for k, v in params.items() if v}, "text_template", project_path)
    data = read_project(project_path)

    template = _find_material_template("text_templates", asset["resource_id"], project_path)
    if not template:
        template = {
            "version": "1.0.0",
            "type": "text_template",
            "third_resource_id": "",
            "platform": "all",
            "text_to_audio_ids": [],
            "source_platform": 1,
            "resources": [],
            "text_template_resource_type": "text_template",
        }

    material_id = _new_id()
    segment_id = _new_id()
    text_id = _new_id()
    start_us = int(start_sec * 1_000_000)
    duration_us = int(duration_sec * 1_000_000)

    material = copy.deepcopy(template)
    material.update({
        "id": material_id,
        "name": asset["name"],
        "path": asset["path"],
        "effect_id": asset["resource_id"],
        "resource_id": asset["resource_id"],
        "category_name": asset.get("category_name") or template.get("category_name"),
    })
    data["materials"].setdefault("text_templates", []).append(material)

    if text_content:
        data["materials"].setdefault("texts", []).append({
            "id": text_id,
            "type": "text",
            "name": "",
            "content": json.dumps({
                "text": text_content,
                "styles": [{
                    "fill": {"content": {"solid": {"color": [1, 1, 1]}, "render_type": "solid"}},
                    "range": [0, len(text_content)],
                    "size": 15,
                }],
            }),
        })

    seg_template = _segment_template(data, "text") or {
        "desc": "",
        "state": 0,
        "speed": 1.0,
        "visible": True,
        "volume": 1.0,
        "last_nonzero_volume": 1.0,
        "clip": {
            "scale": {"x": 1.0, "y": 1.0},
            "rotation": 0.0,
            "transform": {"x": 0.0, "y": 0.0},
            "flip": {"vertical": False, "horizontal": False},
            "alpha": 1.0,
        },
        "uniform_scale": {"on": True, "value": 1.0},
        "extra_material_refs": [text_id] if text_content else [],
        "keyframe_refs": [],
        "render_index": 0,
    }

    segment = copy.deepcopy(seg_template)
    segment.update({
        "id": segment_id,
        "material_id": material_id,
        "source_timerange": None,
        "target_timerange": {"start": start_us, "duration": duration_us},
        "render_timerange": {"start": 0, "duration": 0},
    })
    if text_content and text_id not in segment.get("extra_material_refs", []):
        segment.setdefault("extra_material_refs", []).append(text_id)

    text_track = next((t for t in data["tracks"] if t.get("type") == "text"), None)
    if not text_track:
        text_track = {"type": "text", "segments": [], "attribute": 0}
        data["tracks"].append(text_track)
    text_track["segments"].append(segment)

    write_project(project_path, data)
    return {"material_id": material_id, "segment_id": segment_id, "name": asset["name"]}


CAPCUT_SYSTEM_FONT = (
    "/Applications/CapCut.app/Contents/Resources/Font/SystemFont/en.ttf"
)


def _build_subtitle_content(text: str, font_size: float = 10.0) -> str:
    return json.dumps({
        "styles": [{
            "fill": {
                "alpha": 1.0,
                "content": {
                    "render_type": "solid",
                    "solid": {"alpha": 1.0, "color": [1.0, 1.0, 1.0]},
                },
            },
            "font": {"id": "", "path": CAPCUT_SYSTEM_FONT},
            "range": [0, len(text)],
            "size": font_size,
        }],
        "text": text,
    })


def _find_visible_text_blueprint(
    project_path: str | None = None,
) -> tuple[dict, dict, dict, list[dict], list[dict]]:
    """Clone a working CapCut text overlay (full template resources + text_info_resources)."""
    search_paths: list[Path] = []
    if project_path:
        search_paths.append(Path(project_path) / "draft_info.json")
    if PROJECTS_PATH.exists():
        for folder in PROJECTS_PATH.iterdir():
            draft = folder / "draft_info.json"
            if draft.exists() and draft not in search_paths:
                search_paths.append(draft)

    for draft in search_paths:
        try:
            data = json.loads(draft.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        templates = {t["id"]: t for t in data.get("materials", {}).get("text_templates", [])}
        texts = {t["id"]: t for t in data.get("materials", {}).get("texts", [])}
        anims = {a["id"]: a for a in data.get("materials", {}).get("material_animations", [])}
        effects = {e["id"]: e for e in data.get("materials", {}).get("effects", [])}

        for track in data.get("tracks", []):
            if track.get("type") != "text":
                continue
            for seg in track.get("segments", []):
                tpl = templates.get(seg.get("material_id", ""))
                if not tpl or len(tpl.get("resources", [])) < 3:
                    continue
                if not tpl.get("text_info_resources"):
                    continue
                text_id = tpl["text_info_resources"][0].get("text_material_id")
                text = texts.get(text_id or "")
                if not text:
                    continue
                seg_anims = [copy.deepcopy(anims[r]) for r in seg.get("extra_material_refs", []) if r in anims]
                seg_effects = [copy.deepcopy(effects[r]) for r in seg.get("extra_material_refs", []) if r in effects]
                return (
                    copy.deepcopy(tpl),
                    copy.deepcopy(text),
                    copy.deepcopy(seg),
                    seg_anims,
                    seg_effects,
                )

    raise ValueError(
        "No renderable text template found. Add any styled text once in CapCut (project 0602 works) and save."
    )


def _build_styled_text_content(text: str, font_size: float = 24.0) -> str:
    return json.dumps({
        "styles": [{
            "fill": {
                "content": {
                    "solid": {"color": [1, 1, 1]},
                    "render_type": "solid",
                },
            },
            "range": [0, len(text)],
            "size": font_size,
        }],
        "text": text,
    })


def _find_subtitle_blueprint(
    project_path: str | None = None,
) -> tuple[dict, dict, dict, dict]:
    """Clone native CapCut auto-caption structure (type=subtitle, not text_template)."""
    search_paths: list[Path] = []
    preferred = PROJECTS_PATH / "0605" / "draft_info.json"
    if preferred.exists():
        search_paths.append(preferred)
    if project_path:
        root = Path(project_path) / "draft_info.json"
        if root.exists() and root not in search_paths:
            search_paths.append(root)
    if PROJECTS_PATH.exists():
        for folder in sorted(PROJECTS_PATH.iterdir()):
            draft = folder / "draft_info.json"
            if draft.exists() and draft not in search_paths:
                search_paths.append(draft)

    for draft in search_paths:
        try:
            data = json.loads(draft.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        subtitles = {
            t["id"]: t
            for t in data.get("materials", {}).get("texts", [])
            if t.get("type") == "subtitle"
        }
        if not subtitles:
            continue
        subtitle_track = None
        for track in data.get("tracks", []):
            if track.get("type") != "text":
                continue
            for seg in track.get("segments", []):
                text = subtitles.get(seg.get("material_id", ""))
                if not text:
                    continue
                anim = {
                    "type": "sticker_animation",
                    "animations": [],
                    "multi_language_current": "none",
                }
                for ref in seg.get("extra_material_refs", []):
                    for item in data.get("materials", {}).get("material_animations", []):
                        if item.get("id") == ref:
                            anim = copy.deepcopy(item)
                            break
                if track.get("flag") == 1:
                    subtitle_track = copy.deepcopy(track)
                return (
                    copy.deepcopy(text),
                    copy.deepcopy(seg),
                    anim,
                    subtitle_track or copy.deepcopy(track),
                )

    text_material = {
        "recognize_task_id": "",
        "name": "",
        "recognize_model": "",
        "punc_model": "",
        "type": "subtitle",
        "words": {"start_time": [], "end_time": [], "text": []},
        "current_words": {"start_time": [], "end_time": [], "text": []},
        "global_alpha": 1.0,
        "combo_info": {"text_templates": []},
        "caption_template_info": {
            "resource_id": "",
            "third_resource_id": "",
            "resource_name": "",
            "category_id": "",
            "category_name": "",
            "effect_id": "",
            "request_id": "",
            "path": "",
            "is_new": False,
            "source_platform": 0,
        },
        "layer_weight": 1,
        "letter_spacing": 0.0,
        "line_spacing": 0.02,
        "has_shadow": False,
        "shadow_alpha": 0.9,
        "shadow_smoothing": 0.45,
        "shadow_distance": 5.0,
        "shadow_point": {"x": 0.6363961030678928, "y": -0.6363961030678927},
        "shadow_angle": -45.0,
        "border_alpha": 1.0,
        "border_width": 0.08,
        "text_color": "#FFFFFF",
        "text_alpha": 1.0,
        "font_title": "none",
        "font_size": 10.0,
        "font_path": CAPCUT_SYSTEM_FONT,
        "alignment": 1,
        "line_feed": 1,
        "use_effect_default_color": True,
        "check_flag": 7,
        "text_size": 30,
        "add_type": 1,
        "operation_type": 0,
        "recognize_type": 0,
        "line_max_width": 0.82,
        "language": "en-US",
        "multi_language_current": "none",
        "source_from": "capcut_agent",
    }
    segment = {
        "desc": "",
        "state": 0,
        "speed": 1.0,
        "visible": True,
        "volume": 1.0,
        "last_nonzero_volume": 1.0,
        "clip": {
            "scale": {"x": 1.0, "y": 1.0},
            "rotation": 0.0,
            "transform": {"x": 0.0, "y": -0.56},
            "flip": {"vertical": False, "horizontal": False},
            "alpha": 1.0,
        },
        "uniform_scale": {"on": True, "value": 1.0},
        "keyframe_refs": [],
        "render_index": 14000,
        "track_attribute": 0,
        "template_scene": "default",
        "source": "segmentsourcenormal",
    }
    animation = {
        "type": "sticker_animation",
        "animations": [],
        "multi_language_current": "none",
    }
    subtitle_track = {
        "id": _new_id(),
        "type": "text",
        "flag": 1,
        "attribute": 0,
        "name": "",
        "is_default_name": True,
        "segments": [],
    }
    return text_material, segment, animation, subtitle_track


def _subtitle_text_track(data: dict, track_blueprint: dict | None = None) -> dict:
    texts_by_id = {t["id"]: t for t in data.get("materials", {}).get("texts", [])}
    for track in data.get("tracks", []):
        if track.get("type") != "text":
            continue
        if track.get("flag") == 1:
            return track
        segments = track.get("segments", [])
        if segments and all(
            texts_by_id.get(seg.get("material_id", ""), {}).get("type") == "subtitle"
            for seg in segments
        ):
            track["flag"] = 1
            track.setdefault("id", _new_id())
            track.setdefault("is_default_name", True)
            return track
    track = copy.deepcopy(track_blueprint) if track_blueprint else {
        "type": "text",
        "flag": 1,
        "attribute": 0,
        "name": "",
        "is_default_name": True,
        "segments": [],
    }
    track["id"] = _new_id()
    track["segments"] = []
    data["tracks"].append(track)
    return track


def _styled_text_track(data: dict) -> dict:
    for track in data.get("tracks", []):
        if track.get("type") == "text" and track.get("flag", 0) != 1 and not track.get("segments"):
            return track
    track = {
        "id": _new_id(),
        "type": "text",
        "flag": 0,
        "attribute": 0,
        "name": "",
        "is_default_name": True,
        "segments": [],
    }
    data["tracks"].append(track)
    return track


def clear_whisper_captions(data: dict) -> int:
    """Remove broken text_template overlays and prior whisper subtitles before re-apply."""
    texts_by_id = {t["id"]: t for t in data.get("materials", {}).get("texts", [])}
    template_ids = {t["id"] for t in data.get("materials", {}).get("text_templates", [])}
    removed_seg_ids: set[str] = set()
    removed_text_ids: set[str] = set()
    removed_anim_ids: set[str] = set()
    removed_effect_ids: set[str] = set()
    used_template_ids: set[str] = set()
    effect_ids = {e["id"] for e in data.get("materials", {}).get("effects", [])}

    for track in data.get("tracks", []):
        if track.get("type") != "text":
            continue
        kept = []
        for seg in track.get("segments", []):
            mid = seg.get("material_id", "")
            text = texts_by_id.get(mid)
            is_template_overlay = mid in template_ids
            is_whisper_subtitle = text and text.get("type") == "subtitle"
            is_agent_text = text and text.get("source_from") == "capcut_agent"
            if not is_template_overlay and not is_whisper_subtitle and not is_agent_text:
                kept.append(seg)
                continue
            removed_seg_ids.add(seg["id"])
            if is_template_overlay:
                used_template_ids.add(mid)
                for tpl in data.get("materials", {}).get("text_templates", []):
                    if tpl.get("id") != mid:
                        continue
                    for res in tpl.get("text_info_resources", []):
                        tid = res.get("text_material_id")
                        if tid:
                            removed_text_ids.add(tid)
            if is_whisper_subtitle or is_agent_text:
                removed_text_ids.add(mid)
            for ref in seg.get("extra_material_refs", []):
                if ref in texts_by_id:
                    removed_text_ids.add(ref)
                elif ref in effect_ids:
                    removed_effect_ids.add(ref)
                else:
                    removed_anim_ids.add(ref)
        track["segments"] = kept

    orphan_template_ids = used_template_ids.copy()
    for track in data.get("tracks", []):
        if track.get("type") != "text":
            continue
        for seg in track.get("segments", []):
            orphan_template_ids.discard(seg.get("material_id", ""))

    data["materials"]["texts"] = [
        t for t in data.get("materials", {}).get("texts", [])
        if t.get("id") not in removed_text_ids
    ]
    data["materials"]["text_templates"] = [
        t for t in data.get("materials", {}).get("text_templates", [])
        if t.get("id") not in orphan_template_ids
    ]
    data["materials"]["material_animations"] = [
        a for a in data.get("materials", {}).get("material_animations", [])
        if a.get("id") not in removed_anim_ids
    ]
    data["materials"]["effects"] = [
        e for e in data.get("materials", {}).get("effects", [])
        if e.get("id") not in removed_effect_ids
    ]
    data["tracks"] = [
        t for t in data.get("tracks", [])
        if not (t.get("type") == "text" and not t.get("segments"))
    ]
    return len(removed_seg_ids)


def count_visible_captions(data: dict) -> int:
    texts_by_id = {t["id"]: t for t in data.get("materials", {}).get("texts", [])}
    templates = {t["id"]: t for t in data.get("materials", {}).get("text_templates", [])}
    count = 0
    for track in data.get("tracks", []):
        if track.get("type") != "text":
            continue
        for seg in track.get("segments", []):
            mid = seg.get("material_id", "")
            text = texts_by_id.get(mid)
            if text and text.get("type") == "subtitle":
                count += 1
                continue
            tpl = templates.get(mid)
            if tpl and tpl.get("text_info_resources") and len(tpl.get("resources", [])) >= 3:
                count += 1
    return count


def add_visible_text_caption(
    project_path: str,
    text_content: str,
    start_sec: float = 0,
    duration_sec: float = 2.5,
    font_size: float = 24.0,
):
    """Add caption using a full CapCut text template (resources + text_info_resources)."""
    data = read_project(project_path)
    tpl_b, text_b, seg_b, anims_b, effects_b = _find_visible_text_blueprint(project_path)

    text_id = _new_id()
    template_id = _new_id()
    segment_id = _new_id()
    start_us = int(start_sec * 1_000_000)
    duration_us = int(duration_sec * 1_000_000)
    content = _build_styled_text_content(text_content, font_size)

    text_material = copy.deepcopy(text_b)
    text_material.update({
        "id": text_id,
        "type": "text",
        "name": _new_id(),
        "content": content,
        "base_content": content,
        "font_size": font_size,
        "source_from": "capcut_agent",
    })
    data["materials"].setdefault("texts", []).append(text_material)

    extra_refs: list[str] = []
    for anim in anims_b:
        item = copy.deepcopy(anim)
        item["id"] = _new_id()
        data["materials"].setdefault("material_animations", []).append(item)
        extra_refs.append(item["id"])
    for effect in effects_b:
        item = copy.deepcopy(effect)
        item["id"] = _new_id()
        data["materials"].setdefault("effects", []).append(item)
        extra_refs.append(item["id"])
    if not extra_refs:
        anim_id = _new_id()
        data["materials"].setdefault("material_animations", []).append({
            "id": anim_id,
            "type": "sticker_animation",
            "animations": [],
            "multi_language_current": "none",
        })
        extra_refs.append(anim_id)

    template = copy.deepcopy(tpl_b)
    template["id"] = template_id
    if template.get("text_info_resources"):
        tir = copy.deepcopy(template["text_info_resources"][0])
        tir["id"] = _new_id()
        tir["text_material_id"] = text_id
        tir["extra_material_refs"] = extra_refs[:2] if len(extra_refs) >= 2 else extra_refs
        attach = tir.setdefault("attach_info", {})
        attach["start_time"] = 0
        attach["duration"] = duration_us
        clip = attach.setdefault("clip", {})
        clip["scale"] = {"x": 1.2, "y": 1.2}
        clip["transform"] = {"x": 0.0, "y": -0.65}
        template["text_info_resources"] = [tir]
    data["materials"].setdefault("text_templates", []).append(template)

    segment = copy.deepcopy(seg_b)
    segment.update({
        "id": segment_id,
        "material_id": template_id,
        "source_timerange": None,
        "target_timerange": {"start": start_us, "duration": duration_us},
        "render_timerange": {"start": 0, "duration": 0},
        "extra_material_refs": extra_refs,
    })
    segment.setdefault("clip", {}).setdefault("transform", {})["y"] = -0.56

    text_track = _styled_text_track(data)
    text_track["segments"].append(segment)
    write_project(project_path, data)
    return {"text_id": text_id, "segment_id": segment_id, "content": text_content}


def _subtitle_word_timings(
    text_content: str,
    start_sec: float,
    duration_sec: float,
    word_entries: list[dict] | None = None,
) -> dict:
    if word_entries:
        return {
            "start_time": [
                max(0, int((w["start"] - start_sec) * 1_000_000))
                for w in word_entries
            ],
            "end_time": [
                max(0, int((w["end"] - start_sec) * 1_000_000))
                for w in word_entries
            ],
            "text": [w.get("word", "") for w in word_entries],
        }
    duration_us = int(duration_sec * 1_000_000)
    return {"start_time": [0], "end_time": [duration_us], "text": [text_content]}


def add_subtitle_caption(
    project_path: str,
    text_content: str,
    start_sec: float = 0,
    duration_sec: float = 2.5,
    font_size: float = 12.0,
    group_id: str | None = None,
    render_index: int | None = None,
    word_entries: list[dict] | None = None,
    timeline_start_sec: float | None = None,
):
    """Add a visible on-screen caption using CapCut's native subtitle material type."""
    data = read_project(project_path)
    text_blueprint, seg_blueprint, anim_blueprint, track_blueprint = _find_subtitle_blueprint(
        project_path
    )

    text_id = _new_id()
    segment_id = _new_id()
    anim_id = _new_id()
    speech_base = timeline_start_sec if timeline_start_sec is not None else start_sec
    start_us = int(start_sec * 1_000_000)
    duration_us = int(duration_sec * 1_000_000)
    content = _build_subtitle_content(text_content, font_size)
    word_timings = _subtitle_word_timings(
        text_content,
        speech_base,
        duration_sec,
        word_entries,
    )

    text_material = copy.deepcopy(text_blueprint)
    text_material.update({
        "id": text_id,
        "type": "subtitle",
        "recognize_task_id": "",
        "recognize_text": text_content,
        "content": content,
        "base_content": content,
        "font_path": CAPCUT_SYSTEM_FONT,
        "font_size": font_size,
        "text_size": 30,
        "text_color": "#FFFFFF",
        "border_alpha": 1.0,
        "border_width": 0.08,
        "alignment": 1,
        "group_id": group_id or f"en-US_{int(time.time() * 1000)}",
        "source_from": "capcut_agent",
        "words": word_timings,
    })
    data["materials"].setdefault("texts", []).append(text_material)

    animation = copy.deepcopy(anim_blueprint)
    animation["id"] = anim_id
    data["materials"].setdefault("material_animations", []).append(animation)

    segment = copy.deepcopy(seg_blueprint)
    segment.update({
        "id": segment_id,
        "material_id": text_id,
        "source_timerange": None,
        "target_timerange": {"start": start_us, "duration": duration_us},
        "render_timerange": {"start": 0, "duration": 0},
        "extra_material_refs": [anim_id],
        "visible": True,
        "render_index": render_index if render_index is not None else 14004,
    })
    clip = segment.setdefault("clip", {})
    clip["alpha"] = 1.0
    clip.setdefault("transform", {})["x"] = 0.0
    clip["transform"]["y"] = -0.56

    text_track = _subtitle_text_track(data, track_blueprint)
    text_track["segments"].append(segment)

    write_project(project_path, data)
    return {"text_id": text_id, "segment_id": segment_id, "content": text_content}


def add_text_overlay(
    project_path: str,
    text_content: str,
    start_sec: float = 0,
    duration_sec: float = 2.5,
    font_size: int = 18,
    group_id: str | None = None,
    render_index: int | None = None,
    word_entries: list[dict] | None = None,
    timeline_start_sec: float | None = None,
):
    """Whisper captions — native CapCut subtitles (same format as Auto Captions)."""
    return add_subtitle_caption(
        project_path,
        text_content=text_content,
        start_sec=start_sec,
        duration_sec=duration_sec,
        font_size=float(font_size) * 0.65,
        group_id=group_id,
        render_index=render_index,
        word_entries=word_entries,
        timeline_start_sec=timeline_start_sec,
    )


def _is_background_music_name(name: str) -> bool:
    return bool(name) and not name.upper().startswith("VID_")


def _mute_background_music_segments(data: dict) -> int:
    """Remove non-camera music segments so replace does not stack extra beds."""
    materials: dict[str, dict] = {}
    for items in data.get("materials", {}).values():
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    materials[item["id"]] = item

    removed = 0
    for track in data.get("tracks", []):
        if track.get("type") != "audio":
            continue
        kept: list[dict] = []
        for seg in track.get("segments", []):
            mat = materials.get(seg.get("material_id", ""), {})
            name = mat.get("name") or mat.get("material_name") or ""
            if _is_background_music_name(name):
                removed += 1
                continue
            kept.append(seg)
        track["segments"] = kept
    return removed


def _append_music_to_data(
    data: dict,
    music_path: str,
    name: str,
    duration_us: int,
    start_sec: float = 0,
    clip_duration_sec: float | None = None,
    volume: float = 0.8,
) -> dict:
    audios = data["materials"].get("audios", [])
    if not audios:
        raise ValueError("No audio template in project — add music manually in CapCut once first")

    template = copy.deepcopy(audios[0])
    material_id = _new_id()
    segment_id = _new_id()

    start_us = int(start_sec * 1_000_000)
    if clip_duration_sec is not None:
        clip_us = int(clip_duration_sec * 1_000_000)
    else:
        # Calculate maximum end time of any video clip on the timeline
        video_duration_us = 0
        for track in data.get("tracks", []):
            if track.get("type") == "video":
                for segment in track.get("segments", []):
                    timerange = segment.get("target_timerange") or {}
                    start = timerange.get("start") or 0
                    duration = timerange.get("duration") or 0
                    end = start + duration
                    if end > video_duration_us:
                        video_duration_us = end
        
        if video_duration_us > start_us and (video_duration_us - start_us) >= 1_000_000:
            calc_duration_us = video_duration_us - start_us
            clip_us = min(duration_us, calc_duration_us)
            logger.info(f"Auto-trimmed music to match video duration: {clip_us / 1_000_000}s (video end: {video_duration_us / 1_000_000}s)")
        else:
            clip_us = duration_us

    template.update({
        "id": material_id,
        "name": name,
        "path": music_path,
        "duration": duration_us,
        "type": "music",
    })
    data["materials"]["audios"].append(template)

    seg_template = None
    for track in data["tracks"]:
        if track.get("type") == "audio" and track.get("segments"):
            seg_template = copy.deepcopy(track["segments"][0])
            break

    if not seg_template:
        raise ValueError("No audio track template found in project")

    seg_template.update({
        "id": segment_id,
        "material_id": material_id,
        "speed": 1.0,
        "volume": volume,
        "last_nonzero_volume": volume,
        "source_timerange": {"start": 0, "duration": clip_us},
        "target_timerange": {"start": start_us, "duration": clip_us},
    })

    for track in data["tracks"]:
        if track.get("type") == "audio":
            track["segments"].append(seg_template)
            break

    return {"material_id": material_id, "segment_id": segment_id, "name": name}


def add_music(
    project_path: str,
    music_path: str,
    name: str,
    duration_us: int,
    start_sec: float = 0,
    clip_duration_sec: float | None = None,
    volume: float = 0.8,
):
    data = read_project(project_path)
    result = _append_music_to_data(
        data, music_path, name, duration_us, start_sec, clip_duration_sec, volume
    )
    write_project(project_path, data)
    return result


def replace_music(
    project_path: str,
    music_path: str,
    name: str,
    duration_us: int,
    start_sec: float = 0,
    clip_duration_sec: float | None = None,
    volume: float = 0.8,
):
    """Mute existing background music and add a new track."""
    data = read_project(project_path)
    muted = _mute_background_music_segments(data)
    result = _append_music_to_data(
        data, music_path, name, duration_us, start_sec, clip_duration_sec, volume
    )
    write_project(project_path, data)
    return {**result, "muted_tracks": muted}


def reorder_clips(project_path: str, segment_id_a: str, segment_id_b: str):
    data = read_project(project_path)
    seg_a = _find_segment(data, segment_id_a)
    seg_b = _find_segment(data, segment_id_b)
    if not seg_a or not seg_b:
        raise ValueError(f"Could not find segments to reorder: {segment_id_a}, {segment_id_b}")

    for track in data["tracks"]:
        segments = track["segments"]
        idx_a = next((i for i, s in enumerate(segments) if s["id"] == segment_id_a), None)
        idx_b = next((i for i, s in enumerate(segments) if s["id"] == segment_id_b), None)
        if idx_a is not None and idx_b is not None:
            segments[idx_a], segments[idx_b] = segments[idx_b], segments[idx_a]
            write_project(project_path, data)
            return data

    a_start = seg_a["target_timerange"]["start"]
    b_start = seg_b["target_timerange"]["start"]
    seg_a["target_timerange"]["start"] = b_start
    seg_b["target_timerange"]["start"] = a_start
    write_project(project_path, data)
    return data
