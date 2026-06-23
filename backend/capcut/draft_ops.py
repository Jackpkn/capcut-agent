"""Generic CapCut draft operations — one executor for many timeline edits."""

from __future__ import annotations

import copy
import logging
from typing import Any

from capcut.draft_repair import sanitize_transitions
from capcut.writer import (
    add_effect,
    add_music,
    add_transition,
    batch_edits,
    batch_update_texts,
    remove_effect,
    reorder_clips,
    replace_music,
    _new_id,
    _update_segment_speed,
    update_clip_speed,
    update_text,
    update_transition,
    update_volume,
)

logger = logging.getLogger(__name__)

MICROSECONDS = 1_000_000

IN_BATCH_OPS = frozenset({
    "segment.split",
    "segment.delete",
    "segment.set",
    "segment.move",
    "segment.trim",
    "segment.hide",
    "segment.show",
    "transition.remove",
})

LEGACY_BRIDGE_OPS = frozenset({
    "transition.add",
    "effect.add",
    "text.update",
    "text.batch_update",
    "clip.speed",
    "clip.volume",
    "clip.reorder",
    "music.add",
    "music.replace",
    "effect.remove",
    "transition.update",
})


def _sec_to_us(sec: float) -> int:
    return int(sec * MICROSECONDS)


def _locate_segment(data: dict, segment_id: str) -> tuple[dict, int, dict] | None:
    for track in data.get("tracks", []):
        segments = track.get("segments", [])
        for idx, seg in enumerate(segments):
            if seg.get("id") == segment_id:
                return track, idx, seg
    return None


def _describe_op(op: dict) -> str:
    name = op.get("op", "unknown")
    if name == "segment.split":
        return f"Split clip at {op.get('at_sec')}s"
    if name == "segment.delete":
        return f"Delete segment {str(op.get('segment_id', ''))[:8]}…"
    if name == "segment.set":
        return f"Set {op.get('field')} on segment"
    if name == "transition.add":
        return f"Add transition «{op.get('query', op.get('name', ''))}»"
    if name == "transition.remove":
        return "Remove transition from clip"
    if name == "text.update":
        return f'Update text to "{str(op.get("content", ""))[:40]}"'
    return name


def describe_operations(operations: list[dict]) -> str:
    if not operations:
        return "No operations"
    lines = [_describe_op(o) for o in operations[:6]]
    if len(operations) > 6:
        lines.append(f"…and {len(operations) - 6} more")
    return "; ".join(lines)


def _split_segment(data: dict, segment_id: str, at_sec: float) -> str:
    located = _locate_segment(data, segment_id)
    if not located:
        raise ValueError(f"Segment not found: {segment_id}")
    track, idx, seg = located
    target = seg.get("target_timerange") or {}
    source = seg.get("source_timerange") or {}
    seg_start = int(target.get("start", 0))
    seg_dur = int(target.get("duration", 0))
    split_us = _sec_to_us(at_sec) - seg_start
    if split_us <= 0 or split_us >= seg_dur:
        raise ValueError(f"Split at {at_sec}s is outside segment range")

    speed = float(seg.get("speed") or 1.0)
    src_start = int(source.get("start", 0))
    src_dur = int(source.get("duration", seg_dur))

    seg["target_timerange"]["duration"] = split_us
    seg["source_timerange"]["duration"] = int(split_us * speed)

    new_seg = copy.deepcopy(seg)
    new_seg["id"] = _new_id()
    new_seg["target_timerange"] = {
        "start": seg_start + split_us,
        "duration": seg_dur - split_us,
    }
    new_seg["source_timerange"] = {
        "start": src_start + int(split_us * speed),
        "duration": src_dur - int(split_us * speed),
    }
    track["segments"].insert(idx + 1, new_seg)
    return f"Split segment at {at_sec:.2f}s → two clips"


