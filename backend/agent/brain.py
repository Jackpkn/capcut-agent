import json
import logging
from dataclasses import dataclass, field

from dotenv import load_dotenv
from agent.actions import describe_action, execute_actions
from agent.streaming import (
    EventEmitter,
    emit_text_chunks,
    proposal as emit_proposal,
    response_start,
    step as emit_step,
    summarize_tool_output,
    text_delta as emit_text_delta,
    tool_call as emit_tool_call,
    tool_result as emit_tool_result,
)
from analysis.suggestions import issues_to_actions
from capcut.catalog import search_catalog
from capcut.library import director_picks, search_library
from capcut.reader import get_project_summary, read_project

load_dotenv()

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert AI video editor controlling CapCut projects directly on macOS.
You think like a professional editor — fast, creative, and precise. The human approves your edits before they run.

## CapCut data model (important)
- `text_overlays`: each has `text_id` (for editing content), `segment_id` (for timing/visibility), `content`, `at_sec`, `duration_sec`
- `video_clips`: each has `segment_id` (for speed/volume/trim/move), `name`, `at_sec`, `duration_sec`
- `audio_clips`: segment_id, volume, timing
- `text_id` edits the words. `segment_id` edits timeline placement, speed, volume, trim, visibility.
- Some projects use text templates — always use `text_id` from text_overlays for text edits.

## Agent behavior (you decide — no scripts)
- Infer intent from the human message in **any language**. You are the agent: observe project data → decide whether to **answer** or **propose edits**.
- **Questions / inspection** (what is on the timeline, captions, clips, duration, capabilities, advice): answer using ONLY ACTIVE PROJECT data. Do **not** call propose_* tools. Format clearly (tables for lists).
- **Edit requests** (add, change, remove, speed up, music, transitions, captions, mood): call propose_* tools for every change needed. Batch when useful.
- **Mixed** (e.g. "what captions do I have and make them shorter"): answer first in your message, then propose edits.
- Think like a pro editor when they want edits: pacing, hook, music, captions — but only propose when they want changes.
- NEVER claim edits are done until the human approves.
- Use exact IDs from project data. Timings: 1 second = 1,000,000 microseconds.
- For text edits use text_id; for speed/volume/trim use segment_id from video_clips.
- Use propose_batch_update_texts for bulk caption changes.
- Use search_library / get_director_picks when you need catalog assets before proposing add_* actions.
- For AI-generated B-roll: propose_generate_image or propose_generate_video_clip with start_sec on the timeline.
- When ANALYSIS REPORT is present, reference it in answers and in edit proposals.
- In answers and proposals, mention **where** on the timeline (seconds, clip name) when relevant.
- **Timeline visual (your choice only):** call `present_timeline` when a visual helps answer the question — e.g. "what captions", "show my clips", "where will this edit go", "scan this project", audio levels. Do **not** call it for every message. Plain text/tables are enough when the user only wants facts.
  - User asks **show captions on timeline** / **IN VISUAL** → `present_timeline(view=captions)` same turn.
  - User asks **scan** / **analyze project** / health → `present_timeline(view=full_scan)` when analysis exists, else `view=captions` or `view=clips` as appropriate.
  - `view=clips` — clip order and positions
  - `view=captions` — text overlays on the timeline
  - `view=audio` — waveform / levels (if analyzed)
  - `view=edits` — pass `markers` with `at_sec` and `label` for proposed placements
  - `view=full_scan` — only when user asks for analysis/health scan
- When the user asks for a **visual** / **show on timeline** / **IN VISUAL**: call `present_timeline` in the same turn. **Never** write `<tool_code>`, `print(present_timeline(...))`, or pseudo-code — only real tool calls work.

