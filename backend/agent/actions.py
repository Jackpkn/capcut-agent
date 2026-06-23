import json
import logging

from capcut.reader import read_project
from capcut.writer import batch_edits
from capcut.downloader import ensure_asset_cached
from capcut.library import find_asset

logger = logging.getLogger(__name__)
from capcut.writer import (
    add_effect,
    add_music,
    replace_music,
    add_sticker,
    add_text_template,
    add_text_overlay,
    add_visible_text_caption,
    add_transition,
    _find_segment,
    batch_update_texts,
    clear_whisper_captions,
    count_visible_captions,
    move_segment,
    remove_effect,
    reorder_clips,
    set_segment_visibility,
    trim_clip,
    update_clip_speed,
    update_text,
    update_transition,
    update_volume,
    write_project,
)


def _build_text_content(
    plain_text: str,
    existing_content: str | None = None,
    project_path: str | None = None,
) -> str:
    guidelines = []
    if project_path:
        try:
            from capcut.writer import get_session_memory_for_project
            memory = get_session_memory_for_project(project_path)
            if memory.style_brief:
                guidelines.append(memory.style_brief.lower())
            if memory.caption_direction:
                guidelines.append(memory.caption_direction.lower())
            for c in memory.constraints:
                guidelines.append(c.lower())
        except Exception:
            pass

    color = [1.0, 1.0, 1.0]
    for g in guidelines:
        if "yellow" in g:
            color = [1.0, 1.0, 0.0]
            break
        elif "red" in g:
            color = [1.0, 0.0, 0.0]
            break
        elif "green" in g:
            color = [0.0, 1.0, 0.0]
            break
        elif "blue" in g:
            color = [0.0, 0.0, 1.0]
            break
        elif "cyan" in g:
            color = [0.0, 1.0, 1.0]
            break
        elif "magenta" in g:
            color = [1.0, 0.0, 1.0]
            break

    size = 15
    for g in guidelines:
        if "large" in g or "big" in g:
            size = 24
            break
        elif "small" in g or "tiny" in g:
            size = 10
            break

    if existing_content:
        try:
            data = json.loads(existing_content)
            if isinstance(data, dict):
                data["text"] = plain_text
                for style in data.get("styles", []):
                    if "range" in style:
                        style["range"] = [0, len(plain_text)]
                    if color != [1.0, 1.0, 1.0]:
                        style.setdefault("fill", {}).setdefault("content", {}).setdefault("solid", {})["color"] = color
                    if size != 15:
                        style["size"] = size
                return json.dumps(data)
        except (json.JSONDecodeError, TypeError):
            pass

    return json.dumps({
        "styles": [{
            "fill": {
                "content": {
                    "solid": {"color": color},
                    "render_type": "solid",
                }
            },
            "range": [0, len(plain_text)],
            "size": size,
        }],
        "text": plain_text,
    })


def _get_existing_text_content(project_path: str, text_id: str) -> str | None:
    data = read_project(project_path)
    for t in data["materials"]["texts"]:
        if t["id"] == text_id:
            return t.get("content")
    return None


