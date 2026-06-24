"""Local CapCut asset catalog — Phase 1.

Indexes music, effects, transitions, stickers, and text templates from:
- Project draft_info.json (best display names + resource_ids)
- Cache/effect/{resource_id}/{md5}/ bundles on disk
- Cache/artistEffect/ text templates
- Cache/music/ audio files
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import time
from pathlib import Path

from capcut.reader import PROJECTS_PATH

CATALOG_DB = Path.home() / ".capcut-agent" / "catalog.db"
CACHE_ROOT = Path.home() / "Movies/CapCut/User Data/Cache"
CONTAINER_CACHE = (
    Path.home()
    / "Library/Containers/com.lemon.lvoverseas/Data/Movies/CapCut/User Data/Cache"
)

ASSET_TYPES = ("music", "effect", "filter", "transition", "sticker", "text_template")


def _cache_dirs() -> list[Path]:
    dirs = [CACHE_ROOT]
    if CONTAINER_CACHE.exists() and CONTAINER_CACHE.resolve() != CACHE_ROOT.resolve():
        dirs.append(CONTAINER_CACHE)
    return dirs


def _resolve_path(path: str) -> str:
    if not path:
        return path
    p = Path(path)
    if p.exists():
        return str(p.resolve())
    movies = Path.home() / "Movies/CapCut/User Data/Cache"
    container = CONTAINER_CACHE
    for prefix in (container, movies):
        if "Cache/" in path or "Cache\\" in path:
            suffix = path.split("Cache/", 1)[-1].split("Cache\\", 1)[-1]
            candidate = prefix / suffix
            if candidate.exists():
                return str(candidate.resolve())
    return path


def _probe_duration(path: Path) -> int | None:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        sec = float(data.get("format", {}).get("duration", 0))
        return int(sec * 1_000_000) if sec > 0 else None
    except Exception:
        return None


def _classify_effect_bundle(bundle_dir: Path) -> str:
    extra = bundle_dir / "extra.json"
    config = bundle_dir / "config.json"
    if extra.exists():
        try:
            data = json.loads(extra.read_text())
            if "transition" in data:
                return "transition"
        except (json.JSONDecodeError, OSError):
            pass
    if config.exists():
        try:
            raw = config.read_text()
            data = json.loads(raw)
            kind = str(data.get("type", ""))
            if "InfoSticker" in kind or "Sticker" in kind:
                return "sticker"
        except (json.JSONDecodeError, OSError):
            pass
        if "anim.prefab" in [p.name for p in bundle_dir.iterdir() if p.is_file()]:
            return "sticker"
    return "effect"


def _match_score(query: str, name: str) -> float:
    q = query.lower().strip()
    n = name.lower()
    if not q:
        return 0.5
    if q in n:
        return 1.0
    tokens = [t for t in re.split(r"\W+", q) if t]
    if not tokens:
        return 0
    hits = sum(1 for t in tokens if t in n)
    return hits / len(tokens)


def _connect() -> sqlite3.Connection:
    CATALOG_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CATALOG_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_id TEXT NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            path TEXT,
            effect_id TEXT,
            material_type TEXT,
            category_name TEXT,
            duration_us INTEGER,
            is_overlap INTEGER,
            cached INTEGER DEFAULT 0,
            source TEXT,
            UNIQUE(resource_id, type, path)
        );
        CREATE INDEX IF NOT EXISTS idx_assets_name ON assets(name);
        CREATE INDEX IF NOT EXISTS idx_assets_type ON assets(type);
        CREATE INDEX IF NOT EXISTS idx_assets_resource ON assets(resource_id);
    """)


