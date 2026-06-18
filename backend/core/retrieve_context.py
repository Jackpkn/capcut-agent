"""Retrieve minimal timeline context for an agent call — search before load."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from core.chapters import Chapter, chapter_timeline_slice
from core.edit_ledger import EditLedger
from core.slices import get_slice_for_task_type, get_timeline_summary, timeline_summary_from_project_summary
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
    project_summary: dict | None = None,
) -> RetrievedContext:
    """
    Build minimal context for one agent step.
    Domain/chapter come from the orchestrator or Director — not keyword heuristics.
    """
    if project_path:
        from core.project_ledger import load_ledger

        ledger = load_ledger(project_path) if ledger is None else ledger

    index = TimelineIndex.from_project(project_path, summary=project_summary)
    notes: list[str] = []
    working: dict[str, Any] = {}
    compact = (
        timeline_summary_from_project_summary(project_summary)
        if project_summary is not None
        else None
    )

    time_start = 0.0
    time_end = index.duration_sec or 9999.0
    if chapter:
        time_start = chapter.start_sec
        time_end = chapter.end_sec
        notes.append(f"Chapter «{chapter.label}» {time_start:.0f}s–{time_end:.0f}s")

    clip_n = index.parse_clip_index_from_message(user_message)
    if clip_n is not None:
        clip = index.clip_by_index(clip_n)
        if clip:
            working["focus_clip"] = clip
            notes.append(f"Focused clip #{clip_n}")

    if domain in ("video", "audio", "text", "effects"):
        slice_data = get_slice_for_task_type(project_path, domain)
        working["domain_slice"] = (
            slice_data.get("clips") or slice_data.get("overlays") or slice_data
        )
        notes.append(f"Domain slice: {domain}")
    elif chapter:
        summary = compact or get_timeline_summary(project_path)
        working = chapter_timeline_slice(summary, chapter)
        notes.append("Chapter slice (clips + captions in range)")
    elif working.get("focus_clip"):
        notes.append("Focus clip only")
    else:
        summary = compact or get_timeline_summary(project_path)
        working = {
            "video_clips": summary.get("video_clips", [])[:8],
            "text_overlays": summary.get("text_overlays", [])[:10],
        }
        notes.append("Default compact slice")

    domains = [domain] if domain else ["overview"]

    return RetrievedContext(
        catalog=index.catalog(),
        working_slice=working,
        domains=domains,
        retrieval_notes=notes,
        ledger_summary=ledger.summary() if ledger else "",
        clip_intelligence_summary=_clip_intelligence_prompt_block(project_path),
        analysis=analysis,
    )
