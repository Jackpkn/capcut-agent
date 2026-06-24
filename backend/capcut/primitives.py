"""Low-level CapCut draft primitives — keyframes, transforms, canvas.

Layer 3 building blocks for execute_capcut_script and specialist agents.
"""

from __future__ import annotations

import copy
import math
import uuid
from typing import Any

from capcut.reader import read_project
from capcut.writer import write_project

# CapCut keyframe property types (transform + mask + adjust).
KF_PROPERTIES: dict[str, str] = {
    "position_x": "KFTypePositionX",
    "position_y": "KFTypePositionY",
    "scale_x": "KFTypeScaleX",
    "scale_y": "KFTypeScaleY",
    "scale": "KFTypeScaleX",
    "rotation": "KFTypeRotation",
    "opacity": "KFTypeAlpha",
    "alpha": "KFTypeAlpha",
    "sharpen": "KFTypeSharpen",
    "mask_position_x": "KFTypeCommonMaskPositionX",
    "mask_position_y": "KFTypeCommonMaskPositionY",
    "mask_width": "KFTypeCommonMaskSizeWidth",
    "mask_height": "KFTypeCommonMaskSizeHeight",
    "mask_rotation": "KFTypeCommonMaskRotation",
    "mask_feather": "KFTypeCommonMaskFeather",
    "mask_round_corner": "KFTypeCommonMaskRoundCorner",
}


def _new_id() -> str:
    return str(uuid.uuid4()).upper()


def _find_segment(data: dict, segment_id: str) -> dict | None:
    for track in data.get("tracks", []):
        for seg in track.get("segments", []):
            if seg.get("id") == segment_id:
                return seg
    return None


def _resolve_property(property_name: str) -> str:
    key = property_name.strip()
    if key.startswith("KFType"):
        return key
    normalized = key.lower().replace("-", "_")
    if normalized not in KF_PROPERTIES:
        known = ", ".join(sorted(KF_PROPERTIES))
        raise ValueError(f"Unknown property '{property_name}'. Known: {known}")
    return KF_PROPERTIES[normalized]


def _keyframe_point(time_sec: float, value: float, curve: str = "Line") -> dict:
    return {
        "id": _new_id(),
        "curveType": curve,
        "time_offset": int(time_sec * 1_000_000),
        "left_control": {"x": 0.0, "y": 0.0},
        "right_control": {"x": 0.0, "y": 0.0},
        "values": [float(value)],
        "string_value": "",
        "graphID": "",
    }


def set_clip_transform(
    project_path: str,
    segment_id: str,
    *,
    scale: float | None = None,
    scale_x: float | None = None,
    scale_y: float | None = None,
    position_x: float | None = None,
    position_y: float | None = None,
    rotation: float | None = None,
    alpha: float | None = None,
) -> dict:
    """Set static clip transform (no keyframes) on a video/text segment."""
    data = read_project(project_path)
    seg = _find_segment(data, segment_id)
    if not seg:
        raise ValueError(f"Segment not found: {segment_id}")

    clip = seg.setdefault("clip", {})
    clip.setdefault("scale", {"x": 1.0, "y": 1.0})
    clip.setdefault("transform", {"x": 0.0, "y": 0.0})
    clip.setdefault("flip", {"vertical": False, "horizontal": False})

    sx = scale_x if scale_x is not None else scale
    sy = scale_y if scale_y is not None else scale
    if sx is not None:
        clip["scale"]["x"] = float(sx)
    if sy is not None:
        clip["scale"]["y"] = float(sy)
    if position_x is not None:
        clip["transform"]["x"] = float(position_x)
    if position_y is not None:
        clip["transform"]["y"] = float(position_y)
    if rotation is not None:
        clip["rotation"] = float(rotation)
    if alpha is not None:
        clip["alpha"] = float(alpha)

    write_project(project_path, data)
    return {"segment_id": segment_id, "clip": clip}


def add_keyframes(
    project_path: str,
    segment_id: str,
    property_name: str,
    keyframes: list[dict[str, float]],
    *,
    material_id: str = "",
    replace: bool = True,
) -> dict:
    """Add or replace a keyframe track on a segment.

    keyframes: [{"time_sec": 0.0, "value": 1.0}, {"time_sec": 1.0, "value": 1.2}]
    """
    if not keyframes:
        raise ValueError("keyframes list cannot be empty")

    property_type = _resolve_property(property_name)
    data = read_project(project_path)
    seg = _find_segment(data, segment_id)
    if not seg:
        raise ValueError(f"Segment not found: {segment_id}")

    track = {
        "id": _new_id(),
        "material_id": material_id,
        "property_type": property_type,
        "keyframe_list": [
            _keyframe_point(
                float(k["time_sec"]),
                float(k["value"]),
                str(k.get("curve", "Line")),
            )
            for k in keyframes
        ],
    }

    common = seg.setdefault("common_keyframes", [])
    if replace:
        common[:] = [t for t in common if t.get("property_type") != property_type]
    common.append(track)

    write_project(project_path, data)
    return {
        "segment_id": segment_id,
        "property_type": property_type,
        "keyframe_count": len(track["keyframe_list"]),
        "track_id": track["id"],
    }


def set_canvas(
    project_path: str,
    *,
    width: int | None = None,
    height: int | None = None,
    ratio: str | None = None,
    background: str | None = None,
) -> dict:
    """Update project canvas size / aspect ratio."""
    data = read_project(project_path)
    canvas = data.setdefault("canvas_config", {})
    if width is not None:
        canvas["width"] = int(width)
    if height is not None:
        canvas["height"] = int(height)
    if ratio is not None:
        canvas["ratio"] = ratio
    if background is not None:
        canvas["background"] = background
    write_project(project_path, data)
    return dict(canvas)


def zoom_pulse(
    project_path: str,
    segment_id: str,
    *,
    start_scale: float = 1.0,
    peak_scale: float = 1.15,
    duration_sec: float = 2.0,
) -> dict:
    """Ken Burns-style zoom pulse using scale keyframes."""
    mid = max(0.05, duration_sec / 2.0)
    return add_keyframes(
        project_path,
        segment_id,
        "scale_x",
        [
            {"time_sec": 0.0, "value": start_scale},
            {"time_sec": mid, "value": peak_scale},
            {"time_sec": duration_sec, "value": start_scale},
        ],
    )


def shake_segment(
    project_path: str,
    segment_id: str,
    *,
    intensity: float = 0.02,
    duration_sec: float = 0.5,
    steps: int = 8,
) -> dict:
    """Organic camera shake via position_x / position_y keyframes."""
    if steps < 2:
        raise ValueError("steps must be >= 2")

    xs: list[dict[str, float]] = []
    ys: list[dict[str, float]] = []
    for i in range(steps + 1):
        t = duration_sec * i / steps
        phase = i * 1.7
        xs.append({"time_sec": t, "value": math.sin(phase) * intensity})
        ys.append({"time_sec": t, "value": math.cos(phase * 1.3) * intensity})

    add_keyframes(project_path, segment_id, "position_x", xs)
    result = add_keyframes(project_path, segment_id, "position_y", ys)
    return {"segment_id": segment_id, "steps": steps, "intensity": intensity, **result}


def get_segment(project_path: str, segment_id: str) -> dict:
    data = read_project(project_path)
    seg = _find_segment(data, segment_id)
    if not seg:
        raise ValueError(f"Segment not found: {segment_id}")
    return copy.deepcopy(seg)
