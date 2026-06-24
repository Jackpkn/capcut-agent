"""Timeline index — searchable catalog of clips/captions (like a repo file tree)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from capcut.reader import get_project_summary
from core.chapters import Chapter, default_chapters_from_timeline


@dataclass
class TimelineIndex:
    """Compact, searchable view of a CapCut project — never full draft JSON."""

    project_path: str
    duration_sec: float
    fps: float | None
    video_clips: list[dict] = field(default_factory=list)
    audio_clips: list[dict] = field(default_factory=list)
    text_overlays: list[dict] = field(default_factory=list)
    transitions: list[dict] = field(default_factory=list)
    effects: list[dict] = field(default_factory=list)
    filters: list[dict] = field(default_factory=list)
    chapters: list[Chapter] = field(default_factory=list)

    @classmethod
    def from_project(cls, project_path: str, summary: dict | None = None) -> TimelineIndex:
        if summary is None:
            summary = get_project_summary(project_path)
        overview = summary.get("overview", {})
        timeline_summary = {
            "duration_sec": overview.get("duration_sec"),
            "video_clips": summary.get("video_clips", []),
        }
        chapters = default_chapters_from_timeline(timeline_summary)

        return cls(
            project_path=project_path,
            duration_sec=float(overview.get("duration_sec") or 0),
            fps=overview.get("fps"),
            video_clips=list(summary.get("video_clips", [])),
            audio_clips=list(summary.get("audio_clips", [])),
            text_overlays=list(summary.get("text_overlays", [])),
            transitions=list(summary.get("transitions", [])),
            effects=list(summary.get("effects", [])),
            filters=list(summary.get("filters", [])),
            chapters=chapters,
        )

    def catalog(self) -> dict:
        """Minimal index always safe to send to Director / orchestrator."""
        return {
            "duration_sec": self.duration_sec,
            "fps": self.fps,
            "video_clip_count": len(self.video_clips),
            "audio_clip_count": len(self.audio_clips),
            "text_overlay_count": len(self.text_overlays),
            "transition_count": len(self.transitions),
            "effect_count": len(self.effects),
            "filter_count": len(self.filters),
            "chapters": [c.to_dict() for c in self.chapters],
            "clip_index": [
                {
                    "index": c.get("index"),
                    "name": c.get("name"),
                    "at_sec": c.get("at_sec"),
                    "duration_sec": c.get("duration_sec"),
                    "segment_id": c.get("segment_id"),
                    "transition_after": c.get("transition"),
                }
                for c in self.video_clips
            ],
            "transition_note": (
                "transition_after on each clip = transition on the cut to the next clip; "
                "null means none on that cut yet"
            ),
        }

    def clip_by_index(self, n: int) -> dict | None:
        for c in self.video_clips:
            if c.get("index") == n:
                return c
        if 1 <= n <= len(self.video_clips):
            return self.video_clips[n - 1]
         
        return None

    def clips_in_range(self, start_sec: float, end_sec: float) -> list[dict]:
        out: list[dict] = []
        for c in self.video_clips:
            at = float(c.get("at_sec", 0))
            end = at + float(c.get("duration_sec", 0))
            if at < end_sec and end > start_sec:
                out.append(c)
        return out

    def texts_in_range(self, start_sec: float, end_sec: float) -> list[dict]:
        out: list[dict] = []
        for t in self.text_overlays:
            at = float(t.get("at_sec", 0))
            end = at + float(t.get("duration_sec", 0))
            if at < end_sec and end > start_sec:
                out.append(t)
        return out

    def chapter_for_time(self, at_sec: float) -> Chapter | None:
        for ch in self.chapters:
            if ch.start_sec <= at_sec < ch.end_sec:
                return ch
        return self.chapters[-1] if self.chapters else None

    def chapter_by_label(self, label: str) -> Chapter | None:
        needle = label.lower()
        for ch in self.chapters:
            if needle in ch.label.lower():
                return ch
        return None

    def search_text(self, query: str, limit: int = 20) -> list[dict]:
        q = query.lower()
        hits = [
            t for t in self.text_overlays
            if q in (t.get("content") or "").lower()
        ]
        return hits[:limit]

    @staticmethod
    def parse_clip_index_from_message(message: str) -> int | None:
        m = re.search(r"\bclip\s*#?\s*(\d+)\b", message, re.I)
        if m:
            return int(m.group(1))
        m = re.search(r"\b#(\d+)\b", message)
        if m:
            return int(m.group(1))
        return None