def _delete_segment(data: dict, segment_id: str) -> str:
    located = _locate_segment(data, segment_id)
    if not located:
        raise ValueError(f"Segment not found: {segment_id}")
    track, idx, _ = located
    track["segments"].pop(idx)
    return f"Deleted segment {segment_id[:8]}…"


def _set_segment_field(data: dict, segment_id: str, field: str, value: Any) -> str:
    located = _locate_segment(data, segment_id)
    if not located:
        raise ValueError(f"Segment not found: {segment_id}")
    _, _, seg = located
    field = field.lower()
    if field == "speed":
        _update_segment_speed(data, seg, float(value))
        return f"Set speed to {value}x"
    if field == "volume":
        vol = float(value)
        seg["volume"] = vol
        seg["last_nonzero_volume"] = vol
        return f"Set volume to {vol}"
    if field == "visible":
        seg["visible"] = bool(value)
        return f"Segment visible={bool(value)}"
    if field.startswith("clip."):
        clip = seg.setdefault("clip", {})
        clip[field.split(".", 1)[1]] = value
        return f"Updated {field}"
    raise ValueError(f"Unsupported segment field: {field}")


def _move_segment_in_batch(data: dict, segment_id: str, start_sec: float, duration_sec: float | None) -> str:
    located = _locate_segment(data, segment_id)
    if not located:
        raise ValueError(f"Segment not found: {segment_id}")
    _, _, seg = located
    seg["target_timerange"]["start"] = _sec_to_us(start_sec)
    if duration_sec is not None:
        seg["target_timerange"]["duration"] = _sec_to_us(duration_sec)
    return f"Moved segment to {start_sec}s"


def _trim_segment_in_batch(data: dict, segment_id: str, duration_sec: float) -> str:
    located = _locate_segment(data, segment_id)
    if not located:
        raise ValueError(f"Segment not found: {segment_id}")
    _, _, seg = located
    dur_us = _sec_to_us(duration_sec)
    seg["target_timerange"]["duration"] = dur_us
    if seg.get("source_timerange"):
        speed = float(seg.get("speed") or 1.0)
        seg["source_timerange"]["duration"] = int(dur_us * speed)
    return f"Trimmed segment to {duration_sec}s"


def _remove_transition_from_segment(data: dict, segment_id: str) -> str:
    located = _locate_segment(data, segment_id)
    if not located:
        raise ValueError(f"Segment not found: {segment_id}")
    _, _, seg = located
    transition_ids = {t["id"] for t in data["materials"].get("transitions", [])}
    refs = seg.get("extra_material_refs", [])
    removed = [r for r in refs if r in transition_ids]
    seg["extra_material_refs"] = [r for r in refs if r not in transition_ids]
    if removed:
        referenced = {
            ref
            for track in data.get("tracks", [])
            for s in track.get("segments", [])
            for ref in s.get("extra_material_refs", [])
        }
        data["materials"]["transitions"] = [
            t for t in data["materials"].get("transitions", [])
            if t["id"] in referenced
        ]
    sanitize_transitions(data)
    return "Removed transition from clip" if removed else "No transition on clip"


def _apply_in_batch(data: dict, op: dict) -> str:
    name = op.get("op", "")
    segment_id = op.get("segment_id", "")

    if name == "segment.split":
        return _split_segment(data, segment_id, float(op["at_sec"]))
    if name == "segment.delete":
        return _delete_segment(data, segment_id)
    if name == "segment.set":
        return _set_segment_field(data, segment_id, op["field"], op.get("value"))
    if name == "segment.move":
        return _move_segment_in_batch(
            data, segment_id, float(op["start_sec"]), op.get("duration_sec"),
        )
    if name == "segment.trim":
        return _trim_segment_in_batch(data, segment_id, float(op["duration_sec"]))
    if name == "segment.hide":
        return _set_segment_field(data, segment_id, "visible", False)
    if name == "segment.show":
        return _set_segment_field(data, segment_id, "visible", True)
    if name == "transition.remove":
        return _remove_transition_from_segment(data, segment_id)

    raise ValueError(f"Unknown in-batch op: {name}")