def describe_action(action: str, params: dict) -> str:
    if action == "update_text":
        return f'Change text to "{params.get("new_content", "")}"'
    if action == "batch_update_texts":
        count = len(params.get("updates", []))
        return f"Update {count} text overlay(s)"
    if action == "update_transition":
        parts = []
        if params.get("name"):
            parts.append(f'name to "{params["name"]}"')
        if params.get("duration"):
            secs = params["duration"] / 1_000_000
            parts.append(f"duration to {secs:.2f}s")
        return f"Update transition ({', '.join(parts) or 'properties'})"
    if action == "update_clip_speed":
        speed = params.get("speed")
        idx = params.get("clip_index")
        name = params.get("clip_name")
        seg = str(params.get("segment_id", ""))[:8]
        if idx and name:
            return f'Set clip #{idx} ("{name}") to {speed}x'
        if idx:
            return f"Set clip #{idx} to {speed}x"
        if seg:
            return f"Set clip {seg}… to {speed}x"
        return f"Set clip speed to {speed}x"
    if action == "update_volume":
        return f"Set volume to {int(params.get('volume', 1) * 100)}%"
    if action == "trim_clip":
        return f"Trim clip segment {params.get('segment_id', '')[:8]}..."
    if action == "move_segment":
        start_sec = params.get("start_sec", params.get("start", 0) / 1_000_000)
        return f"Move segment to {start_sec}s on timeline"
    if action == "set_segment_visibility":
        state = "show" if params.get("visible", True) else "hide"
        return f"{state.capitalize()} segment {params.get('segment_id', '')[:8]}..."
    if action == "remove_effect":
        return f"Remove effect {params.get('effect_id', '')[:8]}..."
    if action == "reorder_clips":
        return "Swap positions of two clips"
    if action == "add_music":
        return f'Add music "{params.get("name", params.get("query", ""))}" at {params.get("start_sec", 0)}s'
    if action == "replace_music":
        return (
            f'Replace background music with "{params.get("name", params.get("query", ""))}" '
            f'at {params.get("start_sec", 0)}s'
        )
    if action == "add_transition":
        idx = params.get("clip_index")
        name = params.get("clip_name")
        trans = params.get("query", params.get("name", ""))
        if idx and name:
            return f'Add transition "{trans}" after clip #{idx} ("{name}")'
        if idx:
            return f'Add transition "{trans}" after clip #{idx}'
        seg = str(params.get("segment_id", ""))[:8]
        return f'Add transition "{trans}" after clip {seg}…'
    if action == "add_effect":
        return f'Add effect "{params.get("query", params.get("name", ""))}" at {params.get("start_sec", 0)}s'
    if action == "add_sticker":
        return f'Add sticker "{params.get("query", params.get("name", ""))}" at {params.get("start_sec", 0)}s'
    if action == "add_text_template":
        return f'Add text template "{params.get("query", params.get("name", ""))}" at {params.get("start_sec", 0)}s'
    if action == "generate_image":
        return f'Generate AI image at {params.get("start_sec", 0)}s: "{params.get("prompt", "")[:48]}"'
    if action == "split_clip":
        return f"Split clip {params.get('segment_id', '')[:8]}… at {params.get('at_sec')}s"
    if action == "duck_audio":
        vol = params.get("volume", 0.2)
        return f"Duck background music to {int(vol * 100)}% volume"
    if action == "sync_video_to_beats":
        bpm = params.get("bpm", 120.0)
        return f"Sync video clip boundaries to music cuts ({bpm} BPM)"
    if action == "apply_color_preset":
        return f'Apply color preset "{params.get("preset", "")}"'
    if action == "generate_video_clip":
        return f'Generate AI video at {params.get("start_sec", 0)}s: "{params.get("prompt", "")[:48]}"'
    if action == "generate_captions":
        return f'Generate speech-synced captions ({params.get("style", "travel")} style, Whisper)'
    if action == "draft_operations":
        from capcut.draft_ops import describe_operations
        return describe_operations(params.get("operations", []))
    return f"{action}: {json.dumps(params)}"


