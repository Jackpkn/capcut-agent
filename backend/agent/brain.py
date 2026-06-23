import json
import logging
from dataclasses import dataclass, field

from dotenv import load_dotenv
from agent.actions import describe_action, execute_actions
from agent.streaming import (
    EventEmitter,
    emit_text_chunks,
    emit_thinking_chunks,
    model_thinking_delta,
    model_thinking_end,
    model_thinking_start,
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
from capcut.media_names import is_background_music_name
from capcut.reader import get_project_summary, read_project

load_dotenv()

logger = logging.getLogger(__name__)

from agent.prompts import (
    ANSWER_SYSTEM_PROMPT,
    EDIT_SYSTEM_PROMPT,
    EMPTY_REPLY_NUDGE as _EMPTY_REPLY_NUDGE,
    NO_PROJECT_PROMPT,
    SYNTHESIS_NUDGE,
    edit_retry_nudge as _edit_retry_nudge,
)

SYSTEM_PROMPT = EDIT_SYSTEM_PROMPT

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
            "description": (
                "Add a transition after a video clip (between that clip and the next). "
                "Set segment_id, clip_index, or placement from where the user wants it. "
                "See video_clips[].transition for what each cut already has."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "segment_id": {
                        "type": "string",
                        "description": "Exact segment_id UUID from video_clips (optional if placement/clip_index set)",
                    },
                    "clip_index": {
                        "type": "integer",
                        "description": "1-based clip index — transition goes after this clip",
                    },
                    "placement": {
                        "type": "string",
                        "enum": ["end", "first", "between", "after_clip"],
                        "description": "end=last cut, first=after clip 1, after_clip=use clip_index",
                    },
                    "after_clip_index": {
                        "type": "integer",
                        "description": "For between/after_clip — transition after this clip number",
                    },
                    "query": {"type": "string"},
                    "resource_id": {"type": "string"},
                    "duration_sec": {"type": "number"},
                },
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
            "name": "propose_split_clip",
            "description": "Propose splitting a video clip at a timeline position (seconds within the clip).",
            "parameters": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "string"},
                    "at_sec": {"type": "number", "description": "Split point in seconds on the timeline"},
                },
                "required": ["segment_id", "at_sec"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_duck_audio",
            "description": (
                "Propose ducking background music under voice (lowers music volume). "
                "Omit segment_id to duck the main audio/music track."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "music_segment_id": {"type": "string"},
                    "volume": {"type": "number", "description": "Target volume 0.0–1.0 (default 0.2)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_sync_video_to_beats",
            "description": "Propose aligning video cuts (boundaries) to background music beat intervals (pacing sync).",
            "parameters": {
                "type": "object",
                "properties": {
                    "bpm": {"type": "number", "description": "Tempo in BPM to align clip boundaries to (default 120.0, i.e. 0.5s per beat)"},
                    "beat_interval": {"type": "number", "description": "Explicit beat interval in seconds (optional, overrides bpm)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "propose_apply_color_preset",
            "description": (
                "Propose a color grade / filter preset across the timeline or a clip. "
                "Presets: cinematic, warm, cool, vintage, vivid, teal_orange, moody — or a catalog query."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "preset": {"type": "string"},
                    "start_sec": {"type": "number"},
                    "duration_sec": {"type": "number"},
                    "bind_segment_id": {"type": "string"},
                },
                "required": ["preset"],
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
    {
        "type": "function",
        "function": {
            "name": "propose_draft_operations",
            "description": (
                "Propose one or more timeline operations in a single batch. "
                "Prefer this for splits, deletes, multi-clip edits, or mixed changes. "
                "Use exact segment_id / text_id from WORKING SLICE."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Short human-readable summary of the edit plan",
                    },
                    "operations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": {
                                    "type": "string",
                                    "description": (
                                        "segment.split | segment.delete | segment.set | segment.move | "
                                        "segment.trim | segment.hide | segment.show | transition.add | "
                                        "transition.remove | transition.update | clip.speed | clip.volume | "
                                        "clip.reorder | text.update | text.batch_update | effect.add | "
                                        "effect.remove | music.add | music.replace"
                                    ),
                                },
                                "segment_id": {"type": "string"},
                                "text_id": {"type": "string"},
                                "at_sec": {"type": "number"},
                                "start_sec": {"type": "number"},
                                "duration_sec": {"type": "number"},
                                "field": {"type": "string"},
                                "value": {},
                                "speed": {"type": "number"},
                                "volume": {"type": "number"},
                                "query": {"type": "string"},
                                "name": {"type": "string"},
                                "content": {"type": "string"},
                                "segment_id_a": {"type": "string"},
                                "segment_id_b": {"type": "string"},
                                "effect_id": {"type": "string"},
                                "transition_id": {"type": "string"},
                                "updates": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "text_id": {"type": "string"},
                                            "content": {"type": "string"},
                                        },
                                    },
                                },
                            },
                            "required": ["op"],
                        },
                    },
                },
                "required": ["operations", "summary"],
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
    "propose_split_clip": "split_clip",
    "propose_duck_audio": "duck_audio",
    "propose_sync_video_to_beats": "sync_video_to_beats",
    "propose_apply_color_preset": "apply_color_preset",
    "propose_generate_image": "generate_image",
    "propose_generate_video_clip": "generate_video_clip",
    "propose_draft_operations": "draft_operations",
}

