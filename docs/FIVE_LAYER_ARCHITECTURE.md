# 5-Layer CapCut AI Automation Architecture

> Living architecture doc — maps the full automation vision to code in this repo.

## Overview

```
User prompt + clips
       │
       ▼
┌──────────────────────────────────────┐
│ Layer 5: Multi-Agent Creative Brain  │  Director → Planner → Specialists
└──────────────────────────────────────┘
       │
       ├──────────────────┬────────────────────┐
       ▼                  ▼                    ▼
┌─────────────┐   ┌─────────────────┐   ┌──────────────────┐
│ Layer 4     │   │ Layer 3         │   │ Layer 2          │
│ Vision/Audio│   │ Scripting Engine│   │ OS GUI / RPA     │
│ Intelligence│   │ (draft JSON)    │   │ (CapCut desktop) │
└─────────────┘   └─────────────────┘   └──────────────────┘
       │                  │                    │
       └──────────────────┴────────────────────┘
                          ▼
              ┌───────────────────────┐
              │ Layer 1: Sync + QA    │  verify → CDP reload → self-correct
              └───────────────────────┘
                          ▼
                 CapCut project + app
```

## Layer 1 — Real-Time Sync & QA Guardrails

| Component | Path | Status |
|-----------|------|--------|
| Disk writer | `backend/capcut/writer.py` | ✅ |
| Batch ops | `backend/capcut/draft_ops.py` | ✅ |
| CDP live reload | `backend/capcut/cdp.py` | ✅ |
| UI handoff (lock/unlock) | `backend/capcut/project_ui.py` | ✅ |
| Pre-apply QA | `backend/agent/qa_agent.py` | ✅ |
| Reflection / self-correct | `backend/agent/reflection_agent.py` | ✅ partial |
| **Post-apply verify** | `backend/capcut/verify.py` | ✅ NEW |
| MCP `verify_project` | `backend/agent/mcp_server.py` | ✅ NEW |

## Layer 2 — OS GUI & RPA Specialist

Drives CapCut desktop when JSON cannot express the feature.

| Component | Path | Status |
|-----------|------|--------|
| RPA dispatcher | `backend/capcut/rpa.py` | ✅ NEW |
| Accessibility checks | `backend/capcut/accessibility.py` | ✅ |
| Library download UI | `backend/capcut/ui_trigger.py` | ✅ |
| MCP `rpa_capcut` | `backend/agent/mcp_server.py` | ✅ NEW |
| TaskType.RPA | `backend/core/models.py` | ✅ NEW |

**RPA actions:** `focus`, `export`, `auto_cutout`, `auto_captions`

## Layer 3 — Dynamic Scripting Engine

| Component | Path | Status |
|-----------|------|--------|
| Sandboxed script runner | `backend/capcut/scripting.py` | ✅ NEW |
| Low-level primitives | `backend/capcut/primitives.py` | ✅ NEW |
| Built-in color filters | `backend/capcut/filters.py` | ✅ |
| MCP `execute_capcut_script` | `backend/agent/mcp_server.py` | ✅ NEW |

**Primitives:** `set_clip_transform`, `add_keyframes`, `set_canvas`, `zoom_pulse`, `shake_segment`

**Script sandbox:** AST validation, blocked imports, 30s timeout, exposed writer API.

## Layer 4 — Visual & Audio Intelligence

| Component | Path | Status |
|-----------|------|--------|
| FFmpeg probe | `backend/analysis/` | ✅ |
| Whisper captions | `backend/analysis/whisper_captions.py` | ✅ |
| Clip intelligence | `backend/analysis/clip_intelligence.py` | ✅ partial |
| Vision metadata | — | 🔲 Phase 4 |

## Layer 5 — Multi-Agent Creative Brain

| Component | Path | Status |
|-----------|------|--------|
| Orchestrator | `backend/agent/orchestrator.py` | ✅ |
| Director | `backend/agent/agents/director_agent.py` | ✅ |
| Scene planner | `backend/agent/scene_planner.py` | ✅ |
| Specialists | `backend/agent/specialists/` | ✅ |
| Timeline index | `backend/core/timeline_index.py` | ✅ |
| Session memory | `backend/core/session_memory.py` | ✅ |

## Free alternatives to paid CapCut Pro features

| CapCut Pro feature | Our free path |
|--------------------|---------------|
| Auto captions | `generate_captions` (local Whisper) |
| Cinematic filters | `apply_color_preset` / built-in filter IDs |
| Beat sync | `sync_video_to_beats` |
| Background removal | `rpa_capcut(auto_cutout)` → future local rembg engine |
| Smart reframe | 🔲 future primitive + vision metadata |
| AI video gen | 🔲 `generate_video_clip` stub |

## MCP tools (18)

Core: `list_projects`, `get_timeline_summary`, audio/FX tools.

**New:** `execute_capcut_script`, `rpa_capcut`, `verify_project`

## Implementation phases

- [x] Layer 1 foundation (writer, CDP, QA rules)
- [x] Layer 3 scripting + primitives (v1)
- [x] Layer 2 RPA scaffold (v1)
- [x] Layer 1 post-apply verify
- [ ] Media ingest (`import_clips` from user folder)
- [ ] Layer 4 vision metadata pipeline
- [ ] Layer 3 masks / adjustment layers / compound clips
- [ ] Layer 2 robust cutout + export path automation
- [ ] Closed-loop: verify → reflection → retry in `apply_service`

## Last updated

2026-06-24 — Layer 2/3 scripting + verify foundation.
