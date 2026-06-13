import json
import re
import subprocess
from pathlib import Path

SAMPLE_SECONDS = 15
TIMEOUT = 60


def _run(cmd: list[str]) -> tuple[str, str, int]:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    return result.stdout, result.stderr, result.returncode


def probe_file(path: str) -> dict | None:
    file_path = Path(path)
    if not file_path.exists():
        return None

    stdout, stderr, code = _run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", str(file_path),
    ])
    if code != 0:
        return None

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None

    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})

    fps = 0.0
    if video:
        rate = video.get("r_frame_rate", "0/1")
        if "/" in rate:
            num, den = rate.split("/")
            fps = float(num) / float(den) if float(den) else 0.0

    return {
        "path": str(file_path),
        "name": file_path.name,
        "duration": float(fmt.get("duration", 0)),
        "size_mb": round(int(fmt.get("size", 0)) / 1_048_576, 2),
        "video": {
            "width": video.get("width") if video else None,
            "height": video.get("height") if video else None,
            "fps": round(fps, 2),
            "codec": video.get("codec_name") if video else None,
            "nb_frames": int(video.get("nb_frames", 0)) if video and video.get("nb_frames") else None,
        } if video else None,
        "audio": {
            "codec": audio.get("codec_name") if audio else None,
            "sample_rate": audio.get("sample_rate") if audio else None,
            "channels": audio.get("channels") if audio else None,
        } if audio else None,
    }


def analyze_video_quality(path: str) -> dict:
    file_path = Path(path)
    if not file_path.exists():
        return {"error": "File not found"}

    _, stderr, _ = _run([
        "ffmpeg", "-hide_banner", "-i", str(file_path),
        "-t", str(SAMPLE_SECONDS),
        "-vf", "signalstats,metadata=mode=print:file=-",
        "-an", "-f", "null", "-",
    ])

    yavg_values = [float(m) for m in re.findall(r"lavfi\.signalstats\.YAVG=([0-9.]+)", stderr)]
    ydif_values = [float(m) for m in re.findall(r"lavfi\.signalstats\.YDIF=([0-9.]+)", stderr)]
    ymax_values = [float(m) for m in re.findall(r"lavfi\.signalstats\.YMAX=([0-9.]+)", stderr)]
    ymin_values = [float(m) for m in re.findall(r"lavfi\.signalstats\.YMIN=([0-9.]+)", stderr)]

    _, scene_stderr, _ = _run([
        "ffmpeg", "-hide_banner", "-i", str(file_path),
        "-t", str(SAMPLE_SECONDS),
        "-vf", "select='gt(scene,0.25)',showinfo",
        "-an", "-f", "null", "-",
    ])
    scene_count = scene_stderr.count("pts_time:")

    _, edge_stderr, _ = _run([
        "ffmpeg", "-hide_banner", "-i", str(file_path),
        "-t", str(min(5, SAMPLE_SECONDS)),
        "-vf", "format=gray,edgedetect=low=0.1:high=0.3:mode=colormix,signalstats",
        "-an", "-f", "null", "-",
    ])
    edge_yavg = [float(m) for m in re.findall(r"lavfi\.signalstats\.YAVG=([0-9.]+)", edge_stderr)]

    avg_brightness = round(sum(yavg_values) / len(yavg_values), 1) if yavg_values else 0
    avg_motion = round(sum(ydif_values) / len(ydif_values), 1) if ydif_values else 0
    avg_edge = round(sum(edge_yavg) / len(edge_yavg), 1) if edge_yavg else 0
    brightness_range = (
        round(max(ymax_values) - min(ymin_values), 1)
        if ymax_values and ymin_values else 0
    )

    return {
        "brightness": avg_brightness,
        "brightness_range": brightness_range,
        "motion": avg_motion,
        "scene_changes_per_15s": scene_count,
        "edge_score": avg_edge,
        "issues": _video_issues(avg_brightness, avg_motion, scene_count, avg_edge, brightness_range),
    }


def analyze_audio_quality(path: str) -> dict:
    file_path = Path(path)
    if not file_path.exists():
        return {"error": "File not found"}

    _, vol_stderr, _ = _run([
        "ffmpeg", "-hide_banner", "-i", str(file_path),
        "-t", str(SAMPLE_SECONDS),
        "-af", "volumedetect",
        "-vn", "-f", "null", "-",
    ])

    mean_match = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", vol_stderr)
    max_match = re.search(r"max_volume:\s*([-\d.]+)\s*dB", vol_stderr)
    mean_vol = float(mean_match.group(1)) if mean_match else None
    max_vol = float(max_match.group(1)) if max_match else None

    _, silence_stderr, _ = _run([
        "ffmpeg", "-hide_banner", "-i", str(file_path),
        "-t", str(SAMPLE_SECONDS),
        "-af", "silencedetect=noise=-35dB:d=0.4",
        "-vn", "-f", "null", "-",
    ])

    silence_starts = [float(m) for m in re.findall(r"silence_start:\s*([\d.]+)", silence_stderr)]
    silence_ends = [float(m) for m in re.findall(r"silence_end:\s*([\d.]+)", silence_stderr)]
    silence_total = sum(e - s for s, e in zip(silence_starts, silence_ends))

    return {
        "mean_volume_db": mean_vol,
        "max_volume_db": max_vol,
        "silence_seconds": round(silence_total, 2),
        "silence_gaps": len(silence_starts),
        "issues": _audio_issues(mean_vol, max_vol, silence_total),
    }


def _video_issues(brightness, motion, scenes, edge, brightness_range) -> list[str]:
    issues = []
    if brightness < 35:
        issues.append("too_dark")
    elif brightness > 210:
        issues.append("overexposed")
    if brightness_range < 28:
        issues.append("low_contrast")
    if motion > 30:
        issues.append("shaky")
    if scenes > 25:
        issues.append("rapid_cuts")
    if edge < 5:
        issues.append("blurry")
    return issues


def _audio_issues(mean_vol, max_vol, silence_total) -> list[str]:
    issues = []
    if mean_vol is not None:
        if mean_vol < -30:
            issues.append("quiet")
        elif mean_vol > -6:
            issues.append("loud")
    if max_vol is not None and max_vol > -1:
        issues.append("clipping")
    if silence_total > 3:
        issues.append("long_silence")
    return issues