IMMEDIATE_TOOLS = {"search_library", "get_director_picks", "present_timeline"}

MAX_CHAT_TURNS = 6
MAX_HISTORY_TURNS = 10

conversation_history: list[dict] = []
_last_project_path: str | None = None
analysis_context: dict | None = None
clip_intelligence_context: list[dict] = []


def clear_conversation() -> None:
    """Reset conversation history — call on project switch or new session."""
    global conversation_history
    conversation_history = []


def _trim_history() -> None:
    """Keep only the last MAX_HISTORY_TURNS pairs to prevent unbounded growth."""
    global conversation_history
    if len(conversation_history) > MAX_HISTORY_TURNS * 2:
        conversation_history = conversation_history[-(MAX_HISTORY_TURNS * 2):]


def set_analysis_context(analysis: dict | None):
    global analysis_context
    analysis_context = analysis


def set_clip_intelligence_context(clips: list[dict] | None) -> None:
    global clip_intelligence_context
    clip_intelligence_context = list(clips or [])


def hydrate_clip_intelligence_from_cache(project_path: str | None) -> list[dict]:
    """Load persisted clip understanding (no re-run)."""
    if not project_path:
        set_clip_intelligence_context([])
        return []
    from analysis.clip_intelligence import load_project_intelligence

    clips = load_project_intelligence(project_path)
    set_clip_intelligence_context(clips)
    return clips


@dataclass
class PendingAction:
    action: str
    params: dict
    description: str


@dataclass
class ChatResult:
    reply: str
    pending_actions: list[PendingAction] = field(default_factory=list)
    thinking: str = ""