def execute_action(action: str, params: dict, project_path: str) -> str:
    def _resolve_music(params: dict) -> dict:
        music = find_asset(params.get("query", params.get("name", "")), "music")
        if not music:
            # Fallback to any music in catalog
            from capcut.catalog import search_catalog

            hits = search_catalog("", "music", limit=1)
            if hits:
                music = hits[0]
                logger.warning(
                    "Music '%s' not found in catalog. Using fallback: '%s' (%s)",
                    params,
                    music.get("name"),
                    music.get("resource_id"),
                )
        if not music:
            raise ValueError(f"Music not found in catalog: {params.get('query', params.get('name'))}")
        return ensure_asset_cached(music, project_path=project_path)

    if action == "update_text":
        existing = _get_existing_text_content(project_path, params["text_id"])
        content = _build_text_content(params["new_content"], existing, project_path)
        update_text(project_path, params["text_id"], content)
        return f'Updated text to "{params["new_content"]}"'

    if action == "batch_update_texts":
        updates = []
        for item in params["updates"]:
            existing = _get_existing_text_content(project_path, item["text_id"])
            updates.append({
                "text_id": item["text_id"],
                "content": _build_text_content(item["new_content"], existing, project_path),
            })
        batch_update_texts(project_path, updates)
        return f"Updated {len(updates)} text overlay(s)"

    if action == "update_transition":
        update_transition(
            project_path,
            params["transition_id"],
            duration=params.get("duration"),
            name=params.get("name"),
        )
        return "Updated transition"

    if action == "update_clip_speed":
        target = float(params["speed"])
        data = read_project(project_path)
        seg = _find_segment(data, params["segment_id"])
        if seg and abs(float(seg.get("speed") or 1.0) - target) < 0.01:
            return f"Clip already at {target}x — no change needed"
        update_clip_speed(project_path, params["segment_id"], target)
        return f"Set clip speed to {target}x"

    if action == "update_volume":
        update_volume(project_path, params["segment_id"], params["volume"])
        return f"Set volume to {params['volume']}"

    if action == "trim_clip":
        trim_clip(
            project_path,
            params["segment_id"],
            start=params.get("start"),
            duration=params.get("duration"),
        )
        return "Trimmed clip"

    if action == "move_segment":
        start = params.get("start")
        if start is None and "start_sec" in params:
            start = int(params["start_sec"] * 1_000_000)
        duration = params.get("duration")
        if duration is None and "duration_sec" in params:
            duration = int(params["duration_sec"] * 1_000_000)
        move_segment(project_path, params["segment_id"], start, duration)
        return f"Moved segment to {params.get('start_sec', start / 1_000_000)}s"

    if action == "set_segment_visibility":
        set_segment_visibility(project_path, params["segment_id"], params["visible"])
        state = "visible" if params["visible"] else "hidden"
        return f"Segment is now {state}"

    if action == "remove_effect":
        remove_effect(project_path, params["effect_id"])
        return "Removed effect"

    if action == "reorder_clips":
        reorder_clips(project_path, params["segment_id_a"], params["segment_id_b"])
        return "Swapped clip positions"

    if action == "add_music":
        music = _resolve_music(params)
        result = add_music(
            project_path,
            music_path=music["path"],
            name=music["name"],
            duration_us=music.get("duration_us") or 30_000_000,
            start_sec=params.get("start_sec", 0),
            clip_duration_sec=params.get("clip_duration_sec"),
            volume=params.get("volume", 0.8),
        )
        return f'Added music "{result["name"]}" (resource_id {music.get("resource_id")})'

    if action == "replace_music":
        music = _resolve_music(params)
        result = replace_music(
            project_path,
            music_path=music["path"],
            name=music["name"],
            duration_us=music.get("duration_us") or 30_000_000,
            start_sec=params.get("start_sec", 0),
            clip_duration_sec=params.get("clip_duration_sec"),
            volume=params.get("volume", 0.8),
        )
        removed = result.get("muted_tracks", 0)
        extra = f" (removed {removed} old track(s))" if removed else ""
        return f'Replaced music with "{result["name"]}"{extra}'

    if action == "add_transition":
        from capcut.reader import get_project_summary
        from capcut.segment_resolve import resolve_transition_target, enrich_segment_params

        video_clips = get_project_summary(project_path).get("video_clips", [])
        params = dict(params)
        user_hint = str(params.pop("user_message", "") or "")
        resolved = resolve_transition_target(params, video_clips, user_message=user_hint)
        if not resolved:
            raise ValueError("Could not resolve which clip should get the transition")
        params["segment_id"] = resolved
        params = enrich_segment_params(params, video_clips)
        result = add_transition(
            project_path,
            segment_id=params["segment_id"],
            resource_id=params.get("resource_id"),
            name=params.get("name"),
            query=params.get("query"),
            duration_us=int(params["duration_sec"] * 1_000_000) if params.get("duration_sec") else None,
        )
        clip_label = (
            f'clip #{params["clip_index"]} ("{params.get("clip_name", "")}")'
            if params.get("clip_index")
            else f'clip {params["segment_id"][:8]}…'
        )
        if result.get("unchanged"):
            return f'Transition "{result["name"]}" is on {clip_label}'
        if result.get("updated"):
            return f'Updated transition "{result["name"]}" duration on {clip_label}'
        if result.get("replaced"):
            old = result.get("replaced_name") or "previous transition"
            return f'Replaced "{old}" with "{result["name"]}" on {clip_label}'
        return f'Added transition "{result["name"]}" after {clip_label}'

    if action == "add_effect":
        result = add_effect(
            project_path,
            resource_id=params.get("resource_id"),
            name=params.get("name"),
            query=params.get("query"),
            start_sec=params.get("start_sec", 0),
            duration_sec=params.get("duration_sec"),
            bind_segment_id=params.get("bind_segment_id"),
        )
        return f'Added effect "{result["name"]}" (resource_id {params.get("resource_id", "from catalog")})'

    if action == "add_sticker":
        result = add_sticker(
            project_path,
            resource_id=params.get("resource_id"),
            name=params.get("name"),
            query=params.get("query"),
            start_sec=params.get("start_sec", 0),
            duration_sec=params.get("duration_sec", 3.0),
        )
        return f'Added sticker "{result["name"]}"'

    if action == "add_text_template":
        result = add_text_template(
            project_path,
            resource_id=params.get("resource_id"),
            name=params.get("name"),
            query=params.get("query"),
            start_sec=params.get("start_sec", 0),
            duration_sec=params.get("duration_sec", 3.0),
            text_content=params.get("text_content"),
        )
        return f'Added text template "{result["name"]}"'

    if action == "generate_captions":
        from analysis.whisper_captions import (
            segments_for_timeline,
            transcribe_audio_file,
            whisper_available,
        )
        from capcut.reader import list_video_segments_for_captions

        if not whisper_available():
            from analysis.whisper_captions import WHISPER_INSTALL_HINT
            raise RuntimeError(
                f"Install Whisper for captions: {WHISPER_INSTALL_HINT} — then restart uvicorn and Approve again"
            )
        max_words = params.get("max_words_per_line", 5)
        data = read_project(project_path)
        cleared = clear_whisper_captions(data)
        if cleared:
            write_project(project_path, data)
        video_segments = list_video_segments_for_captions(data)
        if not params.get("all_tracks", False) and video_segments:
            by_track: dict[int, list[dict]] = {}
            for clip in video_segments:
                by_track.setdefault(clip["track_index"], []).append(clip)
            if len(by_track) > 1:
                primary_track = max(
                    by_track.keys(),
                    key=lambda ti: sum(c["duration_sec"] for c in by_track[ti]),
                )
                video_segments = by_track[primary_track]
        import time

        added = 0
        errors: list[str] = []
        use_visible = bool(params.get("visible_captions"))
        caption_group_id = f"en-US_{int(time.time() * 1000)}"
        for clip in video_segments:
            try:
                segments = transcribe_audio_file(clip["path"], model="base")
            except RuntimeError as e:
                errors.append(str(e))
                continue
            timed = segments_for_timeline(segments, clip, max_words)
            for seg in timed:
                try:
                    mapped_words = []
                    if seg.get("words"):
                        clip_at = float(clip["at_sec"])
                        source_off = float(clip.get("source_start_sec", 0))
                        speed = float(clip.get("speed") or 1.0)
                        for w in seg["words"]:
                            mapped_words.append({
                                "word": w["word"],
                                "start": clip_at + (w["start"] - source_off) / speed,
                                "end": clip_at + (w["end"] - source_off) / speed,
                            })
                    if use_visible:
                        add_visible_text_caption(
                            project_path,
                            text_content=seg["text"],
                            start_sec=seg["start_sec"],
                            duration_sec=seg["duration_sec"],
                            font_size=28.0,
                        )
                    else:
                        add_text_overlay(
                            project_path,
                            text_content=seg["text"],
                            start_sec=seg["start_sec"],
                            duration_sec=seg["duration_sec"],
                            group_id=caption_group_id,
                            render_index=14004 + added,
                            word_entries=mapped_words or None,
                            timeline_start_sec=seg["start_sec"],
                        )
                    added += 1
                except ValueError as e:
                    errors.append(str(e))
                    break
        if added == 0 and errors:
            raise RuntimeError(errors[0])

        data = read_project(project_path)
        on_disk = count_visible_captions(data)
        if added > 0 and on_disk < added:
            raise RuntimeError(
                f"Only {on_disk}/{added} caption(s) saved to disk. "
                "Click Home in CapCut (top-left), wait 3 seconds, then Approve again."
            )

        suffix = f" ({len(errors)} clip(s) skipped)" if errors else ""
        replace_note = f", replaced {cleared} old overlay(s)" if cleared else ""
        style_note = " (large on-screen text)" if use_visible else ""
        return (
            f"Generated {added} speech-synced caption line(s) via Whisper{style_note}"
            f"{replace_note}{suffix}"
        )

    if action == "generate_image":
        from capcut.image_gen import generate_image_file
        from capcut.writer import add_generated_image

        prompt = params.get("prompt") or params.get("query") or ""
        if not prompt:
            raise ValueError("generate_image requires a prompt")
        image_path = generate_image_file(prompt, project_path)
        result = add_generated_image(
            project_path,
            image_path,
            start_sec=float(params.get("start_sec", 0)),
            duration_sec=float(params.get("duration_sec", 3.0)),
        )
        return (
            f'Generated image "{prompt[:48]}" and placed at {result["at_sec"]}s '
            f'({result["name"]})'
        )

    if action == "split_clip":
        from capcut.writer import split_clip

        msg = split_clip(
            project_path,
            params["segment_id"],
            float(params["at_sec"]),
        )
        return msg

    if action == "duck_audio":
        from capcut.writer import duck_audio

        result = duck_audio(
            project_path,
            music_segment_id=params.get("music_segment_id") or params.get("segment_id"),
            volume=float(params.get("volume", 0.2)),
        )
        return f'Ducked music segment to {int(result["volume"] * 100)}% volume'

    if action == "sync_video_to_beats":
        from capcut.writer import sync_video_to_beats

        result = sync_video_to_beats(
            project_path,
            bpm=float(params.get("bpm", 120.0)),
            beat_interval=params.get("beat_interval"),
        )
        return f"Aligned {result['aligned_clips']} video clips to beats at {result['bpm']} BPM"

    if action == "apply_color_preset":
        from capcut.writer import apply_color_preset

        result = apply_color_preset(
            project_path,
            preset=params["preset"],
            start_sec=float(params.get("start_sec", 0)),
            duration_sec=params.get("duration_sec"),
            bind_segment_id=params.get("bind_segment_id"),
        )
        return f'Applied color preset "{params["preset"]}" — effect "{result["name"]}"'

    if action == "generate_video_clip":
        raise RuntimeError(
            "AI video clip generation is not configured yet. "
            "Set VIDEO_GEN_API_KEY on the server — then approve again."
        )

    if action == "draft_operations":
        from capcut.draft_ops import apply_draft_operations

        results = apply_draft_operations(project_path, params.get("operations", []))
        return "; ".join(results) if results else "No operations applied"

    raise ValueError(f"Unknown action: {action}")


