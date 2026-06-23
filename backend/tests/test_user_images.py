"""Tests for user-attached chat images."""

from agent.user_images import decode_image_bytes, enrich_user_message, normalize_image_b64, normalize_images
import base64


def test_normalize_data_url():
    raw = "data:image/jpeg;base64,abcd"
    assert normalize_image_b64(raw) == "abcd"


def test_normalize_images_rejects_empty():
    assert normalize_images([""]) == []


def test_enrich_without_images():
    text, b64 = enrich_user_message("hello", None)
    assert text == "hello"
    assert b64 == []


def test_decode_tiny_png():
    # 1x1 PNG
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    b64 = base64.b64encode(png).decode("ascii")
    assert decode_image_bytes(b64) == png
    assert len(normalize_images([b64])) == 1
