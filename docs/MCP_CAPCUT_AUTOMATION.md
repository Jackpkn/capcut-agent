# CapCut MCP — Full Automation Guide

> **MCP se pure CapCut ko automate karo** — tum goal bolo, brain samjhega KYA karna hai (shortcut naam yaad rakhne ki zaroorat nahi).

## The one tool you need

```text
capcut_automate(
  goal="make this travel vlog publish ready — captions, cinematic color, music fade"
)
```

The **Automation Brain**:
1. **Discovers** live CapCut UI (`discover_capcut_ui`) — infinite features show up here
2. **Understands purpose** — "save my work" → persist project (not "run shortcut save")
3. **Plans** steps by capability goals (disk > shortcuts > RPA)
4. **Executes** and reports what it did and why

Preview plan without executing:
```text
plan_capcut_automation(goal="add captions and export")
search_capcut_capabilities(goal="lower music under voice")
```

---

## Setup (ek baar)

1. **CapCut desktop** install + kam se kam **ek empty/template project** (e.g. `0610`) drafts folder mein.
2. **Backend MCP** — Cursor mein `capcut-agent` MCP enabled. Changes ke baad MCP **restart** karo.
3. **Accessibility** (shortcuts / export / library ke liye):
   - System Settings → Privacy & Security → **Accessibility** → **Cursor** ya **Terminal** ON
   - **Automation** → same app ko **System Events** control karne do
4. **Optional CDP** — CapCut `--remote-debugging-port=9222` se live reload (disk save ke baad timeline refresh).

---

## MCP workflow — start se export tak

### Step 1 — Project banao + clips import

```text
create_project_from_media(
  media_paths=["/Users/you/Videos/clip1.mp4", "/Users/you/Videos/clip2.mp4"],
  project_name="my-vlog"
)
```

Ya existing project pe:

```text
import_clips(project_path="...", media_paths=["/path/new.mp4"])
```

### Step 2 — Full auto edit (ek command)

```text
run_edit_pipeline(
  project_path="...",          # optional — latest project default
  captions=true,
  caption_style="travel",
  color_preset="cinematic",
  music_fade_in=2.0,
  music_fade_out=3.0,
  duck_volume=0.25,
  sync_beats=false,
  verify=true
)
```

**Ya sab ek saath:**

```text
bootstrap_project_and_edit(
  media_paths=["/path/a.mp4", "/path/b.mp4"],
  project_name="trip",
  color_preset="cinematic"
)
```

### Step 3 — Fine-tune (chat ya individual MCP tools)

| Kaam | MCP tool |
|------|----------|
| Timeline dekhna | `get_timeline_summary` |
| Trim / split | `trim_clip`, `split_clip` |
| Order change | `reorder_clips` |
| Music duck / fade | `duck_audio`, `fade_project_music` |
| Color | `apply_color_preset` (cinematic, warm, vivid…) |
| Captions (free Whisper) | `generate_captions` |
| Transitions / FX | `add_transition`, `add_effect` |
| Custom logic | `execute_capcut_script` |
| QA check | `verify_project` |

### Step 4 — CapCut mein save + export

```text
capcut_shortcut("save")
rpa_capcut(rpa_action="export")
```

---

## Shortcut keys — MCP se chalao

`list_capcut_shortcuts()` — poori list.

```text
capcut_shortcut("play_pause")
capcut_shortcut("split")           # Cmd+B — playhead pe cut
capcut_shortcut("undo")
capcut_shortcut("default_transition")
capcut_shortcut("export")          # export dialog
capcut_shortcut("save")
```

Ya:

```text
rpa_capcut(rpa_action="shortcut", shortcut_name="split", repeat=1)
rpa_capcut(rpa_action="save")
```

### Mac CapCut shortcuts (reference)

| Shortcut name | Keys | Kaam |
|---------------|------|------|
| `save` | ⌘S | Project save |
| `export` | ⌘E | Export dialog |
| `undo` / `redo` | ⌘Z / ⌘⇧Z | Undo / redo |
| `play_pause` | Space | Play / pause |
| `split` | ⌘B | Split at playhead |
| `split_blade` | C | Blade tool |
| `select_tool` | V | Selection tool |
| `duplicate` | ⌘D | Duplicate clip |
| `default_transition` | ⌘⇧D | Default transition |
| `search_library` | ⌘F | Library search focus |
| `copy` / `paste` / `cut` | ⌘C / ⌘V / ⌘X | Clipboard |
| `delete` | Delete | Remove selected |

Settings → Keyboard se remap ho sakte hain — MCP names same rehte hain.

---

## CapCut AI / native features (RPA)

CapCut ke **paid / UI-only** AI features disk JSON se nahi chalte — RPA se best-effort:

```text
rpa_capcut(rpa_action="auto_design", from_home=true)   # AutoCut / Smart template UI
rpa_capcut(rpa_action="auto_captions")                # native captions panel (paid)
rpa_capcut(rpa_action="auto_cutout", clip_name="clip1")
search_capcut_library(query="cinematic piano", asset_type="music")
download_capcut_asset(query="whoosh", asset_type="effect")
```

**Free alternative (recommended):**

- Captions → `generate_captions` (Whisper, disk)
- Color → `apply_color_preset` (disk filters)
- Full polish → `run_edit_pipeline`

---

## Example — Cursor mein bolna

> "MCP se `bootstrap_project_and_edit` chalao media `/Users/me/clips/*.mp4` pe, cinematic color, phir export."

> "`get_timeline_summary` dikhao, clip 2 pe `trim_clip`, music fade 2s, `verify_project`."

> "`capcut_shortcut` se split karo, phir `run_edit_pipeline` captions ke saath."

---

## Layers (architecture)

```
Tumhari clips + prompt
        ↓
MCP tools (Cursor agent)
        ↓
┌─────────────────────────────────────┐
│ Layer 3: draft JSON (writer.py)    │  ← 90% edits — fast, reliable
│ Layer 2: shortcuts + RPA (rpa.py)  │  ← export, library, CapCut AI UI
│ Layer 1: verify + CDP sync         │  ← QA + live reload
└─────────────────────────────────────┘
        ↓
CapCut project on disk + app
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No module named 'capcut'` | MCP restart; `mcp_server.py` path bootstrap |
| Shortcuts fail | Accessibility ON for Cursor/Terminal |
| Export dialog nahi khulta | CapCut foreground mein lao: `rpa_capcut("focus")` |
| AI design click nahi hota | Version drift — manually kholo ya `run_edit_pipeline` use karo |
| Timeline refresh nahi | CapCut CDP port 9222 ya project reopen |

---

## All MCP tools (quick index)

**Project:** `list_projects`, `get_timeline_summary`, `create_project_from_media`, `import_clips`

**Edit:** `trim_clip`, `split_clip`, `reorder_clips`, `add_transition`, `add_effect`, `update_text`, `generate_captions`, `apply_color_preset`, `duck_audio`, `fade_project_music`, `set_audio_fade`, `apply_audio_crossfades`, `sync_video_to_beats`, `execute_capcut_script`

**Pipeline:** `run_edit_pipeline`, `bootstrap_project_and_edit`, `verify_project`

**UI / shortcuts:** `list_capcut_shortcuts`, `capcut_shortcut`, `rpa_capcut`, `search_capcut_library`, `download_capcut_asset`