def _apply_via_legacy(project_path: str, op: dict) -> str:
    name = op.get("op", "")

    if name == "transition.add":
        result = add_transition(
            project_path,
            segment_id=op["segment_id"],
            resource_id=op.get("resource_id"),
            name=op.get("name"),
            query=op.get("query"),
            duration_us=_sec_to_us(op["duration_sec"]) if op.get("duration_sec") else None,
        )
        if result.get("unchanged"):
            return f'Transition "{result["name"]}" already on clip'
        if result.get("replaced"):
            old = result.get("replaced_name") or "previous transition"
            return f'Replaced "{old}" with "{result["name"]}"'
        return f'Added transition "{result["name"]}"'

    if name == "effect.add":
        result = add_effect(
            project_path,
            resource_id=op.get("resource_id"),
            name=op.get("name"),
            query=op.get("query"),
            start_sec=float(op.get("start_sec", 0)),
            duration_sec=op.get("duration_sec"),
            bind_segment_id=op.get("segment_id"),
        )
        return f'Added effect "{result["name"]}"'

    if name == "text.update":
        from agent.actions import _build_text_content, _get_existing_text_content

        existing = _get_existing_text_content(project_path, op["text_id"])
        content = _build_text_content(op["content"], existing)
        update_text(project_path, op["text_id"], content)
        return f'Updated text'

    if name == "text.batch_update":
        from agent.actions import _build_text_content, _get_existing_text_content

        updates = []
        for item in op.get("updates", []):
            existing = _get_existing_text_content(project_path, item["text_id"])
            updates.append({
                "text_id": item["text_id"],
                "content": _build_text_content(item["content"], existing),
            })
        batch_update_texts(project_path, updates)
        return f"Updated {len(updates)} text overlay(s)"

    if name == "clip.speed":
        update_clip_speed(project_path, op["segment_id"], float(op["speed"]))
        return f"Set speed to {op['speed']}x"

    if name == "clip.volume":
        update_volume(project_path, op["segment_id"], float(op["volume"]))
        return f"Set volume to {op['volume']}"

    if name == "clip.reorder":
        reorder_clips(project_path, op["segment_id_a"], op["segment_id_b"])
        return "Swapped clip positions"

    if name == "effect.remove":
        remove_effect(project_path, op["effect_id"])
        return "Removed effect"

    if name == "transition.update":
        update_transition(
            project_path,
            op["transition_id"],
            duration=_sec_to_us(op["duration_sec"]) if op.get("duration_sec") else None,
            name=op.get("name"),
        )
        return "Updated transition"

    if name in ("music.add", "music.replace"):
        from agent.actions import execute_action

        action = "add_music" if name == "music.add" else "replace_music"
        return execute_action(action, op, project_path)

    raise ValueError(f"Unknown legacy op: {name}")


def apply_draft_operations(project_path: str, operations: list[dict]) -> list[str]:
    """Apply a list of draft ops. Structural edits batch; catalog ops run after flush."""
    if not operations:
        return []

    batch_ops = [o for o in operations if o.get("op") in IN_BATCH_OPS]
    legacy_ops = [o for o in operations if o.get("op") in LEGACY_BRIDGE_OPS]
    unknown = [
        o for o in operations
        if o.get("op") not in IN_BATCH_OPS and o.get("op") not in LEGACY_BRIDGE_OPS
    ]

    results: list[str] = []

    if batch_ops:
        with batch_edits(project_path) as data:
            for op in batch_ops:
                results.append(_apply_in_batch(data, op))

    for op in legacy_ops:
        results.append(_apply_via_legacy(project_path, op))

    for op in unknown:
        raise ValueError(f"Unsupported operation: {op.get('op')}")

    return results


def supported_operations() -> list[str]:
    return sorted(IN_BATCH_OPS | LEGACY_BRIDGE_OPS)
