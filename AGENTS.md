# CapCut Agent — instructions for AI assistants

Read **`docs/HIERARCHICAL_AGENT.md`** before changing agent flow.

## Quick rules

1. **Never** send full `draft_info.json` to the Director (strategic layer).
2. **Scene planner** gets one chapter's clips only (`core/chapters.py`).
3. **Specialists** get domain slices only (`core/slices.py`).
4. **SessionMemory** is the shared store — agents read/write via `core/session_memory.py`.
5. **No keyword routing** — orchestrator + Director LLM decide intent.
6. **Sequential writes** to CapCut disk — no parallel timeline mutations.

## Entry point

`POST /agent/stream` → `agent/unified_stream.py` → orchestrator → chat or team loop.

## Tests

Project **0610** — 4 clips, travel, 9:16. Path under `~/Movies/CapCut/User Data/Projects/com.lveditor.draft/`.
