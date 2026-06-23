"""Clip vision — Gemini API or local Ollama multimodal (no CapCut Pro)."""

from __future__ import annotations

import base64
import json
import logging
import os

logger = logging.getLogger(__name__)

VISION_INSTRUCTIONS = """You analyze ONE video frame from a clip in an edit timeline.
Return JSON only with these fields:
- content: short description of what is happening (max 20 words)
- emotion: mood/vibe (e.g. "happy, energetic" or "calm, reflective")
- scene_type: setting (e.g. "outdoor beach, daytime")
- objects: array of 3-6 visible objects/subjects
- has_face: boolean
- hook_strength: 0.0-1.0 how scroll-stopping / exciting this moment feels
- quality_note: one of "sharp", "soft", "dark", "overexposed", "good"
Do not invent speech or text not visible in the frame."""


def vision_available() -> bool:
    if os.environ.get("GEMINI_API_KEY"):
        return True
    if os.environ.get("OLLAMA_VISION", "true").lower() in ("0", "false", "no"):
        return False
    from agent.runtime.ollama_provider import ollama_available

    return ollama_available()


def describe_frame(jpeg_bytes: bytes, *, clip_name: str = "", duration_sec: float = 0) -> dict | None:
    if not jpeg_bytes:
        return None
    if os.environ.get("GEMINI_API_KEY"):
        return _describe_frame_gemini(jpeg_bytes, clip_name=clip_name, duration_sec=duration_sec)
    if vision_available():
        return _describe_frame_ollama(jpeg_bytes, clip_name=clip_name, duration_sec=duration_sec)
    return None


REFERENCE_IMAGE_INSTRUCTIONS = """You analyze a reference image the user attached for video editing in CapCut.
Return JSON only:
- summary: short description (max 25 words)
- style: color grading, mood, aesthetic (e.g. "warm sunset, cinematic")
- subjects: array of 3-6 visible subjects or elements
- suggested_use: one sentence — how to use this as reference (color match, thumbnail style, overlay, etc.)
Do not invent text not visible in the image."""


def describe_reference_image(jpeg_bytes: bytes) -> dict | None:
    """Analyze a user-attached reference still (not a timeline frame)."""
    if not jpeg_bytes:
        return None
    if os.environ.get("GEMINI_API_KEY"):
        return _describe_reference_gemini(jpeg_bytes)
    if vision_available():
        return _describe_reference_ollama(jpeg_bytes)
    return None


def _parse_vision_json(text: str) -> dict | None:
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _describe_frame_gemini(jpeg_bytes: bytes, *, clip_name: str = "", duration_sec: float = 0) -> dict | None:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None

    model = os.environ.get("GEMINI_VISION_MODEL", os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
    client = genai.Client(api_key=key)
    prompt = (
        f"Clip name: {clip_name or 'untitled'}\n"
        f"Clip duration: {duration_sec:.1f}s\n"
        "Describe this representative frame for an AI video editor."
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(text=prompt),
                        types.Part(
                            inline_data=types.Blob(mime_type="image/jpeg", data=jpeg_bytes),
                        ),
                    ],
                )
            ],
            config=types.GenerateContentConfig(
                system_instruction=VISION_INSTRUCTIONS,
                temperature=0.2,
                max_output_tokens=512,
                response_mime_type="application/json",
            ),
        )
    except Exception as exc:
        logger.warning("Gemini vision failed: %s", exc)
        return None

    return _parse_vision_json(getattr(response, "text", None) or "")


def _describe_frame_ollama(jpeg_bytes: bytes, *, clip_name: str = "", duration_sec: float = 0) -> dict | None:
    """Ollama multimodal (gemma4, llava, etc.) — local, free."""
    from agent.runtime.ollama_provider import _get_ollama_client, resolve_ollama_model

    model = resolve_ollama_model()
    b64 = base64.b64encode(jpeg_bytes).decode("ascii")
    prompt = (
        f"{VISION_INSTRUCTIONS}\n\n"
        f"Clip name: {clip_name or 'untitled'}\n"
        f"Clip duration: {duration_sec:.1f}s\n"
        "Return JSON only."
    )

    try:
        response = _get_ollama_client().chat(
            model=model,
            messages=[{
                "role": "user",
                "content": prompt,
                "images": [b64],
            }],
            options={"temperature": 0.2, "num_predict": 512},
        )
    except Exception as exc:
        logger.warning("Ollama vision failed (%s): %s", model, exc)
        return None

    content = getattr(response.message, "content", None) or ""
    return _parse_vision_json(content)


def _describe_reference_gemini(jpeg_bytes: bytes) -> dict | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)
        model = os.environ.get("GEMINI_VISION_MODEL", os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(text=REFERENCE_IMAGE_INSTRUCTIONS),
                        types.Part(
                            inline_data=types.Blob(mime_type="image/jpeg", data=jpeg_bytes),
                        ),
                    ],
                )
            ],
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=512,
                response_mime_type="application/json",
            ),
        )
    except Exception as exc:
        logger.warning("Gemini reference image failed: %s", exc)
        return None
    return _parse_vision_json(getattr(response, "text", None) or "")


def _describe_reference_ollama(jpeg_bytes: bytes) -> dict | None:
    from agent.runtime.ollama_provider import _get_ollama_client, resolve_ollama_model

    model = resolve_ollama_model()
    b64 = base64.b64encode(jpeg_bytes).decode("ascii")
    try:
        response = _get_ollama_client().chat(
            model=model,
            messages=[{
                "role": "user",
                "content": f"{REFERENCE_IMAGE_INSTRUCTIONS}\n\nReturn JSON only.",
                "images": [b64],
            }],
            options={"temperature": 0.2, "num_predict": 512},
        )
    except Exception as exc:
        logger.warning("Ollama reference image failed (%s): %s", model, exc)
        return None
    content = getattr(response.message, "content", None) or ""
    return _parse_vision_json(content)