def _upsert(conn: sqlite3.Connection, item: dict):
    conn.execute(
        """
        INSERT INTO assets (
            resource_id, name, type, path, effect_id, material_type,
            category_name, duration_us, is_overlap, cached, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(resource_id, type, path) DO UPDATE SET
            name = CASE
                WHEN excluded.source = 'project' THEN excluded.name
                WHEN assets.source = 'project' THEN assets.name
                ELSE excluded.name
            END,
            effect_id = excluded.effect_id,
            material_type = COALESCE(excluded.material_type, material_type),
            category_name = COALESCE(excluded.category_name, category_name),
            duration_us = COALESCE(excluded.duration_us, duration_us),
            is_overlap = COALESCE(excluded.is_overlap, is_overlap),
            cached = MAX(excluded.cached, assets.cached),
            source = CASE
                WHEN excluded.source = 'project' THEN 'project'
                WHEN assets.source = 'project' THEN 'project'
                ELSE excluded.source
            END
        """,
        (
            str(item.get("resource_id") or item.get("effect_id") or item.get("id", "")),
            item.get("name") or "Unknown",
            item["type"],
            item.get("path"),
            str(item.get("effect_id") or item.get("resource_id") or ""),
            item.get("material_type"),
            item.get("category_name"),
            item.get("duration_us"),
            1 if item.get("is_overlap") else 0 if "is_overlap" in item else None,
            1 if item.get("cached") else 0,
            item.get("source", "unknown"),
        ),
    )


