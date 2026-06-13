"""Clean and repair draft JSON so CapCut accepts edits on next open."""

from __future__ import annotations

import json
from pathlib import Path


def _material_index(data: dict) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for key, items in data.get("materials", {}).items():
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                lookup[item["id"]] = key
    return lookup


def sanitize_transitions(data: dict) -> int:
    """Keep one transition ref per segment; drop orphan transition materials."""
    transition_ids = {t["id"] for t in data["materials"].get("transitions", [])}
    if not transition_ids:
        return 0

    removed_refs = 0
    for track in data.get("tracks", []):
        for segment in track.get("segments", []):
            refs = segment.get("extra_material_refs", [])
            seen_transition = False
            cleaned: list[str] = []
            for ref in refs:
                if ref in transition_ids:
                    if seen_transition:
                        removed_refs += 1
                        continue
                    seen_transition = True
                cleaned.append(ref)
            segment["extra_material_refs"] = cleaned

    referenced = set()
    for track in data.get("tracks", []):
        for segment in track.get("segments", []):
            referenced.update(segment.get("extra_material_refs", []))

    before = len(data["materials"].get("transitions", []))
    data["materials"]["transitions"] = [
        t for t in data["materials"].get("transitions", [])
        if t["id"] in referenced
    ]
    return removed_refs + (before - len(data["materials"]["transitions"]))


def dedupe_audio_tracks(data: dict) -> int:
    """Keep one segment per unique audio material name on the music track."""
    removed = 0
    for track in data.get("tracks", []):
        if track.get("type") != "audio":
            continue
        seen_names: set[str] = set()
        kept = []
        audio_by_id = {a["id"]: a for a in data["materials"].get("audios", [])}
        for segment in track.get("segments", []):
            audio = audio_by_id.get(segment.get("material_id", ""), {})
            name = audio.get("name") or segment.get("id", "")
            if name in seen_names:
                removed += 1
                continue
            seen_names.add(name)
            kept.append(segment)
        track["segments"] = kept
    return removed


def repair_draft_data(data: dict) -> dict:
    sanitize_transitions(data)
    dedupe_audio_tracks(data)
    return data


def load_best_draft_source(project_path: str) -> tuple[dict, str]:
    """Prefer CapCut's .bak (pre-repair) or our agent backup with the most edits."""
    base = Path(project_path)
    candidates: list[tuple[Path, dict, int]] = []

    for pattern in ("draft_info.json.bak", "draft_info.backup_*.json"):
        for path in sorted(base.glob(pattern), reverse=True):
            try:
                data = json.loads(path.read_text())
                score = len(data["materials"].get("transitions", []))
                score += sum(
                    1 for t in data.get("tracks", [])
                    if t.get("type") == "video"
                    for s in t.get("segments", [])
                    if s.get("speed", 1) != 1
                )
                candidates.append((path, data, score))
            except (json.JSONDecodeError, OSError):
                continue

    timelines = base / "Timelines"
    if timelines.is_dir():
        for folder in timelines.iterdir():
            bak = folder / "draft_info.json.bak"
            if bak.exists():
                try:
                    data = json.loads(bak.read_text())
                    score = len(data["materials"].get("transitions", []))
                    score += sum(
                        1 for t in data.get("tracks", [])
                        if t.get("type") == "video"
                        for s in t.get("segments", [])
                        if s.get("speed", 1) != 1
                    )
                    candidates.append((bak, data, score))
                except (json.JSONDecodeError, OSError):
                    pass

    if not candidates:
        data = json.loads((base / "draft_info.json").read_text())
        return data, "draft_info.json"

    candidates.sort(key=lambda x: x[2], reverse=True)
    best_path, best_data, _ = candidates[0]
    return best_data, best_path.name
