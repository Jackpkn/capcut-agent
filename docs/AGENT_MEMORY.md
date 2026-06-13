# Agent session memory (for humans + AI)

**Canonical architecture:** [HIERARCHICAL_AGENT.md](./HIERARCHICAL_AGENT.md)  
**Cursor entry:** [../AGENTS.md](../AGENTS.md)

## What we are building

Hierarchical reflexive multi-agent for CapCut — not one LLM dumping JSON.

## Current implementation (2026-06-09)

### Layer 1 — Director (`agent/agents/director_agent.py`)
- Sees `strategic_context` only (duration, counts, chapter hints, analysis score).
- Outputs `submit_goals`: intent, chapters[], goals[], constraints[], avoid[].
- Populates `SessionMemory` on `EditSession`.

### Layer 2 — Scene Planner (`agent/scene_planner.py`)
- Runs **once per chapter**.
- Input: `chapter_timeline_slice()` — clips/overlays in `[start_sec, end_sec]` only.
- Reads `SessionMemory.prompt_block()`.

### Layer 3 — Specialists (`agent/specialists/`)
- One task at a time, domain slice only (unchanged).

### Shared memory (`core/session_memory.py`)
- On `EditSession.session_memory` dict.
- Fields: style_brief, catalog_picks, constraints, avoid, completed_edits, chapter_notes.

### Chapters (`core/chapters.py`)
- `Chapter` dataclass on `EditSession.chapters`.
- Tasks tagged with `task.chapter_id`.
- Default chapterizer for short projects → 1 chapter "Full timeline".

### Routing (`agent/orchestrator.py`)
- LLM routes answer | edit | team.
- Auto-team if duration > 180s or clip_count > 8.

### API
- `POST /agent/stream` — unified entry (orchestrator → chat or team).

### UI
- `chapter_map`, `chapter_started`, `chapter_planned` SSE events.
- Chapter chips in live trace + TeamPlanCard.
- **`editor_timeline`** SSE → `EditorTimelineReport` in chat (video strip, waveform, suggestions) — pro editor style.

## Next (not built yet)

- Phase B: task `depends_on` topological execution
- Phase C: reflection agent per chapter
- Phase D: QA confidence vs memory
- Phase E: `episodic_memory.py` SQLite user taste
- Phase F: image/video gen API wiring

## Do not regress

- No full `draft_info.json` to Director.
- No keyword intent routing.
- No parallel writes to CapCut disk.
- No preset planner fallback without LLM.
