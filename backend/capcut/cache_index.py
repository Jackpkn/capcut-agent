"""Backward-compatible wrapper around the local asset catalog."""

from capcut.catalog import build_catalog, get_stats, search_catalog


def get_index(force_refresh: bool = False) -> dict[str, list[dict]]:
    if force_refresh:
        build_catalog()
    stats = get_stats()
    return {
        "music": _items_for_type("music"),
        "effects": _items_for_type("effect"),
        "transitions": _items_for_type("transition"),
        "stickers": _items_for_type("sticker"),
        "text_templates": _items_for_type("text_template"),
        "_stats": stats,
    }


def _items_for_type(asset_type: str) -> list[dict]:
    return search_catalog("", asset_type, limit=500)


def search_local(query: str, asset_type: str = "all", limit: int = 20) -> list[dict]:
    return search_catalog(query, asset_type, limit=limit)


def build_index() -> dict[str, list[dict]]:
    build_catalog()
    return get_index()
