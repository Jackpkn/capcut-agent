"""Optional local Whisper transcription for caption generation."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


WHISPER_INSTALL_HINT = (
    "cd backend && uv sync --extra captions"
)

MIN_CAPTION_SEC = 0.08
END_PAD_SEC = 0.05


def whisper_available() -> bool:
    if shutil.which("whisper"):
        return True
    try:
        import whisper  # noqa: F401
        return True
    except ImportError:
        return False


def transcribe_audio_file(audio_path: str, model: str = "base") -> list[dict]:
    """
    Run openai-whisper CLI on an audio/video file.
    Returns segments: [{start, end, text, words?}, ...]
    """
    if not whisper_available():
        raise RuntimeError(
            f"Whisper not installed. Run: {WHISPER_INSTALL_HINT}"
        )

    from analysis.whisper_cache import get_cached_transcription, set_cached_transcription

    cached = get_cached_transcription(audio_path, model)
    if cached is not None:
        return cached

    out_dir = tempfile.mkdtemp(prefix="capcut-whisper-")
    try:
        subprocess.run(
            [
                "whisper", audio_path,
                "--model", model,
                "--output_format", "json",
                "--output_dir", out_dir,
                "--language", "en",
                "--word_timestamps", "True",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
        json_files = list(Path(out_dir).glob("*.json"))
        if not json_files:
            return []
        data = json.loads(json_files[0].read_text())
        segments = []
        for seg in data.get("segments", []):
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            words = [
                {
                    "word": (w.get("word") or "").strip(),
                    "start": float(w.get("start", 0)),
                    "end": float(w.get("end", 0)),
                }
                for w in seg.get("words", [])
                if (w.get("word") or "").strip()
            ]
            segments.append({
                "start": float(seg.get("start", 0)),
                "end": float(seg.get("end", 0)),
                "text": text,
                "words": words,
            })
        if segments:
            set_cached_transcription(audio_path, model, segments)
        return segments
    except subprocess.CalledProcessError as e:
        logger.warning("Whisper failed: %s", e.stderr)
        raise RuntimeError(f"Whisper transcription failed: {e.stderr[:200]}") from e
    finally:
        for f in Path(out_dir).glob("*"):
            try:
                f.unlink()
            except OSError:
                pass
        try:
            Path(out_dir).rmdir()
        except OSError:
            pass


def _join_words(words: list[dict]) -> str:
    return " ".join(w["word"] for w in words if w.get("word")).strip()


def _chunk_words(words: list[dict], max_words: int) -> list[dict]:
    chunks = []
    buf: list[dict] = []
    for word in words:
        buf.append(word)
        if len(buf) >= max_words:
            chunks.append({
                "text": _join_words(buf),
                "start": buf[0]["start"],
                "end": buf[-1]["end"],
                "words": list(buf),
            })
            buf = []
    if buf:
        chunks.append({
            "text": _join_words(buf),
            "start": buf[0]["start"],
            "end": buf[-1]["end"],
            "words": list(buf),
        })
    return chunks


def _speech_chunks_from_segment(seg: dict, max_words: int) -> list[dict]:
    words = seg.get("words") or []
    if words:
        return _chunk_words(words, max_words)
    text = seg.get("text", "").strip()
    if not text:
        return []
    return [{
        "text": text,
        "start": seg["start"],
        "end": seg["end"],
        "words": [],
    }]


def map_source_to_timeline(
    source_start: float,
    source_end: float,
    clip: dict,
) -> tuple[float, float] | None:
    """Map a speech interval in source media time to timeline seconds."""
    timeline_at = float(clip.get("at_sec", 0))
    source_offset = float(clip.get("source_start_sec", 0))
    speed = float(clip.get("speed") or 1.0)
    if speed <= 0:
        speed = 1.0

    source_limit = source_offset + float(clip.get("source_duration_sec") or 0)
    if source_limit > 0:
        if source_end <= source_offset or source_start >= source_limit:
            return None
        source_start = max(source_start, source_offset)
        source_end = min(source_end, source_limit)

    timeline_start = timeline_at + (source_start - source_offset) / speed
    timeline_end = timeline_at + (source_end - source_offset) / speed
    duration = timeline_end - timeline_start
    if duration < MIN_CAPTION_SEC:
        return None
    return round(timeline_start, 3), round(duration + END_PAD_SEC, 3)


def segments_for_timeline(
    segments: list[dict],
    clip: dict,
    max_words: int = 5,
) -> list[dict]:
    """
    Build timeline-synced captions from Whisper output.
    Captions appear only while speech is detected (gaps stay empty).
    """
    out: list[dict] = []
    for seg in segments:
        for chunk in _speech_chunks_from_segment(seg, max_words):
            text = chunk["text"]
            if not text:
                continue
            mapped = map_source_to_timeline(chunk["start"], chunk["end"], clip)
            if not mapped:
                continue
            start_sec, duration_sec = mapped
            out.append({
                "text": text,
                "start_sec": start_sec,
                "duration_sec": duration_sec,
                "source_start_sec": chunk["start"],
                "source_end_sec": chunk["end"],
                "words": chunk.get("words") or [],
            })

    out.sort(key=lambda c: c["start_sec"])
    return out
