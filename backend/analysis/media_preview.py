"""Thumbnails and waveform peaks for analysis UI."""

from __future__ import annotations

import base64
import struct
import subprocess
from pathlib import Path

PREVIEW_SECONDS = 12
WAVEFORM_POINTS = 72


def _run_bytes(cmd: list[str], timeout: int = 45) -> bytes | None:
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if result.returncode != 0:
            return None
        return result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return None


def clip_thumbnail_base64(path: str, at_sec: float = 1.0) -> str | None:
    file_path = Path(path)
    if not file_path.exists():
        return None
    data = _run_bytes([
        "ffmpeg", "-hide_banner", "-ss", str(at_sec),
        "-i", str(file_path),
        "-vframes", "1",
        "-vf", "scale=128:-1",
        "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ])
    if not data:
        return None
    return f"data:image/jpeg;base64,{base64.b64encode(data).decode('ascii')}"


def audio_waveform_peaks(path: str, points: int = WAVEFORM_POINTS) -> list[float]:
    file_path = Path(path)
    if not file_path.exists():
        return [0.0] * points

    raw = _run_bytes([
        "ffmpeg", "-hide_banner", "-i", str(file_path),
        "-t", str(PREVIEW_SECONDS),
        "-ac", "1", "-ar", "12000",
        "-f", "f32le", "pipe:1",
    ])
    if not raw or len(raw) < 16:
        return [0.05] * points

    count = len(raw) // 4
    samples = struct.unpack(f"<{count}f", raw[: count * 4])
    bucket = max(1, len(samples) // points)
    peaks: list[float] = []
    for i in range(points):
        start = i * bucket
        chunk = samples[start : start + bucket]
        if not chunk:
            peaks.append(0.0)
            continue
        peaks.append(max(abs(v) for v in chunk))

    max_peak = max(peaks) or 1.0
    return [round(min(1.0, p / max_peak), 3) for p in peaks]


def merge_waveform_peaks(series: list[list[float]]) -> list[float]:
    if not series:
        return [0.05] * WAVEFORM_POINTS
    length = max(len(s) for s in series)
    merged = []
    for i in range(length):
        vals = [s[i] for s in series if i < len(s)]
        merged.append(round(sum(vals) / len(vals), 3) if vals else 0.0)
    return merged
