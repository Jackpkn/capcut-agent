# Hierarchical Multi-Agent Architecture

> **Living doc** — update this when layers change. Agents and humans read this first.

## Problem

Single LLM + full `draft_info.json` → context overflow, wrong segment IDs, broken timeline on long projects.

## Solution: 3 layers + shared memory

```
Human → Orchestrator (route: answer | edit | team)
              ↓
Layer 1 STRATEGIC — Director Agent
  • Input: duration, clip count, FFmpeg analysis, chapter time ranges
  • Output: chapter map + style brief + high-level goals
  • NEVER: segment_ids, full draft JSON

Layer 2 TACTICAL — Scene Planner Agent (per chapter)
  • Input: ONE chapter + session memory + clips in [start_sec, end_sec]
  • Output: ordered atomic tasks for that chapter only

Layer 3 EXECUTION — Specialist Agents (sequential)
  • Input: ONE task + domain slice (video/audio/text/effects)
  • Output: one propose_* action → QA → human approve → writer

Shared: SessionMemory (style, catalog picks, completed edits, constraints)
```

## CapCut constraint

**One** `draft_info.json`. Writers run **sequentially** (or batched per chapter). Parallel = asset prep only (Whisper, catalog search), not simultaneous JSON writes.

## Code map

| Component | Path | Status |
|-----------|------|--------|
| Orchestrator | `backend/agent/orchestrator.py` | ✅ |
| Unified SSE | `backend/agent/unified_stream.py` | ✅ |
| Session memory | `backend/core/session_memory.py` | ✅ |
| Chapters | `backend/core/chapters.py` | ✅ |
| Strategic context | `backend/agent/strategic_context.py` | ✅ |
| Director (L1) | `backend/agent/agents/director_agent.py` | ✅ chapters in submit_goals |
| Scene planner (L2) | `backend/agent/scene_planner.py` | ✅ |
| Specialists (L3) | `backend/agent/specialists/` | ✅ |
| QA | `backend/agent/qa_agent.py` | ✅ rules; confidence TBD |
| Team loop | `backend/core/agent_loop.py` | ✅ chapter queue |
| Domain slices | `backend/core/slices.py` | ✅ |
| Episodic memory (user taste) | `backend/core/episodic_memory.py` | ✅ partial (SQLite + Director context) |

## Session fields (`EditSession`)

- `chapters: list[Chapter]`
- `current_chapter_index: int`
- `session_memory: SessionMemory`
- `tasks[].chapter_id` — which chapter a task belongs to

## SSE events (UI)

- `route_decision` — orchestrator mode
- `chapter_map` — Director structure
- `chapter_started` / `chapter_planned` — tactical progress
- `agent_activity` — specialist + `@ time`
- `team_plan` — approve gate

## Implementation phases

- [x] **Phase A** — Chapters + session memory + scene planner
- [x] **Phase B** — Task dependency graph (topological execute)
- [ ] **Phase C** — Reflection agent every N tasks / end of chapter
- [ ] **Phase D** — QA confidence scores + style vs memory
- [ ] **Phase E** — Episodic memory (SQLite per user) — partial: approve/reject + Director taste
- [ ] **Phase F** — Assets agent (image/video gen APIs)

## Last updated

2026-06-09 — Phase A hierarchical planning wired.