def _index_from_projects(conn: sqlite3.Connection) -> int:
    count = 0
    if not PROJECTS_PATH.exists():
        return 0

    for folder in PROJECTS_PATH.iterdir():
        draft = folder / "draft_info.json"
        if not draft.exists():
            continue
        try:
            data = json.loads(draft.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        materials = data.get("materials", {})

        for item in materials.get("audios", []):
            path = _resolve_path(item.get("path", ""))
            if not path:
                continue
            _upsert(conn, {
                "resource_id": item.get("resource_id") or item.get("music_id") or item["id"],
                "name": item.get("name", "Unknown"),
                "type": "music",
                "path": path,
                "effect_id": item.get("music_id"),
                "duration_us": item.get("duration"),
                "cached": Path(path).exists(),
                "source": "project",
            })
            count += 1

        for item in materials.get("video_effects", []):
            path = _resolve_path(item.get("path", ""))
            is_filter = item.get("type") == "filter"
            _upsert(conn, {
                "resource_id": item.get("resource_id") or item.get("effect_id"),
                "name": item.get("name", "Filter" if is_filter else "Effect"),
                "type": "filter" if is_filter else "effect",
                "path": path,
                "effect_id": item.get("effect_id"),
                "material_type": item.get("type", "filter" if is_filter else "video_effect"),
                "category_name": item.get("category_name"),
                "cached": bool(path and Path(path).exists()),
                "source": "project",
            })
            count += 1

        for item in materials.get("transitions", []):
            path = _resolve_path(item.get("path", ""))
            _upsert(conn, {
                "resource_id": item.get("resource_id") or item.get("effect_id"),
                "name": item.get("name", "Transition"),
                "type": "transition",
                "path": path,
                "effect_id": item.get("effect_id"),
                "material_type": "transition",
                "category_name": item.get("category_name"),
                "duration_us": item.get("duration"),
                "is_overlap": item.get("is_overlap"),
                "cached": bool(path and Path(path).exists()),
                "source": "project",
            })
            count += 1

        for item in materials.get("text_templates", []):
            path = _resolve_path(item.get("path", ""))
            _upsert(conn, {
                "resource_id": item.get("resource_id") or item.get("effect_id"),
                "name": item.get("name", "Text template"),
                "type": "text_template",
                "path": path,
                "effect_id": item.get("effect_id"),
                "material_type": item.get("type", "text_template"),
                "category_name": item.get("category_name"),
                "cached": bool(path and Path(path).exists()),
                "source": "project",
            })
            count += 1

        for tmpl in materials.get("text_templates", []):
            for res in tmpl.get("resources", []):
                if res.get("panel") == "sticker":
                    path = _resolve_path(res.get("path", ""))
                    _upsert(conn, {
                        "resource_id": res.get("resource_id"),
                        "name": f"Sticker ({res.get('resource_id', '')[:8]}…)",
                        "type": "sticker",
                        "path": path,
                        "effect_id": res.get("resource_id"),
                        "material_type": "sticker",
                        "cached": bool(path and Path(path).exists()),
                        "source": "project",
                    })
                    count += 1

        for item in materials.get("stickers", []):
            path = _resolve_path(item.get("path", ""))
            _upsert(conn, {
                "resource_id": item.get("resource_id") or item.get("id"),
                "name": item.get("name", "Sticker"),
                "type": "sticker",
                "path": path,
                "effect_id": item.get("resource_id"),
                "material_type": "sticker",
                "cached": bool(path and Path(path).exists()),
                "source": "project",
            })
            count += 1

    return count


def _seed_builtin_filters(conn: sqlite3.Connection) -> int:
    from capcut.filters import VIDEO_FILTERS

    count = 0
    for slug, meta in VIDEO_FILTERS.items():
        path = find_bundle_path(meta["resource_id"], "filter") or ""
        _upsert(conn, {
            "resource_id": meta["resource_id"],
            "name": meta["name"],
            "type": "filter",
            "path": path,
            "effect_id": meta["resource_id"],
            "material_type": "filter",
            "category_name": "Filter",
            "cached": bool(path and Path(path).exists()),
            "source": "builtin",
        })
        count += 1
    return count


def _index_effect_cache(conn: sqlite3.Connection) -> int:
    count = 0
    seen: set[tuple[str, str]] = set()

    for cache_dir in _cache_dirs():
        effect_root = cache_dir / "effect"
        if not effect_root.exists():
            continue
        for resource_dir in effect_root.iterdir():
            if not resource_dir.is_dir() or resource_dir.name == "model":
                continue
            if not resource_dir.name.isdigit():
                continue
            for bundle_dir in resource_dir.iterdir():
                if not bundle_dir.is_dir() or bundle_dir.name.endswith("_tmp"):
                    continue
                key = (resource_dir.name, str(bundle_dir))
                if key in seen:
                    continue
                seen.add(key)

                asset_type = _classify_effect_bundle(bundle_dir)
                path = str(bundle_dir.resolve())
                duration_us = None
                is_overlap = None
                extra = bundle_dir / "extra.json"
                if extra.exists():
                    try:
                        ex = json.loads(extra.read_text())
                        if "transition" in ex:
                            duration_us = int(ex["transition"].get("defaultDura", 0) * 1_000_000)
                            is_overlap = ex["transition"].get("isOverlap", False)
                    except (json.JSONDecodeError, OSError, TypeError, ValueError):
                        pass

                _upsert(conn, {
                    "resource_id": resource_dir.name,
                    "name": f"{asset_type.title()} {resource_dir.name[:8]}…",
                    "type": asset_type,
                    "path": path,
                    "effect_id": resource_dir.name,
                    "material_type": asset_type,
                    "duration_us": duration_us,
                    "is_overlap": is_overlap,
                    "cached": True,
                    "source": "cache_scan",
                })
                count += 1

    return count


def _index_artist_effects(conn: sqlite3.Connection) -> int:
    count = 0
    for cache_dir in _cache_dirs():
        root = cache_dir / "artistEffect"
        if not root.exists():
            continue
        for resource_dir in root.iterdir():
            if not resource_dir.is_dir() or not resource_dir.name.isdigit():
                continue
            for bundle_dir in resource_dir.iterdir():
                if not bundle_dir.is_dir():
                    continue
                path = str(bundle_dir.resolve())
                name = f"Text template {resource_dir.name[:8]}…"
                config = bundle_dir / "config.json"
                if config.exists():
                    try:
                        cfg = json.loads(config.read_text())
                        name = cfg.get("name", name)
                    except (json.JSONDecodeError, OSError):
                        pass
                _upsert(conn, {
                    "resource_id": resource_dir.name,
                    "name": name,
                    "type": "text_template",
                    "path": path,
                    "effect_id": resource_dir.name,
                    "material_type": "text_template",
                    "cached": True,
                    "source": "cache_scan",
                })
                count += 1
    return count


def _index_music_cache(conn: sqlite3.Connection) -> int:
    count = 0
    seen: set[str] = set()
    for cache_dir in _cache_dirs():
        music_dir = cache_dir / "music"
        if not music_dir.exists():
            continue
        for file in music_dir.rglob("*.mp3"):
            path = str(file.resolve())
            if path in seen:
                continue
            seen.add(path)
            duration = _probe_duration(file)
            _upsert(conn, {
                "resource_id": file.stem,
                "name": f"Music {file.stem[:8]}…",
                "type": "music",
                "path": path,
                "duration_us": duration,
                "cached": True,
                "source": "cache_scan",
            })
            count += 1
    return count


def build_catalog() -> dict:
    conn = _connect()
    try:
        _init_db(conn)
        conn.execute("DELETE FROM assets")
        effect_n = _index_effect_cache(conn)
        filter_n = _seed_builtin_filters(conn)
        artist_n = _index_artist_effects(conn)
        music_n = _index_music_cache(conn)
        project_n = _index_from_projects(conn)
        conn.commit()
        stats = get_stats(conn)
        stats["build"] = {
            "project_rows": project_n,
            "cache_effect_rows": effect_n,
            "builtin_filter_rows": filter_n,
            "cache_artist_rows": artist_n,
            "cache_music_rows": music_n,
            "built_at": time.time(),
        }
        return stats
    finally:
        conn.close()


# Alias used by agents / older scripts
rebuild_catalog = build_catalog


def get_stats(conn: sqlite3.Connection | None = None) -> dict:
    own = conn is None
    if own:
        conn = _connect()
        _init_db(conn)
    try:
        rows = conn.execute(
            "SELECT type, COUNT(*) as n, SUM(cached) as cached_n FROM assets GROUP BY type"
        ).fetchall()
        by_type = {r["type"]: {"total": r["n"], "cached": r["cached_n"]} for r in rows}
        total = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        named = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE source = 'project'"
        ).fetchone()[0]
        return {
            "total": total,
            "named_from_projects": named,
            "by_type": by_type,
            "db_path": str(CATALOG_DB),
        }
    finally:
        if own:
            conn.close()


