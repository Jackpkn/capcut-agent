"""Chapter map — strategic time ranges without exposing full JSON to Director."""

from __future__ import annotations

from dataclasses import dataclass

from core.models import new_id


@dataclass
class Chapter:
    """One narrative segment of the timeline (minutes/scenes)."""

    id: str
    index: int
    start_sec: float
    end_sec: float
    label: str
    pacing: str = "medium"
    notes: str = ""
    clip_count: int = 0
    status: str = "pending"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "index": self.index,
            "start_sec": self.start_sec,
            "end_sec": self.end_sec,
            "label": self.label,
            "pacing": self.pacing,
            "notes": self.notes,
            "clip_count": self.clip_count,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Chapter:
        return cls(
            id=data.get("id") or new_id(),
            index=int(data.get("index", 1)),
            start_sec=float(data.get("start_sec", 0)),
            end_sec=float(data.get("end_sec", 0)),
            label=data.get("label", "Chapter"),
            pacing=data.get("pacing", "medium"),
            notes=data.get("notes", ""),
            clip_count=int(data.get("clip_count", 0)),
            status=data.get("status", "pending"),
        )

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.end_sec - self.start_sec)


def _clip_in_chapter(clip: dict, chapter: Chapter) -> bool:
    at = float(clip.get("at_sec", 0))
    end = at + float(clip.get("duration_sec", 0))
    return at < chapter.end_sec and end > chapter.start_sec


def clips_for_chapter(timeline_summary: dict, chapter: Chapter) -> list[dict]:
    clips = timeline_summary.get("video_clips", [])
    return [c for c in clips if _clip_in_chapter(c, chapter)]


def texts_for_chapter(timeline_summary: dict, chapter: Chapter) -> list[dict]:
    texts = timeline_summary.get("text_overlays", [])
    return [t for t in texts if _clip_in_chapter(t, chapter)]


def chapter_timeline_slice(timeline_summary: dict, chapter: Chapter) -> dict:
    clips = clips_for_chapter(timeline_summary, chapter)
    texts = texts_for_chapter(timeline_summary, chapter)
    return {
        "chapter": chapter.to_dict(),
        "video_clips": clips,
        "text_overlays": texts,
        "clip_count": len(clips),
        "text_count": len(texts),
    }


def default_chapters_from_timeline(
    timeline_summary: dict,
    *,
    target_chapter_sec: float = 90.0,
    max_chapters: int = 12,
) -> list[Chapter]:
    duration = float(timeline_summary.get("duration_sec") or 0)
    clips = timeline_summary.get("video_clips", [])

    if duration <= 0 and clips:
        duration = max(
            float(c.get("at_sec", 0)) + float(c.get("duration_sec", 0)) for c in clips
        )

    if duration <= target_chapter_sec or len(clips) <= 4:
        return [Chapter(
            id=new_id(),
            index=1,
            start_sec=0.0,
            end_sec=duration or 60.0,
            label="Full timeline",
            pacing="medium",
            notes="Single chapter — compact project",
            clip_count=len(clips),
        )]

    chapters: list[Chapter] = []
    start = 0.0
    idx = 1
    while start < duration and idx <= max_chapters:
        end = min(duration, start + target_chapter_sec)
        ch_clips = [
            c for c in clips
            if float(c.get("at_sec", 0)) < end
            and float(c.get("at_sec", 0)) + float(c.get("duration_sec", 0)) > start
        ]
        chapters.append(Chapter(
            id=new_id(),
            index=idx,
            start_sec=start,
            end_sec=end,
            label=f"Chapter {idx}",
            pacing="medium",
            clip_count=len(ch_clips),
        ))
        start = end
        idx += 1

    if chapters:
        chapters[0].label = "Opening"
        if len(chapters) > 1:
            chapters[-1].label = "Outro"
    return chapters


def chapters_from_director_payload(
    items: list[dict],
    timeline_summary: dict,
) -> list[Chapter]:
    if not items:
        return default_chapters_from_timeline(timeline_summary)

    chapters: list[Chapter] = []
    for i, raw in enumerate(items, start=1):
        ch = Chapter(
            id=new_id(),
            index=int(raw.get("index", i)),
            start_sec=float(raw.get("start_sec", 0)),
            end_sec=float(raw.get("end_sec", 0)),
            label=raw.get("label", f"Chapter {i}"),
            pacing=raw.get("pacing", "medium"),
            notes=raw.get("notes", ""),
        )
        ch.clip_count = len(clips_for_chapter(timeline_summary, ch))
        chapters.append(ch)
    return chapters
