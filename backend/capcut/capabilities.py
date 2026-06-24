"""Semantic capability catalog — what CapCut can do and WHY, not just key names.

The automation brain matches user *intent* to capabilities by purpose, not by
remembering that Cmd+S is called "save".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Layer = Literal["disk", "shortcut", "rpa", "pipeline", "ui", "script"]


@dataclass
class Capability:
    id: str
    layer: Layer
    purpose: str
    """Human goal this achieves — e.g. 'Persist project edits safely'."""
    intents: list[str]
    """Natural phrases users say for this goal."""
    mechanism: str
    """How it is executed (disk write, keystroke, UI click, etc.)."""
    action: str  # internal dispatcher key
    default_params: dict[str, Any] = field(default_factory=dict)
    prefers_over: list[str] = field(default_factory=list)
    """Other capability ids to use instead when possible (e.g. Whisper > native captions)."""

    def to_brief(self) -> dict[str, str]:
        return {
            "id": self.id,
            "layer": self.layer,
            "purpose": self.purpose,
            "mechanism": self.mechanism,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Rich purpose overlay for shortcuts (keys are shortcut registry names)
_SHORTCUT_PURPOSE: dict[str, dict[str, Any]] = {
    "save": {
        "purpose": "Persist the open project so timeline edits are written to disk",
        "intents": ["save", "save project", "store", "keep changes", "write to disk", "cmd s"],
    },
    "export": {
        "purpose": "Render the finished video to a file (open export dialog)",
        "intents": ["export", "render", "output video", "download mp4", "publish", "cmd e"],
    },
    "undo": {
        "purpose": "Revert the last edit action",
        "intents": ["undo", "go back", "mistake", "revert last change"],
    },
    "redo": {
        "purpose": "Re-apply an edit that was undone",
        "intents": ["redo", "bring back", "restore undone"],
    },
    "play_pause": {
        "purpose": "Preview timeline playback — start or stop",
        "intents": ["play", "pause", "preview", "watch", "spacebar"],
    },
    "split": {
        "purpose": "Cut the selected clip at the playhead into two pieces",
        "intents": ["split", "cut clip", "slice", "break at playhead", "razor"],
    },
    "split_blade": {
        "purpose": "Activate blade tool to cut clips on the timeline",
        "intents": ["blade", "cut tool", "razor tool"],
    },
    "default_transition": {
        "purpose": "Apply CapCut's default crossfade between adjacent clips",
        "intents": ["transition", "crossfade", "smooth cut", "default transition"],
    },
    "duplicate": {
        "purpose": "Copy the selected clip in place on the timeline",
        "intents": ["duplicate", "copy clip", "clone clip"],
    },
    "delete": {
        "purpose": "Remove the selected clip or element from the timeline",
        "intents": ["delete", "remove clip", "trash", "get rid of"],
    },
    "search_library": {
        "purpose": "Search CapCut's built-in library for music, effects, filters",
        "intents": ["search library", "find music", "find effect", "browse assets"],
    },
    "copy": {"purpose": "Copy selected timeline element to clipboard", "intents": ["copy"]},
    "paste": {"purpose": "Paste clipboard content onto timeline", "intents": ["paste"]},
    "select_tool": {"purpose": "Switch to selection mode for moving clips", "intents": ["select", "selection tool", "arrow tool"]},
    "confirm": {"purpose": "Confirm the active dialog (OK / Export / Apply)", "intents": ["confirm", "ok", "accept", "enter"]},
    "escape": {"purpose": "Cancel or close the active panel or dialog", "intents": ["cancel", "close", "escape", "dismiss"]},
}


def _disk_capabilities() -> list[Capability]:
    specs: list[tuple[str, str, list[str], str, dict]] = [
        (
            "generate_captions",
            "Add speech-synced subtitle text across the video (free Whisper path)",
            ["captions", "subtitles", "transcribe", "speech to text", "auto captions"],
            "Writes caption materials directly to draft JSON via Whisper",
            {"style": "travel"},
        ),
        (
            "apply_color_preset",
            "Apply cinematic color grading / mood to the whole video",
            ["color grade", "cinematic", "warm look", "filter", "moody", "vintage color"],
            "Adds a filter track with built-in CapCut filter resource IDs",
            {"preset": "cinematic"},
        ),
        (
            "fade_project_music",
            "Smooth music entry at start and exit at end of the video",
            ["fade in music", "fade out music", "music fade", "audio fade"],
            "Sets audio fade objects on the background music segment",
            {"fade_in_sec": 2.0, "fade_out_sec": 3.0},
        ),
        (
            "duck_audio",
            "Lower background music volume under voice or speech",
            ["duck music", "lower music under voice", "music under dialogue"],
            "Reduces music segment volume during speech regions",
            {"volume": 0.25},
        ),
        (
            "sync_video_to_beats",
            "Align video cuts to music beats for rhythmic pacing",
            ["beat sync", "sync to music", "cut on beat", "rhythm edit"],
            "Adjusts clip boundaries to BPM grid",
            {"bpm": 120.0},
        ),
        (
            "add_transition",
            "Add a visual transition between two clips",
            ["add transition", "wipe", "dissolve between clips"],
            "Inserts transition material between clip segments",
            {},
        ),
        (
            "add_effect",
            "Add a motion or scene visual effect overlay",
            ["add effect", "visual effect", "zoom effect", "glitch"],
            "Inserts effect track segment from catalog",
            {},
        ),
        (
            "add_music",
            "Add background music bed to the timeline",
            ["add music", "background music", "soundtrack"],
            "Resolves music from catalog and appends audio segment",
            {},
        ),
        (
            "trim_clip",
            "Shorten or extend a clip's in/out points",
            ["trim", "shorten clip", "cut ends", "extend clip"],
            "Updates source_timerange on segment",
            {},
        ),
        (
            "split_clip",
            "Split one clip into two at a specific time",
            ["split at time", "cut at second"],
            "Duplicates segment and adjusts timeranges",
            {},
        ),
        (
            "reorder_clips",
            "Change the sequence of video clips",
            ["reorder", "swap clips", "rearrange timeline"],
            "Reorders primary video track segments",
            {},
        ),
        (
            "import_clips",
            "Import new video/photo/audio files onto the timeline",
            ["import", "add clips", "bring in footage"],
            "Probes media and appends materials + segments",
            {},
        ),
        (
            "execute_capcut_script",
            "Run arbitrary sandboxed Python for edits not covered elsewhere",
            ["custom edit", "complex transform", "keyframes batch", "anything else"],
            "Sandboxed script with writer/primitives API",
            {},
        ),
        (
            "verify_project",
            "Check timeline state matches expectations after edits",
            ["verify", "qa", "check result", "did it work"],
            "Runs post-apply assertions on draft JSON",
            {},
        ),
    ]
    return [
        Capability(
            id=s[0],
            layer="disk",
            purpose=s[1],
            intents=s[2],
            mechanism=s[3],
            action=s[0],
            default_params=s[4],
        )
        for s in specs
    ]


def _shortcut_capabilities() -> list[Capability]:
    from capcut.shortcuts import CAPCUT_SHORTCUTS

    out: list[Capability] = []
    for name, meta in CAPCUT_SHORTCUTS.items():
        overlay = _SHORTCUT_PURPOSE.get(name, {})
        purpose = overlay.get("purpose") or meta.get("desc") or name
        intents = overlay.get("intents") or [name.replace("_", " ")]
        out.append(
            Capability(
                id=f"shortcut:{name}",
                layer="shortcut",
                purpose=purpose,
                intents=intents if isinstance(intents, list) else [intents],
                mechanism=f"Sends CapCut desktop keystroke ({meta.get('desc', name)})",
                action="shortcut",
                default_params={"shortcut_name": name},
            )
        )
    return out


def _rpa_capabilities() -> list[Capability]:
    specs = [
        (
            "rpa:auto_design",
            "Open CapCut AI / AutoCut / smart template creation UI",
            ["auto design", "smart template", "autocut", "ai edit", "capcut ai"],
            "Clicks AI-related controls in CapCut home/editor",
            {"rpa_action": "auto_design"},
        ),
        (
            "rpa:auto_cutout",
            "Remove background from a clip using CapCut native cutout",
            ["cutout", "remove background", "green screen", "isolate subject"],
            "UI automation on Video → Cutout panel",
            {"rpa_action": "auto_cutout"},
        ),
        (
            "rpa:auto_captions",
            "Open CapCut's native (often paid) auto-caption panel",
            ["native captions", "capcut captions ui"],
            "Opens Text → Auto captions in app UI",
            {"rpa_action": "auto_captions"},
            ["generate_captions"],
        ),
        (
            "rpa:search_library",
            "Search CapCut in-app asset library",
            ["search capcut library", "find stock music in app"],
            "UI search in Music/Effects/Filters panel",
            {"rpa_action": "search_library"},
        ),
        (
            "rpa:download_asset",
            "Download an asset from CapCut library into local cache",
            ["download effect", "download music from capcut"],
            "Search + click to cache asset",
            {"rpa_action": "download_asset"},
        ),
        (
            "rpa:focus",
            "Bring CapCut to foreground for further UI steps",
            ["focus capcut", "switch to capcut"],
            "Activates CapCut process",
            {"rpa_action": "focus"},
        ),
    ]
    caps: list[Capability] = []
    for row in specs:
        prefers = row[5] if len(row) > 5 else []
        caps.append(
            Capability(
                id=row[0],
                layer="rpa",
                purpose=row[1],
                intents=row[2],
                mechanism=row[3],
                action="rpa_capcut",
                default_params=row[4],
                prefers_over=prefers,
            )
        )
    return caps


def _pipeline_capabilities() -> list[Capability]:
    return [
        Capability(
            id="pipeline:full_edit",
            layer="pipeline",
            purpose="One-shot pro polish: captions, duck, fade, color, sync, save, verify",
            intents=[
                "full edit", "auto edit", "polish video", "make it ready",
                "professional edit", "edit everything", "complete the video",
            ],
            mechanism="Chains disk actions + CDP sync + save shortcut + verify",
            action="run_edit_pipeline",
            default_params={"captions": True, "color_preset": "cinematic"},
        ),
        Capability(
            id="pipeline:bootstrap",
            layer="pipeline",
            purpose="Create a new project from media files then run full edit pipeline",
            intents=["new project and edit", "start from clips", "import and edit all"],
            mechanism="create_project_from_media + run_edit_pipeline",
            action="bootstrap_and_edit",
            default_params={},
        ),
    ]


_REGISTRY: list[Capability] | None = None


def all_capabilities() -> list[Capability]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = (
            _disk_capabilities()
            + _shortcut_capabilities()
            + _rpa_capabilities()
            + _pipeline_capabilities()
        )
    return _REGISTRY


def capability_by_id(cap_id: str) -> Capability | None:
    key = (cap_id or "").strip()
    for cap in all_capabilities():
        if cap.id == key:
            return cap
    return None


def _tokenize(text: str) -> set[str]:
    import re

    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1}


def score_capability(cap: Capability, goal: str) -> float:
    """Semantic-ish match: intent tokens vs user goal (no embedding required)."""
    goal_tokens = _tokenize(goal)
    if not goal_tokens:
        return 0.0
    score = 0.0
    blob = " ".join([cap.purpose, cap.mechanism, *cap.intents]).lower()
    cap_tokens = _tokenize(blob)
    overlap = goal_tokens & cap_tokens
    score += len(overlap) * 2.0
    for intent in cap.intents:
        it = intent.lower()
        if it in goal.lower():
            score += 5.0
        it_tokens = _tokenize(it)
        if it_tokens and it_tokens <= goal_tokens:
            score += 3.0
    if cap.layer == "disk":
        score += 0.5  # prefer reliable disk over RPA when tied
    return score


def search_capabilities(goal: str, *, limit: int = 12) -> list[dict[str, Any]]:
    """Return capabilities ranked by relevance to natural-language goal."""
    ranked = sorted(
        all_capabilities(),
        key=lambda c: score_capability(c, goal),
        reverse=True,
    )
    results = []
    for cap in ranked[:limit]:
        results.append({
            **cap.to_brief(),
            "score": round(score_capability(cap, goal), 2),
            "intents_sample": cap.intents[:4],
        })
    return results


def capabilities_for_planner(*, include_ui: list[dict] | None = None) -> list[dict]:
    """Compact catalog for LLM planner."""
    briefs = [c.to_brief() for c in all_capabilities()]
    for ui in include_ui or []:
        briefs.append({
            "id": f"ui:{ui.get('label', '')[:48]}",
            "layer": "ui",
            "purpose": f"Click visible CapCut UI element: {ui.get('label', '')}",
            "mechanism": "Accessibility click on discovered control",
        })
    return briefs