def _row_to_item(row: sqlite3.Row, score: float = 0) -> dict:
    return {
        "id": row["resource_id"],
        "resource_id": row["resource_id"],
        "effect_id": row["effect_id"],
        "name": row["name"],
        "type": row["type"],
        "path": row["path"],
        "material_type": row["material_type"],
        "category_name": row["category_name"],
        "duration_us": row["duration_us"],
        "is_overlap": bool(row["is_overlap"]) if row["is_overlap"] is not None else None,
        "cached": bool(row["cached"]),
        "source": row["source"],
        "origin": "local_catalog",
        "score": score,
    }


def search_catalog(
    query: str = "",
    asset_type: str = "all",
    limit: int = 20,
    cached_only: bool = False,
) -> list[dict]:
    conn = _connect()
    _init_db(conn)
    if conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0:
        conn.close()
        build_catalog()
        conn = _connect()

    type_map = {
        "all": list(ASSET_TYPES),
        "music": ["music"],
        "audio": ["music"],
        "effect": ["effect"],
        "effects": ["effect"],
        "filter": ["filter"],
        "filters": ["filter"],
        "transition": ["transition"],
        "transitions": ["transition"],
        "sticker": ["sticker"],
        "stickers": ["sticker"],
        "text_template": ["text_template"],
        "text": ["text_template"],
    }
    types = type_map.get(asset_type, list(ASSET_TYPES))

    placeholders = ",".join("?" * len(types))
    sql = f"SELECT * FROM assets WHERE type IN ({placeholders})"
    params: list = list(types)
    if cached_only:
        sql += " AND cached = 1"

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    results = []
    for row in rows:
        score = _match_score(query, row["name"])
        if score > 0 or not query.strip():
            if row["source"] == "project":
                score += 0.2
            results.append(_row_to_item(row, score))

    results.sort(key=lambda x: (-x["score"], x["name"]))
    return results[:limit]


def get_asset(
    *,
    resource_id: str | None = None,
    name: str | None = None,
    asset_type: str | None = None,
) -> dict | None:
    conn = _connect()
    _init_db(conn)
    if conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0:
        conn.close()
        build_catalog()
        conn = _connect()

    row = None
    if resource_id:
        sql = "SELECT * FROM assets WHERE resource_id = ?"
        params: list = [resource_id]
        if asset_type:
            sql += " AND type = ?"
            params.append(asset_type)
        sql += " ORDER BY CASE source WHEN 'project' THEN 0 ELSE 1 END LIMIT 1"
        row = conn.execute(sql, params).fetchone()

    if not row and name:
        hits = search_catalog(name, asset_type or "all", limit=1)
        conn.close()
        return hits[0] if hits else None

    conn.close()
    return _row_to_item(row) if row else None