def execute_actions(actions: list[dict], project_path: str) -> list[str]:
    results = []
    with batch_edits(project_path):
        for item in actions:
            action = item["action"]
            params = item.get("params", {})
            try:
                results.append(execute_action(action, params, project_path))
            except Exception as e:
                logger.error(f"Failed to execute action {action}: {e}", exc_info=True)
                results.append(f"Failed to apply: {e}")
    return results


def iter_execute_sse(actions: list[dict], project_path: str):
    """Stream each apply step as SSE."""
    import queue
    import threading

    from agent.brain import format_execute_reply
    from agent.streaming import sse_line

    event_q: queue.Queue = queue.Queue()
    result_box: dict = {}

    def emit(event: dict) -> None:
        event_q.put(event)

    def run() -> None:
        try:
            results = []
            emit({"type": "agent_start", "message": f"Applying {len(actions)} change(s) to project…"})
            with batch_edits(project_path):
                for i, item in enumerate(actions, start=1):
                    action = item["action"]
                    params = item.get("params", {})
                    desc = item.get("description") or action
                    emit({
                        "type": "step",
                        "id": f"apply_{i}",
                        "status": "running",
                        "label": f"[{i}/{len(actions)}] {desc}",
                    })
                    try:
                        msg = execute_action(action, params, project_path)
                        results.append(msg)
                        emit({
                            "type": "step",
                            "id": f"apply_{i}",
                            "status": "done",
                            "label": f"[{i}/{len(actions)}] {desc}",
                            "detail": msg,
                        })
                    except Exception as e:
                        logger.error(f"Failed to execute action {action}: {e}", exc_info=True)
                        msg = f"Failed to apply: {e}"
                        results.append(msg)
                        emit({
                            "type": "step",
                            "id": f"apply_{i}",
                            "status": "error",
                            "label": f"[{i}/{len(actions)}] {desc} (Failed)",
                            "detail": str(e),
                        })
            result_box["results"] = results
        except Exception as e:
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
        time.sleep(0.04)

    if result_box.get("error"):
        yield sse_line({"type": "error", "message": result_box["error"]})
        return

    results = result_box["results"]
    yield sse_line({
        "type": "done",
        "reply": format_execute_reply(results),
        "results": results,
    })
