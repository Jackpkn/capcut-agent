"""Disk cache for Whisper transcriptions — keyed by file path, mtime, size, and model."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".capcut-agent" / "whisper_cache"


def _cache_key(audio_path: str, model: str) -> str:
    p = Path(audio_path).resolve()
    stat = p.stat()
    raw = f"{p}|{stat.st_mtime_ns}|{stat.st_size}|{model}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_path(audio_path: str, model: str) -> Path:
    return CACHE_DIR / f"{_cache_key(audio_path, model)}.json"


def get_cached_transcription(audio_path: str, model: str = "base") -> list[dict] | None:
    path = _cache_path(audio_path, model)
    if not path.exists():
        return None
    try:
        p = Path(audio_path).resolve()
        stat = p.stat()
        data = json.loads(path.read_text())
        if data.get("mtime_ns") != stat.st_mtime_ns or data.get("size") != stat.st_size:
            return None
        segments = data.get("segments")
        if isinstance(segments, list):
            logger.info("Whisper cache hit: %s (%d segments)", p.name, len(segments))
            return segments
    except (OSError, json.JSONDecodeError, KeyError) as e:
        logger.debug("Whisper cache read failed: %s", e)
    return None


def set_cached_transcription(
    audio_path: str,
    model: str,
    segments: list[dict],
) -> None:
    try:
        p = Path(audio_path).resolve()
        stat = p.stat()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "path": str(p),
            "model": model,
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
            "segments": segments,
        }
        _cache_path(audio_path, model).write_text(json.dumps(payload, indent=0))
        logger.info("Whisper cache saved: %s (%d segments)", p.name, len(segments))
    except OSError as e:
        logger.warning("Whisper cache write failed: %s", e)


def cache_stats() -> dict:
    if not CACHE_DIR.exists():
        return {"entries": 0, "bytes": 0}
    files = list(CACHE_DIR.glob("*.json"))
    return {
        "entries": len(files),
        "bytes": sum(f.stat().st_size for f in files),
        "dir": str(CACHE_DIR),
    }