def find_bundle_path(resource_id: str, asset_type: str) -> str | None:
    """Locate the newest on-disk bundle for a resource_id."""
    if not resource_id:
        return None

    rid = str(resource_id)
    roots: list[Path] = []
    if asset_type == "text_template":
        for cache_dir in _cache_dirs():
            roots.append(cache_dir / "artistEffect" / rid)
    elif asset_type == "music":
        for cache_dir in _cache_dirs():
            music_dir = cache_dir / "music"
            if music_dir.exists():
                for mp3 in music_dir.rglob("*.mp3"):
                    if rid in mp3.stem or rid in mp3.name:
                        return str(mp3.resolve())
        return None
    else:
        for cache_dir in _cache_dirs():
            roots.append(cache_dir / "effect" / rid)

    best: Path | None = None
    best_mtime = 0.0
    for root in roots:
        if not root.exists():
            continue
        if asset_type == "music":
            continue
        for bundle in root.iterdir():
            if not bundle.is_dir() or bundle.name.endswith("_tmp"):
                continue
            mtime = bundle.stat().st_mtime
            if mtime > best_mtime:
                best_mtime = mtime
                best = bundle
    return str(best.resolve()) if best else None


def asset_exists_on_disk(asset: dict) -> bool:
    path = asset.get("path")
    if path and Path(path).exists():
        return True
    bundle = find_bundle_path(str(asset.get("resource_id", "")), asset.get("type", ""))
    return bundle is not None


def refresh_resource(resource_id: str, asset_type: str | None = None) -> dict | None:
    """Re-index a single resource from disk into the catalog."""
    types = [asset_type] if asset_type else list(ASSET_TYPES)
    conn = _connect()
    _init_db(conn)
    updated = None

    for t in types:
        bundle = find_bundle_path(resource_id, t)
        if not bundle:
            continue
        item = {
            "resource_id": resource_id,
            "name": f"{t.title()} {resource_id[:8]}…",
            "type": t,
            "path": bundle,
            "effect_id": resource_id,
            "material_type": t,
            "cached": True,
            "source": "cache_scan",
        }
        if t == "music" and bundle.endswith(".mp3"):
            item["duration_us"] = _probe_duration(Path(bundle))
        elif t != "music":
            bundle_path = Path(bundle)
            extra = bundle_path / "extra.json"
            if extra.exists():
                try:
                    ex = json.loads(extra.read_text())
                    if "transition" in ex:
                        item["type"] = "transition"
                        item["material_type"] = "transition"
                        item["duration_us"] = int(ex["transition"].get("defaultDura", 0) * 1_000_000)
                        item["is_overlap"] = ex["transition"].get("isOverlap", False)
                except (json.JSONDecodeError, OSError, TypeError, ValueError):
                    pass
            if t != "music":
                item["type"] = _classify_effect_bundle(bundle_path)

        existing = conn.execute(
            "SELECT name, source FROM assets WHERE resource_id = ? AND type = ? AND source = 'project' LIMIT 1",
            (resource_id, item["type"]),
        ).fetchone()
        if existing:
            item["name"] = existing["name"]
            item["source"] = "project"

        _upsert(conn, item)
        updated = item

    conn.commit()
    conn.close()
    if not updated:
        return None
    return get_asset(resource_id=resource_id, asset_type=updated["type"])


def get_director_picks(mood: str = "energetic", limit: int = 8) -> dict:
    """Curated catalog picks for AI director (Phase 3)."""
    mood_queries = {
        "energetic": ["zoom", "glitch", "beat", "fast", "dynamic"],
        "calm": ["fade", "soft", "slow", "ambient", "smooth"],
        "dramatic": ["cinematic", "impact", "flash", "dark"],
        "fun": ["bounce", "pop", "comic", "upbeat"],
    }
    queries = mood_queries.get(mood.lower(), mood_queries["energetic"])
    transitions, effects, music = [], [], []
    for q in queries:
        transitions.extend(search_catalog(q, "transition", limit=2))
        effects.extend(search_catalog(q, "effect", limit=2))
        music.extend(search_catalog(q, "music", limit=2))

    def dedupe(items):
        seen = set()
        out = []
        for i in sorted(items, key=lambda x: -x["score"]):
            k = i["resource_id"]
            if k not in seen:
                seen.add(k)
                out.append(i)
        return out[:limit]

    return {
        "mood": mood,
        "transitions": dedupe(transitions),
        "effects": dedupe(effects),
        "music": dedupe(music),
    }
