"""Tests for media ingest (import clips, create project)."""

import copy
import json
from pathlib import Path

import pytest

from capcut import ingest


def _minimal_draft() -> dict:
    return {
        "id": "DRAFT-1",
        "name": "test",
        "duration": 0,
        "tracks": [
            {"id": "vt1", "type": "video", "segments": [], "attribute": 0},
            {"id": "at1", "type": "audio", "segments": [], "attribute": 0},
        ],
        "materials": {
            "videos": [
                {
                    "id": "mat_tpl",
                    "type": "video",
                    "path": "/old/clip.mp4",
                    "width": 1080,
                    "height": 1920,
                    "duration": 5_000_000,
                }
            ],
            "audios": [],
            "video_effects": [],
        },
    }


def test_probe_media_file_photo(tmp_path, monkeypatch):
    img = tmp_path / "shot.jpg"
    img.write_bytes(b"fake-jpeg")

    def fake_run(cmd, **kwargs):
        class R:
            returncode = 0
            stdout = json.dumps({"format": {"duration": "2.5"}, "streams": []})

        return R()

    monkeypatch.setattr(ingest.subprocess, "run", fake_run)
    probe = ingest.probe_media_file(img)
    assert probe["media_type"] == "photo"
    assert probe["duration_us"] == 2_500_000


def test_clear_editable_timeline():
    data = _minimal_draft()
    data["tracks"][0]["segments"] = [{"id": "s1"}]
    data["materials"]["videos"].append({"id": "x"})
    ingest.clear_editable_timeline(data)
    assert data["tracks"][0]["segments"] == []
    assert data["materials"]["videos"] == []
    assert data["duration"] == 0


def test_import_clips_appends_segments(tmp_path, monkeypatch):
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"video")

    stored = copy.deepcopy(_minimal_draft())

    def mock_read(path):
        return copy.deepcopy(stored)

    def mock_write(path, data):
        stored.clear()
        stored.update(data)

    monkeypatch.setattr(ingest, "read_project", mock_read)
    monkeypatch.setattr(ingest, "write_project", mock_write)
    monkeypatch.setattr(
        ingest,
        "probe_media_file",
        lambda p: {
            "path": str(p),
            "name": Path(p).name,
            "media_type": "video",
            "duration_us": 4_000_000,
            "width": 1080,
            "height": 1920,
        },
    )

    result = ingest.import_clips("/fake/project", [str(clip)])
    assert result["imported_count"] == 1
    assert len(stored["tracks"][0]["segments"]) == 1
    assert stored["materials"]["videos"][-1]["path"] == str(clip.resolve())


def test_create_project_from_media(tmp_path, monkeypatch):
    clip = tmp_path / "b.mp4"
    clip.write_bytes(b"video")
    template = tmp_path / "template"
    template.mkdir()
    (template / "draft_info.json").write_text(json.dumps(_minimal_draft()))
    (template / "draft_meta_info.json").write_text(
        json.dumps({"draft_id": "OLD", "draft_name": "template"})
    )
    dest_root = tmp_path / "projects"
    dest_root.mkdir()

    monkeypatch.setattr(ingest, "PROJECTS_PATH", dest_root)
    monkeypatch.setattr(
        ingest,
        "_pick_template_project",
        lambda: template,
    )
    monkeypatch.setattr(
        ingest,
        "probe_media_file",
        lambda p: {
            "path": str(p),
            "name": Path(p).name,
            "media_type": "video",
            "duration_us": 3_000_000,
            "width": 1080,
            "height": 1920,
        },
    )

    # Avoid full read/write chain — stub import_clips
    monkeypatch.setattr(
        ingest,
        "import_clips",
        lambda path, paths, **kw: {
            "imported_count": len(paths),
            "clips": [],
            "timeline_duration_sec": 3.0,
        },
    )

    created = ingest.create_project_from_media([str(clip)], project_name="my-trip")
    assert created["project_name"] == "my-trip"
    assert Path(created["project_path"]).exists()
    meta = json.loads((Path(created["project_path"]) / "draft_meta_info.json").read_text())
    assert meta["draft_name"] == "my-trip"


def test_create_project_requires_files():
    with pytest.raises(ValueError, match="At least one"):
        ingest.create_project_from_media([])
