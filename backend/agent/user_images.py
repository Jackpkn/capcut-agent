"""User-attached reference images for chat (Gemma / Gemini vision)."""

from __future__ import annotations

import base64
import binascii
import logging
import re

logger = logging.getLogger(__name__)

MAX_IMAGES = 2
MAX_IMAGE_BYTES = 3_000_000

_DATA_URL_RE = re.compile(r"^data:image/[\w+.-]+;base64,", re.I)


def normalize_image_b64(raw: str) -> str:
    s = (raw or "").strip()
    s = _DATA_URL_RE.sub("", s)
    s = re.sub(r"\s+", "", s)
    return s


def decode_image_bytes(raw: str) -> bytes | None:
    b64 = normalize_image_b64(raw)
    if not b64:
        return None
    try:
        data = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not data or len(data) > MAX_IMAGE_BYTES:
        return None
    return data


def normalize_images(images: list[str] | None) -> list[str]:
    """Return validated base64 strings (no data-URL prefix)."""
    if not images:
        return []
    out: list[str] = []
    for raw in images[:MAX_IMAGES]:
        data = decode_image_bytes(raw)
        if data:
            out.append(base64.b64encode(data).decode("ascii"))
    return out


def describe_attached_images(images_b64: list[str]) -> str:
    """Vision summary for all providers (Ollama also gets native pixels)."""
    if not images_b64:
        return ""
    from analysis.vision_local import describe_reference_image

    blocks: list[str] = []
    for i, b64 in enumerate(images_b64, start=1):
        data = base64.b64decode(b64)
        info = describe_reference_image(data)
        if not info:
            blocks.append(f"**Reference image {i}:** (could not analyze)")
            continue
        summary = info.get("summary") or info.get("content") or ""
        style = info.get("style") or info.get("emotion") or ""
        use = info.get("suggested_use") or ""
        lines = [f"**Reference image {i}:** {summary}"]
        if style:
            lines.append(f"- Style/mood: {style}")
        if info.get("subjects"):
            subs = info["subjects"]
            if isinstance(subs, list):
                lines.append(f"- Subjects: {', '.join(str(s) for s in subs[:6])}")
        if use:
            lines.append(f"- Suggested use: {use}")
        blocks.append("\n".join(lines))
    if not blocks:
        return ""
    return (
        "## User-attached reference image(s)\n"
        + "\n\n".join(blocks)
        + "\n\nUse these as visual guidance for edits (style, composition, thumbnail, overlay placement)."
    )


def enrich_user_message(user_message: str, images: list[str] | None) -> tuple[str, list[str]]:
    """Append vision text; return (message, ollama-ready base64 list)."""
    b64_list = normalize_images(images)
    if not b64_list:
        return user_message, []
    vision_block = describe_attached_images(b64_list)
    text = (user_message or "").strip()
    if vision_block:
        text = f"{text}\n\n{vision_block}" if text else vision_block
    elif not text:
        text = "User attached reference image(s) — use them to guide the edit."
    return text, b64_list
