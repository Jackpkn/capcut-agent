"""Shared session memory — all agents read/write to stay consistent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionMemory:
    """Cross-agent context for one edit session (in-memory; persisted on EditSession)."""

    style_brief: str = ""
    preset_id: str = ""
    music_direction: str = ""
    caption_direction: str = ""
    constraints: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    catalog_picks: dict[str, str] = field(default_factory=dict)
    human_preferences: list[str] = field(default_factory=list)
    completed_edits: list[dict[str, Any]] = field(default_factory=list)
    chapter_notes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "style_brief": self.style_brief,
            "preset_id": self.preset_id,
            "music_direction": self.music_direction,
            "caption_direction": self.caption_direction,
            "constraints": self.constraints,
            "avoid": self.avoid,
            "catalog_picks": self.catalog_picks,
            "human_preferences": self.human_preferences,
            "completed_edits": self.completed_edits[-50:],
            "chapter_notes": self.chapter_notes,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> SessionMemory:
        if not data:
            return cls()
        return cls(
            style_brief=data.get("style_brief", ""),
            preset_id=data.get("preset_id", ""),
            music_direction=data.get("music_direction", ""),
            caption_direction=data.get("caption_direction", ""),
            constraints=list(data.get("constraints", [])),
            avoid=list(data.get("avoid", [])),
            catalog_picks=dict(data.get("catalog_picks", {})),
            human_preferences=list(data.get("human_preferences", [])),
            completed_edits=list(data.get("completed_edits", [])),
            chapter_notes=dict(data.get("chapter_notes", {})),
        )

    def apply_brief(self, brief_data: dict) -> None:
        self.preset_id = brief_data.get("preset_id", self.preset_id)
        self.music_direction = brief_data.get("music_direction", self.music_direction)
        self.caption_direction = brief_data.get("caption_direction", self.caption_direction)
        notes = brief_data.get("creative_notes") or []
        if notes:
            self.style_brief = "; ".join(notes[:5])

    def record_edit(self, *, chapter_id: str, action: str, description: str, at_sec: float | None = None) -> None:
        self.completed_edits.append({
            "chapter_id": chapter_id,
            "action": action,
            "description": description,
            "at_sec": at_sec,
        })

    def record_chapter_planned(self, chapter_id: str, task_count: int, notes: str = "") -> None:
        self.chapter_notes[chapter_id] = f"Planned {task_count} task(s). {notes}".strip()

    def prompt_block(self) -> str:
        lines = ["SESSION MEMORY (shared — stay consistent):"]
        if self.style_brief:
            lines.append(f"- Style: {self.style_brief}")
        if self.music_direction:
            lines.append(f"- Music: {self.music_direction}")
        if self.caption_direction:
            lines.append(f"- Captions: {self.caption_direction}")
        if self.catalog_picks:
            picks = ", ".join(f"{k}={v}" for k, v in self.catalog_picks.items())
            lines.append(f"- Catalog picks: {picks}")
        if self.constraints:
            lines.append(f"- Constraints: {', '.join(self.constraints)}")
        if self.avoid:
            lines.append(f"- Avoid: {', '.join(self.avoid)}")
        if self.human_preferences:
            lines.append(f"- Human likes: {', '.join(self.human_preferences[:5])}")
        return "\n".join(lines)