## Response format (UI renders structured blocks)
- Use `## Section title` for main sections.
- Use `**Label:** value` lines for metadata (Platform, Clips, Duration, etc.).
- For timeline listings use a markdown table with header row, e.g. `| # | name | at_sec | content |`.
- Use bullet lists for capabilities and numbered lists for step-by-step plans.
- Keep paragraphs short; separate sections with blank lines."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "propose_update_text",
            "description": "Propose changing one text overlay's content. Use text_id from text_overlays.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text_id": {"type": "string"},
                    "new_content": {"type": "string"},
                },
                "required": ["text_id", "new_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_batch_update_texts",
            "description": "Propose updating multiple text overlays at once. Use for bulk caption edits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "updates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text_id": {"type": "string"},
                                "new_content": {"type": "string"},
                            },
                            "required": ["text_id", "new_content"],
                        },
                    },
                },
                "required": ["updates"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_update_transition",
            "description": "Propose changing a transition's name or duration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "transition_id": {"type": "string"},
                    "duration": {"type": "integer"},
                    "name": {"type": "string"},
                },
                "required": ["transition_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_update_clip_speed",
            "description": "Propose changing playback speed of a video clip. Use segment_id from video_clips.",
            "parameters": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "string"},
                    "speed": {"type": "number"},
                },
                "required": ["segment_id", "speed"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_update_volume",
            "description": "Propose changing volume of a video or audio clip segment (0.0 to 1.0).",
            "parameters": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "string"},
                    "volume": {"type": "number"},
                },
                "required": ["segment_id", "volume"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_trim_clip",
            "description": "Propose trimming a clip's in/out points.",
            "parameters": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "string"},
                    "start": {"type": "integer", "description": "Start in microseconds"},
                    "duration": {"type": "integer", "description": "Duration in microseconds"},
                },
                "required": ["segment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_move_segment",
            "description": "Propose moving any segment (text, video, audio) to a new timeline position.",
            "parameters": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "string"},
                    "start_sec": {"type": "number", "description": "New start time in seconds"},
                    "duration_sec": {"type": "number"},
                },
                "required": ["segment_id", "start_sec"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_set_segment_visibility",
            "description": "Propose showing or hiding a segment on the timeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "string"},
                    "visible": {"type": "boolean"},
                },
                "required": ["segment_id", "visible"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_remove_effect",
            "description": "Propose removing a video effect.",
            "parameters": {
                "type": "object",
                "properties": {
                    "effect_id": {"type": "string"},
                },
                "required": ["effect_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_library",
            "description": "Search local CapCut asset catalog by name. Returns resource_id, path, cached status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "asset_type": {
                        "type": "string",
                        "enum": ["music", "effect", "transition", "sticker", "text_template", "all"],
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_director_picks",
            "description": "Get catalog picks for a mood/vibe (energetic, calm, dramatic, fun). Use for creative direction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mood": {"type": "string", "enum": ["energetic", "calm", "dramatic", "fun"]},
                },
                "required": ["mood"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "present_timeline",
            "description": (
                "Show a timeline visual in chat when it helps the user — not on every reply. "
                "Use for clip layout, captions map, audio waveform, or marking where edits will land."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "enum": ["clips", "captions", "audio", "edits", "full_scan"],
                        "description": "What to show on the timeline panel",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Short subtitle explaining why this visual is shown",
                    },
                    "markers": {
                        "type": "array",
                        "description": "For view=edits: pins on the timeline",
                        "items": {
                            "type": "object",
                            "properties": {
                                "at_sec": {"type": "number"},
                                "label": {"type": "string"},
                                "kind": {"type": "string"},
                            },
                            "required": ["at_sec", "label"],
                        },
                    },
                },
                "required": ["view"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_add_music",
            "description": "Propose adding a music track to the timeline. Search library first to find the track name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Music name or search query"},
                    "start_sec": {"type": "number", "description": "Where on timeline to place it (seconds)"},
                    "volume": {"type": "number"},
                },
                "required": ["query", "start_sec"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_replace_music",
            "description": (
                "Propose replacing existing background music (mutes old bed, adds new track). "
                "Use when timeline already has music and user wants hype/new music."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Music name or search query"},
                    "start_sec": {"type": "number"},
                    "volume": {"type": "number"},
                },
                "required": ["query", "start_sec"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_reorder_clips",
            "description": "Propose swapping two video clip positions on the timeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "segment_id_a": {"type": "string"},
                    "segment_id_b": {"type": "string"},
                },
                "required": ["segment_id_a", "segment_id_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_add_transition",
            "description": "Propose adding a transition after a video clip. Search library first for resource_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "string", "description": "Video clip segment_id to attach transition"},
                    "query": {"type": "string"},
                    "resource_id": {"type": "string"},
                    "duration_sec": {"type": "number"},
                },
                "required": ["segment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_add_effect",
            "description": "Propose adding a video effect. Search library first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "resource_id": {"type": "string"},
                    "start_sec": {"type": "number"},
                    "duration_sec": {"type": "number"},
                    "bind_segment_id": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_add_sticker",
            "description": "Propose adding a sticker overlay. Search library first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "resource_id": {"type": "string"},
                    "start_sec": {"type": "number"},
                    "duration_sec": {"type": "number"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_add_text_template",
            "description": "Propose adding a styled text template. Search library first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "resource_id": {"type": "string"},
                    "start_sec": {"type": "number"},
                    "duration_sec": {"type": "number"},
                    "text_content": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_generate_captions",
            "description": "Propose auto-captions via local Whisper (short punchy lines per preset style).",
            "parameters": {
                "type": "object",
                "properties": {
                    "style": {"type": "string", "enum": ["travel_vlog", "tiktok_viral", "cinematic", "energetic"]},
                    "max_words_per_line": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_generate_image",
            "description": (
                "Propose generating an AI image and placing it on the timeline "
                "(B-roll, thumbnail, overlay). Requires image API configured on server."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "start_sec": {"type": "number"},
                    "duration_sec": {"type": "number"},
                },
                "required": ["prompt", "start_sec"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_generate_video_clip",
            "description": (
                "Propose generating a short AI video clip and inserting at a timeline position. "
                "Requires video generation API configured on server."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "start_sec": {"type": "number"},
                    "duration_sec": {"type": "number"},
                },
                "required": ["prompt", "start_sec"],
            },
        },
    },
]

def _to_responses_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "name": tool["function"]["name"],
            "description": tool["function"]["description"],
            "parameters": tool["function"]["parameters"],
        }
        for tool in tools
    ]


PROPOSE_TO_ACTION = {
    "propose_update_text": "update_text",
    "propose_batch_update_texts": "batch_update_texts",
    "propose_update_transition": "update_transition",
    "propose_update_clip_speed": "update_clip_speed",
    "propose_update_volume": "update_volume",
    "propose_trim_clip": "trim_clip",
    "propose_move_segment": "move_segment",
    "propose_set_segment_visibility": "set_segment_visibility",
    "propose_remove_effect": "remove_effect",
    "propose_reorder_clips": "reorder_clips",
    "propose_add_music": "add_music",
    "propose_replace_music": "replace_music",
    "propose_add_transition": "add_transition",
    "propose_add_effect": "add_effect",
    "propose_add_sticker": "add_sticker",
    "propose_add_text_template": "add_text_template",
    "propose_generate_captions": "generate_captions",
    "propose_generate_image": "generate_image",
    "propose_generate_video_clip": "generate_video_clip",
}

IMMEDIATE_TOOLS = {"search_library", "get_director_picks", "present_timeline"}

MAX_CHAT_TURNS = 6

SYNTHESIS_NUDGE = (
    "Using the catalog results and project segment_ids above, call propose_* tools now "
    "for every edit the user asked for. Add a short explanation in your message — "
    "do not call search_library or get_director_picks again."
)

VISUAL_NUDGE = (
    "The user asked for a timeline visual. Call present_timeline now with the right view "
    "(e.g. captions). Do not write tool_code or print() — only the present_timeline tool renders the UI."
)

_FAKE_TOOL_MARKERS = ("<tool_code>", "print(present_timeline", "present_timeline(view=")


def _reply_looks_like_fake_tool(text: str) -> bool:
    lower = text.lower()
    return any(m.lower() in lower for m in _FAKE_TOOL_MARKERS)

conversation_history: list[dict] = []
analysis_context: dict | None = None


def set_analysis_context(analysis: dict | None):
    global analysis_context
    analysis_context = analysis


@dataclass
class PendingAction:
    action: str
    params: dict
    description: str


@dataclass
class ChatResult:
    reply: str
    pending_actions: list[PendingAction] = field(default_factory=list)


def _tool_to_pending(tool_name: str, args: dict) -> PendingAction | list[PendingAction]:
    action = PROPOSE_TO_ACTION[tool_name]
    if action == "batch_update_texts":
        return PendingAction(
            action=action,
            params={"updates": args["updates"]},
            description=describe_action(action, {"updates": args["updates"]}),
        )
    return PendingAction(
        action=action,
        params=args,
        description=describe_action(action, args),
    )


def _execute_immediate_tool(
    name: str,
    args: dict,
    *,
    project_path: str | None = None,
    timeline_summary: dict | None = None,
    emit: EventEmitter | None = None,
) -> str:
    if name == "search_library":
        result = search_library(
            query=args.get("query", ""),
            asset_type=args.get("asset_type", "all"),
        )
        return json.dumps(result, indent=2)
    if name == "get_director_picks":
        return json.dumps(director_picks(args.get("mood", "energetic")), indent=2)
    if name == "present_timeline":
        if not project_path:
            return json.dumps({"error": "No project loaded — cannot show timeline visual"})
        from agent.timeline_report import build_timeline_visual

        view = args.get("view", "clips")
        report = build_timeline_visual(
            project_path,
            view=view,
            reason=args.get("reason", ""),
            markers=args.get("markers"),
            timeline_summary=timeline_summary,
            include_thumbnails=view in ("clips", "full_scan"),
        )
        if emit:
            emit({"type": "editor_timeline", "report": report})
        return json.dumps({
            "shown": True,
            "view": view,
            "markers": len(args.get("markers") or []),
        })
    return json.dumps({"error": f"Unknown tool: {name}"})


def _collect_from_response(response) -> tuple[str, list[PendingAction], list[dict]]:
    pending: list[PendingAction] = []
    reply_parts: list[str] = []
    immediate_calls: list[dict] = []

    for item in response.output:
        if item.type == "function_call":
            tool_name = (item.name or "").split("<|")[0].strip()
            args = json.loads(item.arguments)
            if tool_name in IMMEDIATE_TOOLS:
                immediate_calls.append({
                    "call_id": getattr(item, "call_id", None) or getattr(item, "id", ""),
                    "name": tool_name,
                    "args": args,
                })
            elif tool_name in PROPOSE_TO_ACTION:
                result = _tool_to_pending(tool_name, args)
                if isinstance(result, list):
                    pending.extend(result)
                else:
                    pending.append(result)
        elif item.type == "message":
            for content in item.content:
                if content.type == "output_text" and content.text:
                    reply_parts.append(content.text)

    reply = "\n".join(reply_parts).strip() or (response.output_text or "").strip()
    return reply, pending, immediate_calls


def _pending_from_suggestions(actions: list[dict]) -> list[PendingAction]:
    return [
        PendingAction(action=a["action"], params=a["params"], description=a["description"])
        for a in actions
    ]


def _dedupe_pending(pending: list[PendingAction]) -> list[PendingAction]:
    seen: set[tuple[str, str]] = set()
    unique: list[PendingAction] = []
    for item in pending:
        key = (item.action, json.dumps(item.params, sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _segment_ids_with_transitions(project_path: str) -> set[str]:
    data = read_project(project_path)
    transition_ids = {t["id"] for t in data["materials"].get("transitions", [])}
    attached: set[str] = set()
    for track in data.get("tracks", []):
        if track.get("type") != "video":
            continue
        for segment in track.get("segments", []):
            refs = segment.get("extra_material_refs", [])
            if any(ref in transition_ids for ref in refs):
                attached.add(segment["id"])
    return attached


def _project_already_has_music(summary: dict, music_name: str = "") -> bool:
    if music_name:
        needle = music_name.lower()
        for audio in summary.get("audio_clips", []):
            name = (audio.get("name") or "").lower()
            if needle in name:
                return True
        return False
    for audio in summary.get("audio_clips", []):
        name = audio.get("name") or ""
        if name and not name.upper().startswith("VID_"):
            return True
    return False


def _analysis_audio_actions(summary: dict) -> list[PendingAction]:
    if not analysis_context or not analysis_context.get("issues"):
        return []
    audio_types = {"quiet", "loud", "clipping", "low_volume"}
    issues = [i for i in analysis_context["issues"] if i.get("type") in audio_types]
    return _pending_from_suggestions(issues_to_actions(issues, summary))


def _quiet_audio_actions(summary: dict, msg: str) -> list[PendingAction]:
    """Volume boosts from FFmpeg analysis and/or timeline clip levels."""
    if not any(kw in msg for kw in ("quiet", "fix quiet", "quiet audio", "louder", "volume")):
        return []

    pending: list[PendingAction] = []
    if analysis_context:
        pending.extend(_analysis_audio_actions(summary))

    seen: set[str] = {
        p.params.get("segment_id", "")
        for p in pending
        if p.action == "update_volume"
    }

    for clip in summary.get("video_clips", []):
        seg_id = clip["segment_id"]
        if seg_id in seen:
            continue
        vol = clip.get("volume", 1.0)
        if vol < 1.0:
            new_vol = min(1.0, round(vol + 0.3, 2)) if vol < 0.75 else 1.0
            pending.append(_tool_to_pending("propose_update_volume", {
                "segment_id": seg_id,
                "volume": new_vol,
            }))
            seen.add(seg_id)

    if ("fix quiet" in msg or "quiet audio" in msg) and not any(
        p.action == "update_volume" for p in pending
    ):
        for clip in summary.get("video_clips", []):
            seg_id = clip["segment_id"]
            if seg_id in seen:
                continue
            vol = clip.get("volume", 1.0)
            if vol < 1.0:
                pending.append(_tool_to_pending("propose_update_volume", {
                    "segment_id": seg_id,
                    "volume": 1.0,
                }))
                seen.add(seg_id)

    return pending


def _analysis_pacing_actions(summary: dict) -> list[PendingAction]:
    if not analysis_context or not analysis_context.get("issues"):
        return []
    pacing_types = {"long_clip"}
    issues = [i for i in analysis_context["issues"] if i.get("type") in pacing_types]
    return _pending_from_suggestions(issues_to_actions(issues, summary))


def _detect_mood(message: str) -> str:
    lower = message.lower()
    for mood in ("energetic", "calm", "dramatic", "fun"):
        if mood in lower:
            return mood
    return "energetic"


def _empty_timeline_reply() -> str:
    return (
        "Your project timeline is **empty** in `draft_info.json` (0 video clips). "
        "CapCut may not have saved your edits to disk yet.\n\n"
        "**In CapCut:** add your clips, press **Cmd+S** to save, then send your edit request again. "
        "Once clips appear in the project summary, I can propose speed changes, transitions, music, and volume fixes."
    )


def _format_timeline_summary_reply(summary: dict) -> str:
    """Local read-only answer — no Groq, no edit planner."""
    ov = summary["overview"]
    clips = summary.get("video_clips", [])
    audio = summary.get("audio_clips", [])
    transitions = summary.get("transitions", [])
    effects = summary.get("effects", [])
    texts = summary.get("text_overlays", [])

    lines = ["**Video clips on your timeline (in order of appearance):**\n"]
    if clips:
        lines.append(
            "| Index | Segment ID | File name | Start time (sec) | Duration (sec) |"
        )
        lines.append("|-------|------------|-----------|------------------|----------------|")
        for c in clips:
            lines.append(
                f"| {c['index']} | {c['segment_id']} | {c['name']} | "
                f"{c['at_sec']:.2f} | {c['duration_sec']:.2f} |"
            )
    else:
        lines.append("_No video clips on disk — save the project in CapCut (Cmd+S)._")

    if audio:
        lines.append("\n**Audio clip(s) on the timeline:**\n")
        lines.append("| Segment ID | Name | Start time (sec) | Duration (sec) |")
        lines.append("|------------|------|------------------|----------------|")
        for a in audio:
            lines.append(
                f"| {a['segment_id']} | {a['name']} | {a['at_sec']:.2f} | {a['duration_sec']:.2f} |"
            )

    extras = []
    if transitions:
        extras.append(f"{len(transitions)} transition(s)")
    if effects:
        extras.append(f"{len(effects)} effect(s)")
    if texts:
        extras.append(f"{len(texts)} text overlay(s)")
    if extras:
        lines.append(f"\nAlso present: {', '.join(extras)}.")
    elif not transitions and not effects and not texts:
        lines.append("\nNo transitions, effects, or text overlays are present in the current project.")

    lines.append(
        f"\n_Total duration: {ov.get('duration_sec', 0):.1f}s · "
        f"{ov.get('video_clip_count', 0)} video · {ov.get('audio_clip_count', 0)} audio_"
    )
    return "\n".join(lines)


def _build_heuristic_plan(
    user_message: str,
    summary: dict,
    project_path: str | None = None,
) -> list[PendingAction]:
    """Fallback when the model returns no proposals after tool calls / rate limits."""
    clips = summary.get("video_clips", [])
    if not clips:
        return []

    pending: list[PendingAction] = []
    msg = user_message.lower()
    sorted_clips = sorted(clips, key=lambda c: c["at_sec"])
    has_transitions = (
        _segment_ids_with_transitions(project_path)
        if project_path
        else set()
    )

    if "reorder" in msg and len(sorted_clips) >= 2:
        pending.append(_tool_to_pending("propose_reorder_clips", {
            "segment_id_a": sorted_clips[0]["segment_id"],
            "segment_id_b": sorted_clips[-1]["segment_id"],
        }))

    if "1.2" in msg or "speed" in msg:
        target_nums: set[int] = set()
        if "clips 2" in msg or "clips 2–3" in msg or "clips 2-3" in msg:
            target_nums = {2, 3}
        elif "clip 2" in msg:
            target_nums = {2}
        speed_val = 1.2
        for i, clip in enumerate(sorted_clips, start=1):
            if not target_nums or i in target_nums:
                pending.append(_tool_to_pending("propose_update_clip_speed", {
                    "segment_id": clip["segment_id"],
                    "speed": speed_val,
                }))

    pending.extend(_quiet_audio_actions(summary, msg))

    if analysis_context and ("energetic" in msg or "pacing" in msg or "trim" in msg):
        pending.extend(_analysis_pacing_actions(summary))

    if "transition" in msg or "pull" in msg:
        pull_hits = search_catalog("pull in", "transition", limit=1)
        query = pull_hits[0]["name"] if pull_hits else "Pull in"
        resource_id = pull_hits[0]["resource_id"] if pull_hits else None
        for clip in sorted_clips[:-1]:
            if clip["segment_id"] in has_transitions:
                continue
            params: dict = {
                "segment_id": clip["segment_id"],
                "query": query,
                "duration_sec": 0.5,
            }
            if resource_id:
                params["resource_id"] = resource_id
            pending.append(_tool_to_pending("propose_add_transition", params))

    if any(kw in msg for kw in ("music", "hype", "replace")):
        music_hits = (
            search_catalog("adrenaline", "music", limit=1)
            or search_catalog("action", "music", limit=1)
            or search_catalog("intense", "music", limit=1)
        )
        if music_hits:
            music_name = music_hits[0]["name"]
            music_params = {
                "query": music_name,
                "start_sec": 0,
                "volume": 0.65,
            }
            if _project_already_has_music(summary, music_name):
                pass
            elif _project_already_has_music(summary):
                pending.append(_tool_to_pending("propose_replace_music", music_params))
            else:
                pending.append(_tool_to_pending("propose_add_music", music_params))

    return _dedupe_pending(pending)


NO_PROJECT_PROMPT = """You are the CapCut AI assistant.
The user has NOT selected a CapCut project in the sidebar.
Tell them clearly: pick their project from the dropdown first — timeline questions, visuals, and edits all need project data.
Do NOT invent captions, clips, or timeline visuals. Do NOT output tool_code, present_timeline, or fake code."""


def _run_streaming_chat(
    input_items: list[dict],
    emit: EventEmitter | None,
) -> ChatResult:
    """Stream a short chat reply (no tools, no huge project dump)."""
    from agent.runtime.model import stream_model_text

    emit_step(emit, "model", "Composing reply…")
    response_start(emit)
    parts: list[str] = []
    for delta in stream_model_text(
        instructions=NO_PROJECT_PROMPT,
        input_items=input_items,
        tools=None,
        max_output_tokens=512,
    ):
        parts.append(delta)
        emit_text_delta(emit, delta)
    reply = "".join(parts).strip() or "How can I help with your CapCut project?"
    emit_step(emit, "model", "Reply complete", "done")
    conversation_history.append({"role": "assistant", "content": reply})
    return ChatResult(reply=reply, pending_actions=[])


def _append_response_to_input(input_items: list, response) -> None:
    """Append model output items for the next turn (Groq has no previous_response_id)."""
    for item in response.output:
        if item.type == "function_call":
            input_items.append({
                "type": "function_call",
                "call_id": getattr(item, "call_id", None) or getattr(item, "id", ""),
                "name": item.name,
                "arguments": item.arguments,
            })
        elif item.type == "message":
            text_parts = []
            for content in item.content:
                if content.type == "output_text" and content.text:
                    text_parts.append(content.text)
            if text_parts:
                input_items.append({
                    "role": "assistant",
                    "content": "\n".join(text_parts),
                })


def hydrate_analysis_from_cache(project_path: str | None) -> None:
    if not project_path:
        return
    from analysis.cache import get_cached

    cached = get_cached(project_path)
    if cached:
        set_analysis_context({
            "score": cached["score"],
            "issues": cached["issues"],
            "clips_analyzed": cached["clips_analyzed"],
        })


def _maybe_run_audio_analysis(
    user_message: str,
    project_path: str,
    emit: EventEmitter | None,
    *,
    run_if_missing: bool = True,
) -> None:
    from analysis.analyzer import analyze_project
    from analysis.cache import get_cached, message_needs_audio_analysis, set_cached

    if not message_needs_audio_analysis(user_message):
        hydrate_analysis_from_cache(project_path)
        return

    cached = get_cached(project_path)
    if cached:
        set_analysis_context({
            "score": cached["score"],
            "issues": cached["issues"],
            "clips_analyzed": cached["clips_analyzed"],
        })
        emit_step(
            emit, "ffmpeg",
            f"Using cached audio analysis (score {cached['score']}/100)",
            "done",
        )
        return

    if not run_if_missing:
        emit_step(
            emit, "ffmpeg",
            "Skipping live FFmpeg scan (use Analyze panel for deep quiet detection)",
            "done",
        )
        return

    emit_step(emit, "ffmpeg", "Analyzing clip audio (FFmpeg)…")
    try:
        analysis = analyze_project(project_path, max_clips=4)
        set_cached(project_path, analysis)
        set_analysis_context({
            "score": analysis["score"],
            "issues": analysis["issues"],
            "clips_analyzed": analysis["clips_analyzed"],
        })
        emit_step(
            emit, "ffmpeg",
            f"Audio analysis ready — score {analysis['score']}/100",
            "done",
            f"{analysis['clips_analyzed']} clip(s) scanned",
        )
    except Exception as e:
        logger.warning("Auto audio analysis failed: %s", e)
        emit_step(emit, "ffmpeg", "Audio analysis skipped", "error", str(e))


def stream_agent_events(
    user_message: str,
    project_path: str | None = None,
    emit: EventEmitter | None = None,
) -> ChatResult:
    """Run the agent loop; emit step/tool events in real time when emit is provided."""
    from core.slices import get_timeline_summary

    context = ""
    summary: dict | None = None
    timeline_compact: dict | None = None
    if project_path:
        emit_step(emit, "load_project", "Reading CapCut timeline from disk…")
        try:
            summary = get_project_summary(project_path)
            overview = summary.get("overview", {})
            clip_count = overview.get("video_clip_count", 0)
            emit_step(
                emit, "load_project", "Timeline loaded", "done",
                f"{clip_count} video clip(s), {overview.get('transition_count', 0)} transition(s)",
            )
            timeline_compact = get_timeline_summary(project_path)
            context = f"\n\nACTIVE PROJECT:\n{json.dumps(timeline_compact, indent=2)}"
            if clip_count == 0:
                context += (
                    "\n\nNOTE: Timeline shows 0 video clips on disk. "
                    "If the user sees clips in CapCut, they may need Cmd+S and Home before edits."
                )
            if analysis_context:
                score = analysis_context.get("score", "?")
                emit_step(emit, "analysis", f"Using FFmpeg analysis (score {score}/100)", "done")
                context += f"\n\nANALYSIS REPORT (FFmpeg):\n{json.dumps(analysis_context, indent=2)}"
        except Exception as e:
            emit_step(emit, "load_project", "Failed to read project", "error", str(e))
            context = f"\n\nError reading project: {e}"

    conversation_history.append({
        "role": "user",
        "content": user_message + context,
    })

    if not project_path:
        input_items = [{"role": m["role"], "content": m["content"]} for m in conversation_history]
        return _run_streaming_chat(input_items, emit)

    tools = _to_responses_tools(TOOLS)
    input_items: list[dict] = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in conversation_history
    ]

    pending: list[PendingAction] = []
    reply_parts: list[str] = []
    nudged = False
    llm_failed = False

    for turn in range(MAX_CHAT_TURNS):
        emit_step(emit, f"model_{turn}", f"Thinking (turn {turn + 1})…")
        from agent.runtime.model import call_model

        response = call_model(
            instructions=SYSTEM_PROMPT,
            input_items=input_items,
            tools=tools,
            temperature=0.5,
            max_output_tokens=1536,
        )
        if response is None:
            llm_failed = True
            emit_step(emit, f"model_{turn}", "Model unavailable", "error")
            break

        step_reply, step_pending, immediate_calls = _collect_from_response(response)

        if (
            not immediate_calls
            and not step_pending
            and step_reply
            and _reply_looks_like_fake_tool(step_reply)
            and turn + 1 < MAX_CHAT_TURNS
        ):
            emit_step(emit, f"model_{turn}", "Requesting real timeline visual…", "done")
            _append_response_to_input(input_items, response)
            input_items.append({"role": "user", "content": VISUAL_NUDGE})
            continue

        if step_reply:
            reply_parts.append(step_reply)
            if emit:
                response_start(emit)
                emit_text_chunks(emit, step_reply, chunk_chars=16)
        from agent.timeline_anchor import describe_timeline_target

        for item in step_pending:
            anchor = describe_timeline_target(item.action, item.params, summary)
            emit_proposal(
                emit, item.description, item.action,
                anchor=anchor or None, agent="Edit Agent",
            )
        pending.extend(step_pending)

        if immediate_calls:
            emit_step(emit, f"model_{turn}", "Running catalog tools…", "done")
            _append_response_to_input(input_items, response)
            for call in immediate_calls:
                emit_tool_call(emit, call["name"], call["args"])
                output = _execute_immediate_tool(
                    call["name"],
                    call["args"],
                    project_path=project_path,
                    timeline_summary=timeline_compact,
                    emit=emit,
                )
                emit_tool_result(emit, call["name"], summarize_tool_output(call["name"], output))
                input_items.append({
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "name": call["name"],
                    "output": output,
                })
            continue

        if step_pending:
            emit_step(emit, f"model_{turn}", f"Received {len(step_pending)} proposal(s)", "done")
            break

        emit_step(emit, f"model_{turn}", "Response complete", "done")
        break

    reply = "\n".join(reply_parts).strip()

    if llm_failed and not reply:
        reply = (
            "The AI model is temporarily unavailable (rate limit or API error on Groq/Gemini). "
            "Try again in a moment, or set LLM_PROVIDER=gemini / LLM_PROVIDER=groq to force one provider."
        )
        emit_step(emit, "model", "Model unavailable", "error")

    pending = _dedupe_pending(pending)

    if pending:
        plan = "\n".join(f"  • {a.description}" for a in pending)
        reply = (reply + "\n\n**Planned changes (awaiting your approval):**\n" + plan).strip()

    if not reply and analysis_context and summary:
        score = analysis_context.get("score", "?")
        fixes = issues_to_actions(analysis_context.get("issues", []), summary)
        fix_lines = "\n".join(f"  • {f['description']}" for f in fixes[:6])
        reply = (
            f"Your FFmpeg analysis scored **{score}/100**. "
            "Describe an edit (e.g. \"make it energetic\") or say **apply analysis fixes**.\n\n"
            f"**Available auto-fixes:**\n{fix_lines}"
        )

    reply = reply or "How can I help with your CapCut project?"
    conversation_history.append({"role": "assistant", "content": reply})
    return ChatResult(reply=reply, pending_actions=pending)


def chat(user_message: str, project_path: str | None = None) -> ChatResult:
    return stream_agent_events(user_message, project_path)


def iter_agent_sse(user_message: str, project_path: str | None = None):
    """Yield SSE lines while the agent runs (threaded producer)."""
    import queue
    import threading

    from agent.streaming import sse_line

    # Immediate ping so the UI shows progress before any heavy work
    yield sse_line({"type": "agent_start", "message": "CapCut edit agent started"})

    event_q: queue.Queue = queue.Queue()
    result_box: dict = {}

    def emit(event: dict) -> None:
        event_q.put(event)

    def run() -> None:
        try:
            result_box["result"] = stream_agent_events(user_message, project_path, emit=emit)
        except Exception as e:
            logger.exception("Agent stream error")
            result_box["error"] = str(e)
        finally:
            event_q.put(None)

    threading.Thread(target=run, daemon=True).start()

    import time

    while True:
        event = event_q.get()
        if event is None:
            break
        yield sse_line(event)

    if result_box.get("error"):
        yield sse_line({"type": "error", "message": result_box["error"]})
        return

    result: ChatResult = result_box["result"]
    action_dicts = [
        {"action": a.action, "params": a.params, "description": a.description}
        for a in result.pending_actions
    ]
    done_event: dict = {
        "type": "done",
        "reply": result.reply,
        "pending_actions": action_dicts,
    }
    if project_path and action_dicts:
        from agent.diff import compute_edit_diff

        done_event["edit_diff"] = compute_edit_diff(project_path, action_dicts)
    yield sse_line(done_event)


def format_execute_reply(results: list[str]) -> str:
    summary = "\n".join(f"  ✓ {r}" for r in results)
    return (
        f"Done! Applied {len(results)} change(s):\n{summary}\n\n"
        "Check your timeline in CapCut — the agent closed and reopened the project to apply edits."
    )


def record_assistant_reply(reply: str) -> None:
    conversation_history.append({"role": "assistant", "content": reply})


def confirm_actions(actions: list[dict], project_path: str) -> str:
    results = execute_actions(actions, project_path)
    reply = format_execute_reply(results)
    record_assistant_reply(reply)
    return reply


def reject_actions(reason: str = "User rejected the proposed changes.") -> str:
    conversation_history.append({"role": "assistant", "content": reason})
    return reason