def _tool_to_pending(tool_name: str, args: dict) -> PendingAction | list[PendingAction]:
    action = PROPOSE_TO_ACTION[tool_name]
    if action == "batch_update_texts":
        return PendingAction(
            action=action,
            params={"updates": args["updates"]},
            description=describe_action(action, {"updates": args["updates"]}),
        )
    if action == "draft_operations":
        ops = args.get("operations", [])
        return PendingAction(
            action=action,
            params={"operations": ops},
            description=args.get("summary") or describe_action(action, {"operations": ops}),
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
    from agent.runtime.tools import normalize_tool_name

    pending: list[PendingAction] = []
    reply_parts: list[str] = []
    immediate_calls: list[dict] = []

    for item in response.output:
        if item.type == "function_call":
            tool_name = normalize_tool_name((item.name or "").split("<|")[0].strip())
            try:
                args = json.loads(item.arguments or "{}")
            except json.JSONDecodeError:
                logger.warning("Bad tool JSON from model: %s", item.arguments)
                continue
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
            else:
                logger.warning("Unknown propose tool from model: %s", tool_name)
        elif item.type == "message":
            for content in item.content:
                if content.type == "output_text" and content.text:
                    reply_parts.append(content.text)

    reply = "\n".join(reply_parts).strip() or (response.output_text or "").strip()
    if not reply:
        thinking_text = getattr(response, "thinking_text", "") or ""
        if thinking_text:
            from agent.runtime.ollama_provider import extract_visible_reply_from_thinking

            reply = extract_visible_reply_from_thinking(thinking_text) or ""
    return reply, pending, immediate_calls


def _pending_from_suggestions(actions: list[dict]) -> list[PendingAction]:
    return [
        PendingAction(action=a["action"], params=a["params"], description=a["description"])
        for a in actions
    ]


def _normalize_pending_list(
    pending: list[PendingAction],
    summary: dict | None,
    *,
    user_message: str = "",
) -> list[PendingAction]:
    from agent.actions import describe_action
    from capcut.segment_resolve import normalize_pending_params

    clips = (summary or {}).get("video_clips", [])
    out: list[PendingAction] = []
    for item in pending:
        params = normalize_pending_params(
            item.action, item.params, clips, user_message=user_message,
        )
        if params is None:
            logger.warning("Dropped invalid segment_id for %s: %s", item.action, item.params)
            continue
        if params != item.params:
            item = PendingAction(
                action=item.action,
                params=params,
                description=describe_action(item.action, params),
            )
        out.append(item)
    return out


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
        if is_background_music_name(name):
            return True
    return False


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


def _collect_streamed_reply(
    input_items: list[dict],
    emit: EventEmitter | None,
    *,
    instructions: str,
    max_output_tokens: int,
    agent: str,
    think: bool | None = None,
) -> tuple[str, str]:
    """Stream one chat turn; returns (visible_reply, thinking_text)."""
    from agent.runtime.model import stream_model_text

    thinking_started = False
    thinking_parts: list[str] = []
    parts: list[str] = []
    answer_started = False
    for channel, delta in stream_model_text(
        instructions=instructions,
        input_items=input_items,
        tools=None,
        max_output_tokens=max_output_tokens,
        think=think,
    ):
        if channel == "thinking":
            thinking_parts.append(delta)
            if not thinking_started:
                model_thinking_start(emit, agent=agent)
                thinking_started = True
            model_thinking_delta(emit, delta)
            continue
        if thinking_started and not answer_started:
            model_thinking_end(emit)
            thinking_started = False
        if not answer_started:
            response_start(emit)
            answer_started = True
        parts.append(delta)
        emit_text_delta(emit, delta)
    if thinking_started:
        model_thinking_end(emit)
    reply = "".join(parts).strip()
    thinking = "".join(thinking_parts).strip()
    if not reply and thinking:
        from agent.runtime.ollama_provider import extract_visible_reply_from_thinking

        reply = extract_visible_reply_from_thinking(thinking) or ""
    if not parts and reply and not answer_started:
        response_start(emit)
        from agent.streaming import emit_text_chunks

        emit_text_chunks(emit, reply, chunk_chars=10)
    return reply, thinking


def _run_streaming_chat(
    input_items: list[dict],
    emit: EventEmitter | None,
    *,
    instructions: str = NO_PROJECT_PROMPT,
    max_output_tokens: int = 512,
    agent: str = "chat",
    think: bool | None = None,
) -> ChatResult:
    """Stream a chat reply (no tools)."""
    emit_step(emit, "model", "Composing reply…")
    reply, thinking = _collect_streamed_reply(
        input_items,
        emit,
        instructions=instructions,
        max_output_tokens=max_output_tokens,
        agent=agent,
        think=think,
    )
    if not reply.strip():
        emit_step(emit, "model", "Empty reply — retrying…")
        retry_items = [*input_items, {"role": "user", "content": _EMPTY_REPLY_NUDGE}]
        retry_reply, retry_thinking = _collect_streamed_reply(
            retry_items,
            emit,
            instructions=instructions,
            max_output_tokens=max_output_tokens,
            agent=agent,
            think=think,
        )
        if retry_reply.strip():
            reply = retry_reply
        if retry_thinking:
            thinking = f"{thinking}\n\n{retry_thinking}".strip() if thinking else retry_thinking
    emit_step(emit, "model", "Reply complete", "done")
    conversation_history.append({"role": "assistant", "content": reply})
    return ChatResult(reply=reply, pending_actions=[], thinking=thinking)


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


def _history_to_input_items(history: list[dict]) -> list[dict]:
    items: list[dict] = []
    for msg in history:
        item: dict = {"role": msg["role"], "content": msg["content"]}
        if msg.get("images"):
            item["images"] = msg["images"]
        items.append(item)
    return items


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
        if cached.get("clip_intelligence"):
            set_clip_intelligence_context(cached["clip_intelligence"])


def stream_agent_events(
    user_message: str,
    project_path: str | None = None,
    emit: EventEmitter | None = None,
    *,
    answer_only: bool = False,
    project_summary: dict | None = None,
    images: list[str] | None = None,
    preprocessed_images: bool = False,
) -> ChatResult:
    """Run the agent loop; emit step/tool events in real time when emit is provided."""
    global _last_project_path
    from core.retrieve_context import retrieve_context

    # Reset conversation when project changes to avoid stale segment IDs
    if project_path != _last_project_path:
        clear_conversation()
        _last_project_path = project_path

    _trim_history()

    from agent.user_images import enrich_user_message, normalize_images

    if preprocessed_images:
        enriched_message = user_message
        image_b64 = normalize_images(images)
    else:
        if images:
            emit_step(emit, "user_images", "Analyzing attached image(s)…", "running")
        enriched_message, image_b64 = enrich_user_message(user_message, images)
        if images:
            if image_b64:
                emit_step(
                    emit, "user_images",
                    f"Attached {len(image_b64)} reference image(s)",
                    "done",
                )
            else:
                emit_step(
                    emit, "user_images",
                    "Could not read attached image(s)",
                    "error",
                    "Use JPEG or PNG under 3MB",
                )

    context = ""
    summary: dict | None = None
    timeline_compact: dict | None = None
    if project_path:
        try:
            if project_summary is not None:
                summary = project_summary
                emit_step(emit, "load_project", "Using preloaded timeline", "done")
            else:
                emit_step(emit, "load_project", "Reading CapCut timeline from disk…")
                summary = get_project_summary(project_path)
            overview = summary.get("overview", {})
            clip_count = overview.get("video_clip_count", 0)
            if project_summary is None:
                emit_step(
                    emit, "load_project", "Timeline loaded", "done",
                    f"{clip_count} video clip(s), {overview.get('transition_count', 0)} transition(s)",
                )
            else:
                emit_step(
                    emit, "load_project", "Timeline ready", "done",
                    f"{clip_count} video clip(s), {overview.get('transition_count', 0)} transition(s)",
                )
            retrieved = retrieve_context(
                project_path,
                user_message,
                analysis=analysis_context,
                project_summary=summary,
            )
            emit_step(
                emit, "retrieve",
                "Loaded timeline slice", "done",
                ", ".join(retrieved.domains) + (
                    f" — {retrieved.retrieval_notes[0]}" if retrieved.retrieval_notes else ""
                ),
            )
            context = f"\n\n{retrieved.to_prompt_block()}"
            timeline_compact = retrieved.catalog
            if clip_count == 0:
                context += (
                    "\n\nNOTE: Timeline shows 0 video clips on disk. "
                    "If the user sees clips in CapCut, they may need Cmd+S and Home before edits."
                )
        except Exception as e:
            emit_step(emit, "load_project", "Failed to read project", "error", str(e))
            context = f"\n\nError reading project: {e}"

    user_entry: dict = {
        "role": "user",
        "content": enriched_message + context,
    }
    if image_b64:
        user_entry["images"] = image_b64
    conversation_history.append(user_entry)

    if not project_path:
        return _run_streaming_chat(_history_to_input_items(conversation_history), emit)

    if answer_only:
        return _run_streaming_chat(
            _history_to_input_items(conversation_history),
            emit,
            instructions=ANSWER_SYSTEM_PROMPT,
            max_output_tokens=768 if image_b64 else 384,
            agent="chat",
            think=False if image_b64 else None,
        )

    tools = _to_responses_tools(TOOLS)
    input_items: list[dict] = _history_to_input_items(conversation_history)

    pending: list[PendingAction] = []
    reply_parts: list[str] = []
    thinking_parts: list[str] = []
    llm_failed = False

    for turn in range(MAX_CHAT_TURNS):
        emit_step(emit, f"model_{turn}", f"Thinking (turn {turn + 1})…")
        from agent.runtime.model import call_model

        response = call_model(
            instructions=EDIT_SYSTEM_PROMPT,
            input_items=input_items,
            tools=tools,
            temperature=0.3,
            max_output_tokens=1024,
            agent="chat",
            emit=emit,
        )
        if response is None:
            llm_failed = True
            emit_step(emit, f"model_{turn}", "Model unavailable", "error")
            break

        step_reply, step_pending, immediate_calls = _collect_from_response(response)
        has_proposal = bool(step_pending or immediate_calls)

        if not has_proposal and turn + 1 < MAX_CHAT_TURNS:
            emit_step(emit, f"model_{turn}", "No proposal yet — retrying…", "done")
            _append_response_to_input(input_items, response)
            input_items.append({"role": "user", "content": _edit_retry_nudge(user_message)})
            continue

        if step_reply:
            reply_parts.append(step_reply)
        from agent.timeline_anchor import describe_timeline_target

        normalized_step = _normalize_pending_list(
            step_pending, summary, user_message=enriched_message,
        )
        for item in normalized_step:
            anchor = describe_timeline_target(item.action, item.params, summary)
            emit_proposal(
                emit, item.description, item.action,
                anchor=anchor or None, agent="Edit Agent",
            )
        pending.extend(normalized_step)

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
            "The AI model is temporarily unavailable. "
            "**Local:** run `ollama serve` and `ollama pull gemma4` (set LLM_PROVIDER=ollama). "
            "**Cloud:** check Groq/Gemini keys or rate limits."
        )
        emit_step(emit, "model", "Model unavailable", "error")

    pending = _normalize_pending_list(pending, summary, user_message=enriched_message)
    pending = _dedupe_pending(pending)

    # Only attempt a final retry if the main loop used few turns (≤2),
    # otherwise we already retried enough and would just burn rate limits.
    if not pending and not llm_failed and turn <= 2:
        from agent.runtime.model import call_model
        from agent.timeline_anchor import describe_timeline_target

        emit_step(emit, "model", "No proposal — final tool attempt…")
        retry_response = call_model(
            instructions=EDIT_SYSTEM_PROMPT,
            input_items=[
                *input_items,
                {"role": "user", "content": _edit_retry_nudge(user_message)},
            ],
            tools=tools,
            temperature=0.3,
            max_output_tokens=1024,
            agent="chat",
            emit=emit,
        )
        if retry_response is not None:
            retry_reply, retry_pending, _ = _collect_from_response(retry_response)
            if retry_pending:
                for item in retry_pending:
                    anchor = describe_timeline_target(item.action, item.params, summary)
                    emit_proposal(
                        emit, item.description, item.action,
                        anchor=anchor or None, agent="Edit Agent",
                    )
                pending.extend(retry_pending)
            if retry_reply.strip():
                reply = retry_reply

    pending = _normalize_pending_list(pending, summary, user_message=enriched_message)
    pending = _dedupe_pending(pending)
    if project_path and pending:
        from agent.plan_guard import collapse_redundant_pending

        pending = collapse_redundant_pending(pending, summary or {}, project_path)

    if pending:
        plan = "\n".join(f"  • {a.description}" for a in pending)
        if reply:
            reply = (reply + "\n\n**Planned changes (awaiting your approval):**\n" + plan).strip()
        else:
            reply = (
                f"I've queued **{len(pending)}** change(s) for your timeline:\n{plan}\n\n"
                "Review the amber **Approve** bar when you're ready."
            )

    conversation_history.append({"role": "assistant", "content": reply})
    return ChatResult(
        reply=reply,
        pending_actions=pending,
        thinking="\n\n".join(thinking_parts).strip(),
    )


