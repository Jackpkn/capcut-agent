"""Phase F — generate images via OpenAI or Gemini."""

from __future__ import annotations

import logging
import os
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


def _download_url(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest)
    return dest


def _save_bytes(data: bytes, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def generate_image_file(prompt: str, project_path: str) -> str:
    """
    Generate an image and save under the project folder.
    Returns absolute path to the PNG file.
    """
    out_dir = Path(project_path) / "generated_images"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time() * 1000)
    dest = out_dir / f"ai_{stamp}.png"

    provider = (os.environ.get("IMAGE_GEN_PROVIDER") or "openai").lower().strip()
    if provider == "gemini":
        return str(_generate_gemini(prompt, dest))

    api_key = os.environ.get("IMAGE_GEN_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Set IMAGE_GEN_API_KEY or OPENAI_API_KEY for AI image generation."
        )
    return str(_generate_openai(prompt, dest, api_key))


def _generate_openai(prompt: str, dest: Path, api_key: str) -> Path:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    model = os.environ.get("IMAGE_GEN_MODEL", "dall-e-3")
    size = os.environ.get("IMAGE_GEN_SIZE", "1024x1024")
    response = client.images.generate(
        model=model,
        prompt=prompt,
        n=1,
        size=size,
    )
    item = response.data[0]
    if getattr(item, "b64_json", None):
        import base64

        return _save_bytes(base64.b64decode(item.b64_json), dest)
    if getattr(item, "url", None):
        return _download_url(item.url, dest)
    raise RuntimeError("OpenAI image API returned no url or b64_json")


def _generate_gemini(prompt: str, dest: Path) -> Path:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("IMAGE_GEN_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY or IMAGE_GEN_API_KEY for Gemini images.")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    model = os.environ.get("IMAGE_GEN_MODEL", "imagen-3.0-generate-002")
    response = client.models.generate_images(
        model=model,
        prompt=prompt,
        config=types.GenerateImagesConfig(number_of_images=1),
    )
    images = getattr(response, "generated_images", None) or []
    if not images:
        raise RuntimeError("Gemini image API returned no images")
    image = images[0]
    raw = getattr(image, "image", None)
    if raw is None and hasattr(image, "image_bytes"):
        raw = image.image_bytes
    if isinstance(raw, bytes):
        return _save_bytes(raw, dest)
    if hasattr(raw, "save"):
        raw.save(dest)
        return dest
    raise RuntimeError("Could not read Gemini image bytes")
