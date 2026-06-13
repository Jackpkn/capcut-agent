"""Orchestrate CDP capture + CapCut UI search to populate the live library catalog."""

from __future__ import annotations

import logging
import time

from capcut.cdp import is_connected
from capcut.cdp_library import (
    _load_catalog,
    _merge_items,
    _save_catalog,
    capture_status,
    ensure_capcut_page,
    search_captured,
    search_via_cdp_api,
    start_capture,
)
from capcut.ui_trigger import scrape_capcut_results, trigger_capcut_search

logger = logging.getLogger(__name__)

_last_trigger_at = 0.0
TRIGGER_COOLDOWN_SEC = 4.0


def _catalog_size() -> int:
    catalog = _load_catalog()
    return sum(len(v) for v in catalog.values())


def _ingest_scraped_results(names: list[str], asset_type: str) -> int:
    if not names:
        return 0

    item_type = "music" if asset_type in ("music", "audio", "transition", "transitions") else "effect"
    catalog_key = "music" if item_type == "music" else "effects" if item_type == "effect" else "transitions"

    catalog = _load_catalog()
    items = [
        {
            "id": name,
            "name": name,
            "type": item_type,
            "resource_id": None,
            "source": "ui_scrape",
            "origin": "capcut_live",
            "cached": False,
        }
        for name in names
    ]
    catalog[catalog_key] = _merge_items(catalog.get(catalog_key, []), items)
    _save_catalog(catalog)
    return len(items)


def _wait_for_results(query: str, asset_type: str, timeout: float = 8.0) -> dict:
    before = _catalog_size()
    deadline = time.time() + timeout
    captured = 0

    while time.time() < deadline:
        time.sleep(0.4)
        now = _catalog_size()
        if now > before:
            captured = now - before
            break
        if query and search_captured(query, asset_type, limit=1):
            captured = 1
            break

    return {
        "catalog_before": before,
        "catalog_after": _catalog_size(),
        "items_captured": captured,
        "waited_sec": round(min(timeout, time.time() - (deadline - timeout)), 1),
    }


async def _try_cdp_api_search(query: str, asset_type: str) -> int:
    import asyncio

    try:
        items = await search_via_cdp_api(query, asset_type, limit=10)
        return len(items)
    except Exception as e:
        logger.debug("CDP API prefetch failed: %s", e)
        return 0


def trigger_library_search(
    query: str = "music",
    asset_type: str = "music",
    wait: bool = True,
    force: bool = False,
) -> dict:
    """Trigger CapCut library search via UI automation + CDP capture."""
    global _last_trigger_at

    query = (query or "music").strip()
    asset_type = asset_type if asset_type != "all" else "music"

    if not is_connected():
        return {
            "success": False,
            "error": "cdp_not_connected",
            "hint": (
                "Launch CapCut with: "
                "open /Applications/CapCut.app --args --remote-debugging-port=9222"
            ),
        }

    now = time.time()
    if not force and now - _last_trigger_at < TRIGGER_COOLDOWN_SEC:
        return {
            "success": False,
            "error": "cooldown",
            "retry_after_sec": round(TRIGGER_COOLDOWN_SEC - (now - _last_trigger_at), 1),
        }

    start_capture()
    ensure_capcut_page()

    import asyncio
    api_items = asyncio.run(_try_cdp_api_search(query, asset_type))

    ui_result = trigger_capcut_search(query, asset_type)
    _last_trigger_at = now

    scraped = scrape_capcut_results()
    scraped_ingested = _ingest_scraped_results(scraped, asset_type)

    wait_result = _wait_for_results(query, asset_type, timeout=8.0 if wait else 0.5)
    wait_result["ui_scraped"] = len(scraped)
    wait_result["ui_ingested"] = scraped_ingested

    success = (
        ui_result.get("success")
        and (scraped_ingested > 0 or wait_result["items_captured"] > 0 or api_items > 0)
    ) or _catalog_size() > 0

    return {
        "success": success,
        "query": query,
        "asset_type": asset_type,
        "ui": ui_result,
        "cdp_api_items": api_items,
        "capture": wait_result,
        "scraped_results": scraped[:20],
        "status": capture_status(),
    }


def maybe_auto_trigger(query: str, asset_type: str = "all") -> dict | None:
    """Auto-trigger once when CDP is connected but catalog is empty."""
    if not query.strip() or not is_connected():
        return None
    if _catalog_size() > 0:
        return None
    return trigger_library_search(query, asset_type, wait=True)