def iter_agent_sse(
    user_message: str,
    project_path: str | None = None,
    *,
    answer_only: bool = False,
    project_summary: dict | None = None,
    images: list[str] | None = None,
    preprocessed_images: bool = False,
    trust_apply: bool = False,
):
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
            result_box["result"] = stream_agent_events(
                user_message,
                project_path,
                emit=emit,
                answer_only=answer_only,
                project_summary=project_summary,
                images=images,
                preprocessed_images=preprocessed_images,
            )
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
    from core.task_deps import order_action_dicts

    action_dicts = order_action_dicts(action_dicts)
    reply = result.reply
    done_event: dict = {
        "type": "done",
        "reply": reply,
        "pending_actions": action_dicts,
    }
    if result.thinking:
        done_event["thinking"] = result.thinking
    if project_path and action_dicts:
        from agent.diff import compute_edit_diff
        from agent.qa_agent import review_pending_actions
        from core.project_ledger import record_proposed_edits

        approved, blocked, reviews = review_pending_actions(
            action_dicts,
            project_path,
            project_summary=project_summary,
        )
        done_event["qa_review"] = reviews
        if blocked:
            done_event["qa_blocked"] = blocked
        action_dicts = approved
        done_event["pending_actions"] = action_dicts
        if blocked and not approved:
            issues = "; ".join(
                f"{b.get('description') or b['action']}: {', '.join(b.get('qa_issues', []))}"
                for b in blocked
            )
            reply = f"{reply}\n\n**QA blocked all proposals:** {issues}"
            done_event["reply"] = reply
        elif blocked:
            reply = (
                f"{reply}\n\n_QA blocked {len(blocked)} invalid proposal(s) — "
                "only the valid ones are listed for approval._"
            )
            done_event["reply"] = reply

        if action_dicts:
            record_proposed_edits(project_path, action_dicts)
            done_event["edit_diff"] = compute_edit_diff(project_path, action_dicts)
    yield sse_line(done_event)

    if trust_apply and project_path and action_dicts:
        from agent.actions import iter_execute_sse

        yield sse_line({
            "type": "trust_apply_start",
            "count": len(action_dicts),
            "note": "Trust mode — applying proposals without manual approve.",
        })
        yield from iter_execute_sse(action_dicts, project_path)


def format_execute_reply(results: list[str]) -> str:
    summary = "\n".join(f"  ✓ {r}" for r in results)
    return (
        f"Done! Applied {len(results)} change(s):\n{summary}\n\n"
        "Check your timeline in CapCut — the agent closed and reopened the project to apply edits."
    )


def record_assistant_reply(reply: str) -> None:
    conversation_history.append({"role": "assistant", "content": reply})


def reject_actions(reason: str = "User rejected the proposed changes.") -> str:
    conversation_history.append({"role": "assistant", "content": reason})
    return reason
