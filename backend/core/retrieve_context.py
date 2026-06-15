"""Retrieve minimal timeline context for an agent call — search before load."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from core.chapters import Chapter, chapter_timeline_slice
from core.edit_ledger import EditLedger
from core.slices import get_slice_for_task_type, get_timeline_summary
from core.timeline_index import TimelineIndex


@dataclass
class RetrievedContext:
    """Small bundle for one LLM call — index + working slice + metadata."""

    catalog: dict
    working_slice: dict
    domains: list[str]
    retrieval_notes: list[str] = field(default_factory=list)
    ledger_summary: str = ""
    clip_intelligence_summary: str = ""
    analysis: dict | None = None

    def to_prompt_block(self) -> str:
        parts = [
            "TIMELINE INDEX (search catalog — use segment_id/text_id from WORKING SLICE):",
            json.dumps(self.catalog, indent=2),
            "",
            "WORKING SLICE (only load what you need for this request):",
            json.dumps(self.working_slice, indent=2),
        ]
        if self.retrieval_notes:
            parts.extend(["", "RETRIEVAL:", *[f"- {n}" for n in self.retrieval_notes]])
        if self.ledger_summary:
            parts.extend(["", self.ledger_summary])
        if self.clip_intelligence_summary:
            parts.extend(["", self.clip_intelligence_summary])
        if self.analysis:
            parts.extend([
                "",
                "ANALYSIS (FFmpeg):",
                json.dumps(self.analysis, indent=2),
            ])
        return "\n\n".join(parts)


def _clip_intelligence_prompt_block(project_path: str) -> str:
    from agent import brain as brain_module
    from analysis.clip_intelligence import director_clip_summaries, load_project_intelligence

    clips = brain_module.clip_intelligence_context or load_project_intelligence(project_path)
    if not clips:
        return ""
    summaries = director_clip_summaries(clips)
    lines = [
        "CLIP INTELLIGENCE (what is in each clip — use for creative decisions):",
        json.dumps(summaries, indent=2),
    ]
    return "\n".join(lines)


def retrieve_context(
    project_path: str,
    user_message: str,
    *,
    chapter: Chapter | None = None,
    domain: str | None = None,
    ledger: EditLedger | None = None,
    analysis: dict | None = None,
) -> RetrievedContext:
    """
    Build minimal context for one agent step.
    Like opening specific files in a codebase — not the whole repo.
    """
    if project_path:
        from core.project_ledger import load_ledger

        ledger = load_ledger(project_path) if ledger is None else ledger

    index = TimelineIndex.from_project(project_path)
    domains = {domain} if domain else index.infer_domains(user_message)
    notes: list[str] = []

    # Time / chapter focus
    time_start = 0.0
    time_end = index.duration_sec or 9999.0
    if chapter:
        time_start = chapter.start_sec
        time_end = chapter.end_sec
        notes.append(f"Chapter «{chapter.label}» {time_start:.0f}s–{time_end:.0f}s")
    else:
        for ch in index.chapters:
            if ch.label.lower() in user_message.lower():
                chapter = ch
                time_start = ch.start_sec
                time_end = ch.end_sec
                notes.append(f"Matched chapter «{ch.label}»")
                break

    clip_n = index.parse_clip_index_from_message(user_message)
    working: dict[str, Any] = {}

    if clip_n is not None:
        clip = index.clip_by_index(clip_n)
        if clip:
            working["focus_clip"] = clip
            notes.append(f"Focused clip #{clip_n}")

    if "text" in domains or "caption" in user_message.lower():
        texts = index.texts_in_range(time_start, time_end)
        if len(texts) > 15:
            texts = texts[:15]
            notes.append(f"Captions truncated to 15 in range")
        working["text_overlays"] = texts

    if "video" in domains and "focus_clip" not in working:
        clips = index.clips_in_range(time_start, time_end)
        working["video_clips"] = clips

    if "audio" in domains:
        working["audio_clips"] = [
            c for c in index.audio_clips
            if float(c.get("at_sec", 0)) < time_end
        ]

    if "effects" in domains:
        fx = get_slice_for_task_type(project_path, "effects")
        working["transitions"] = fx.get("transitions", [])[:10]
        working["video_effects"] = [
            {"id": e.get("id"), "name": e.get("name"), "type": e.get("type")}
            for e in fx.get("video_effects", [])[:10]
        ]

    if "analysis" in domains and analysis:
        working["analysis_issues"] = (analysis.get("issues") or [])[:8]
        working["analysis_score"] = analysis.get("score")

    if chapter and not working.get("video_clips") and not working.get("text_overlays"):
        summary = get_timeline_summary(project_path)
        working = chapter_timeline_slice(summary, chapter)
        notes.append("Chapter slice (clips + captions in range)")

    if domain and domain in ("video", "audio", "text", "effects"):
        slice_data = get_slice_for_task_type(project_path, domain)
        working.setdefault("domain_slice", slice_data.get("clips") or slice_data.get("overlays") or slice_data)

    if not working:
        summary = get_timeline_summary(project_path)
        if chapter:
            working = chapter_timeline_slice(summary, chapter)
        else:
            working = {
                "video_clips": summary.get("video_clips", [])[:8],
                "text_overlays": summary.get("text_overlays", [])[:10],
            }
        notes.append("Default compact slice")

    return RetrievedContext(
        catalog=index.catalog(),
        working_slice=working,
        domains=sorted(domains),
        retrieval_notes=notes,
        ledger_summary=ledger.summary() if ledger else "",
        clip_intelligence_summary=_clip_intelligence_prompt_block(project_path),
        analysis=analysis if "analysis" in domains else None,
    )
