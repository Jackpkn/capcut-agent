"""Extract JPEG frames from clip files via FFmpeg (local, free)."""

from __future__ import annotations

import subprocess
from pathlib import Path

TIMEOUT = 45


def extract_frame_jpeg(path: str, at_sec: float, *, width: int = 384) -> bytes | None:
    file_path = Path(path)
    if not file_path.exists():
        return None
    at_sec = max(0.0, at_sec)
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-ss", f"{at_sec:.3f}",
                "-i", str(file_path),
                "-vframes", "1",
                "-vf", f"scale={width}:-1",
                "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
            ],
            capture_output=True,
            timeout=TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    return result.stdout


def sample_timestamps(duration_sec: float, count: int = 3) -> list[float]:
    if duration_sec <= 0:
        return [0.0]
    if count <= 1:
        return [min(duration_sec * 0.35, max(0.0, duration_sec - 0.1))]
    step = duration_sec / (count + 1)
    return [round(step * (i + 1), 2) for i in range(count)]
