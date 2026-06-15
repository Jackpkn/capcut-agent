"""Edit ledger — compact record of what agents already changed (not full draft replay)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EditLedger:
    """Append-only log of applied or proposed edits for session continuity."""

    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        *,
        action: str,
        description: str,
        chapter_id: str = "",
        segment_id: str = "",
        at_sec: float | None = None,
        status: str = "proposed",
    ) -> None:
        self.entries.append({
            "action": action,
            "description": description,
            "chapter_id": chapter_id,
            "segment_id": segment_id,
            "at_sec": at_sec,
            "status": status,
        })

    def mark_applied(self, descriptions: list[str]) -> None:
        desc_set = set(descriptions)
        for e in self.entries:
            if e.get("description") in desc_set:
                e["status"] = "applied"

    def summary(self, *, max_lines: int = 12) -> str:
        if not self.entries:
            return ""
        lines = ["EDIT LEDGER (already done or proposed — do not repeat blindly):"]
        for e in self.entries[-max_lines:]:
            at = e.get("at_sec")
            at_s = f" @ {at:.1f}s" if at is not None else ""
            status = e.get("status", "proposed")
            lines.append(f"- [{status}] {e.get('description', '')}{at_s}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"entries": self.entries[-100:]}

    @classmethod
    def from_dict(cls, data: dict | None) -> EditLedger:
        if not data:
            return cls()
        return cls(entries=list(data.get("entries", [])))

    @classmethod
    def from_completed_edits(cls, items: list[dict]) -> EditLedger:
        ledger = cls()
        for item in items:
            ledger.record(
                action=item.get("action", ""),
                description=item.get("description", ""),
                chapter_id=item.get("chapter_id", ""),
                at_sec=item.get("at_sec"),
                status=item.get("status", "applied"),
            )
        return ledger
