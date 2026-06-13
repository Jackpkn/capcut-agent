"""Library search — local catalog first (Phase 1–3). CDP used only for live reload."""

import logging

from capcut.catalog import build_catalog, get_asset, get_director_picks, get_stats, search_catalog
from capcut.cdp import is_connected
from capcut.downloader import download_asset

logger = logging.getLogger(__name__)


def is_online_available() -> bool:
    stats = get_stats()
    return stats.get("total", 0) > 0


def search_library(
    query: str,
    asset_type: str = "all",
    limit: int = 20,
    include_online: bool = True,
    auto_trigger: bool = False,
) -> dict:
    del include_online, auto_trigger  # catalog-only search; CDP not used for discovery

    results = search_catalog(query, asset_type, limit=limit)
    stats = get_stats()

    return {
        "query": query,
        "type": asset_type,
        "online_available": is_connected(),
        "catalog": stats,
        "online_hint": None,
        "count": len(results),
        "results": results,
        "stats": {
            "local": len(results),
            "online": 0,
            "catalog_total": stats.get("total", 0),
            "music": stats.get("by_type", {}).get("music", {}).get("total", 0),
            "effects": stats.get("by_type", {}).get("effect", {}).get("total", 0),
            "transitions": stats.get("by_type", {}).get("transition", {}).get("total", 0),
            "stickers": stats.get("by_type", {}).get("sticker", {}).get("total", 0),
            "text_templates": stats.get("by_type", {}).get("text_template", {}).get("total", 0),
        },
    }


def find_asset(query: str, asset_type: str = "music") -> dict | None:
    return get_asset(name=query, asset_type=asset_type)


def find_music_by_name(query: str) -> dict | None:
    return find_asset(query, "music")


def refresh_catalog() -> dict:
    return build_catalog()


def init_cdp_library():
    """Build catalog on startup; CDP capture no longer required for search."""
    stats = get_stats()
    if stats.get("total", 0) == 0:
        return build_catalog()
    return stats


def director_picks(mood: str = "energetic") -> dict:
    return get_director_picks(mood)


def ensure_cached(
    resource_id: str | None = None,
    name: str | None = None,
    asset_type: str = "music",
    project_path: str | None = None,
) -> dict:
    return download_asset(
        resource_id=resource_id,
        name=name,
        asset_type=asset_type,
        project_path=project_path,
    )
