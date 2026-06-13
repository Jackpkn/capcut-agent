"""CapCut library access via CDP — no third-party API keys.

Uses Chrome DevTools Protocol to:
1. Capture CapCut API responses when the desktop app searches its library
2. Reuse the app's CEF session cookies for same-origin fetches
3. Persist a searchable catalog from captured traffic
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import websockets

from capcut.cdp import get_pages, is_connected
from capcut.cache_index import _match_score

logger = logging.getLogger(__name__)

CATALOG_PATH = Path.home() / ".capcut-agent" / "cdp_catalog.json"
CAPCUT_API_RE = re.compile(r"capcutapi\.com|capcut\.com/lv/", re.I)

_capture_thread: threading.Thread | None = None
_capture_running = False
_capture_stats = {"responses": 0, "items": 0, "last_capture_at": None}


def _ensure_catalog_dir():
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_catalog() -> dict[str, list[dict]]:
    _ensure_catalog_dir()
    if not CATALOG_PATH.exists():
        return {"music": [], "effects": [], "transitions": []}
    try:
        data = json.loads(CATALOG_PATH.read_text())
        return {
            "music": data.get("music", []),
            "effects": data.get("effects", []),
            "transitions": data.get("transitions", []),
        }
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load CDP catalog: %s", e)
        return {"music": [], "effects": [], "transitions": []}


def _save_catalog(catalog: dict[str, list[dict]]):
    _ensure_catalog_dir()
    CATALOG_PATH.write_text(json.dumps(catalog, indent=2))


def _dedupe_key(item: dict) -> str:
    return str(item.get("resource_id") or item.get("id") or item.get("name", "")).lower()


def _merge_items(existing: list[dict], new_items: list[dict]) -> list[dict]:
    by_key = {_dedupe_key(i): i for i in existing}
    for item in new_items:
        by_key[_dedupe_key(item)] = item
    return list(by_key.values())


def _parse_capcut_payload(data: dict | list, source_url: str = "") -> list[dict]:
    """Extract library items from various CapCut API response shapes."""
    results: list[dict] = []

    def walk(node):
        if isinstance(node, dict):
            for key in ("effect_item_list", "items", "resources", "song_list", "music_list"):
                if key in node and isinstance(node[key], list):
                    for raw in node[key]:
                        parsed = _parse_item(raw, source_url)
                        if parsed:
                            results.append(parsed)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data if isinstance(data, (dict, list)) else {})
    return results


def _parse_item(raw: dict, source_url: str = "") -> dict | None:
    if not isinstance(raw, dict):
        return None

    attrs = raw.get("common_attr") or raw
    name = (
        attrs.get("title")
        or attrs.get("name")
        or raw.get("title")
        or raw.get("name")
        or raw.get("description")
    )
    if not name or not str(name).strip():
        return None

    effect_type = raw.get("effect_type") or attrs.get("effect_type")
    asset_type = _infer_type(str(name), effect_type, source_url)

    resource_id = (
        attrs.get("effect_id")
        or raw.get("effect_id")
        or raw.get("id")
        or attrs.get("id")
        or raw.get("music_id")
        or attrs.get("music_id")
    )

    return {
        "id": str(resource_id or name),
        "name": str(name).strip(),
        "type": asset_type,
        "resource_id": str(resource_id) if resource_id else None,
        "thumbnail": raw.get("static_image") or attrs.get("cover_url") or attrs.get("icon_url"),
        "source": "cdp",
        "origin": "capcut_live",
        "cached": False,
        "capture_url": source_url[:120] if source_url else None,
    }


def _infer_type(name: str, effect_type, source_url: str) -> str:
    url_l = source_url.lower()
    if "transition" in url_l or effect_type in (3, "transition"):
        return "transition"
    if "music" in url_l or "song" in url_l or "audio" in url_l:
        return "music"
    if "effect" in url_l or effect_type in (2, 4, "effect"):
        return "effect"
    n = name.lower()
    if any(w in n for w in ("transition", "fade", "wipe", "dissolve")):
        return "transition"
    return "effect"


def _ingest_response_body(url: str, body: str) -> int:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return 0

    if isinstance(data, dict) and data.get("ret") not in (None, "0", 0):
        return 0

    items = _parse_capcut_payload(data, url)
    if not items:
        return 0

    catalog = _load_catalog()
    for item in items:
        key = "music" if item["type"] == "music" else "effects" if item["type"] == "effect" else "transitions"
        catalog[key] = _merge_items(catalog.get(key, []), [item])

    _save_catalog(catalog)
    _capture_stats["items"] = sum(len(v) for v in catalog.values())
    _capture_stats["last_capture_at"] = time.time()
    return len(items)


def get_capcut_page() -> dict | None:
    pages = get_pages()
    for page in pages:
        url = page.get("url", "")
        if "capcut.com" in url:
            return page
    return pages[0] if pages else None


async def _cdp_fetch(ws_url: str, path: str, body: dict) -> str:
    async with websockets.connect(ws_url, open_timeout=5) as ws:
        js = (
            f"(async()=>{{"
            f"try{{const r=await fetch('{path}',{{"
            f"method:'POST',"
            f"headers:{{'Content-Type':'application/json'}},"
            f"body:JSON.stringify({json.dumps(body)})"
            f"}});"
            f"return await r.text();"
            f"}}catch(e){{return JSON.stringify({{error:String(e)}})}}"
            f"}})()"
        )
        await ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": js, "awaitPromise": True, "returnByValue": True},
        }))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            if msg.get("id") == 1:
                return msg.get("result", {}).get("result", {}).get("value", "")


async def _capture_page(ws_url: str, stop_event: threading.Event):
    msg_id = 1
    pending_urls: dict[str, str] = {}
    body_requests: dict[int, str] = {}

    try:
        async with websockets.connect(ws_url, open_timeout=5) as ws:
            await ws.send(json.dumps({"id": msg_id, "method": "Network.enable", "params": {}}))
            msg_id += 1

            while not stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                msg = json.loads(raw)
                method = msg.get("method", "")

                if method == "Network.responseReceived":
                    params = msg.get("params", {})
                    response = params.get("response", {})
                    url = response.get("url", "")
                    req_id = params.get("requestId")
                    if req_id and CAPCUT_API_RE.search(url):
                        pending_urls[req_id] = url

                elif method == "Network.loadingFinished":
                    req_id = msg.get("params", {}).get("requestId")
                    url = pending_urls.pop(req_id, None)
                    if not url:
                        continue

                    body_requests[msg_id] = url
                    await ws.send(json.dumps({
                        "id": msg_id,
                        "method": "Network.getResponseBody",
                        "params": {"requestId": req_id},
                    }))
                    msg_id += 1

                elif "result" in msg and msg.get("id") in body_requests:
                    rid = msg["id"]
                    url = body_requests.pop(rid)
                    body = msg.get("result", {}).get("body")
                    if body:
                        added = _ingest_response_body(url, body)
                        if added:
                            _capture_stats["responses"] += 1
                            logger.info("CDP captured %d items from %s", added, url[:80])

    except Exception as e:
        logger.debug("CDP capture page ended: %s", e)


async def _run_capture(stop_event: threading.Event):
    while not stop_event.is_set():
        if not is_connected():
            await asyncio.sleep(2)
            continue

        pages = get_pages()
        tasks = []
        for page in pages:
            ws_url = page.get("webSocketDebuggerUrl")
            if ws_url:
                tasks.append(_capture_page(ws_url, stop_event))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            await asyncio.sleep(2)


def start_capture() -> dict:
    global _capture_thread, _capture_running

    if _capture_running and _capture_thread and _capture_thread.is_alive():
        return capture_status()

    stop_event = threading.Event()

    def runner():
        global _capture_running
        _capture_running = True
        try:
            asyncio.run(_run_capture(stop_event))
        finally:
            _capture_running = False

    _capture_thread = threading.Thread(target=runner, daemon=True, name="cdp-library-capture")
    _capture_thread.start()
    return capture_status()


def capture_status() -> dict:
    catalog = _load_catalog()
    return {
        "running": _capture_running,
        "cdp_connected": is_connected(),
        "responses_captured": _capture_stats["responses"],
        "catalog_items": sum(len(v) for v in catalog.values()),
        "music": len(catalog.get("music", [])),
        "effects": len(catalog.get("effects", [])),
        "transitions": len(catalog.get("transitions", [])),
        "last_capture_at": _capture_stats["last_capture_at"],
        "hint": (
            None
            if sum(len(v) for v in catalog.values()) > 0
            else "Click 'Sync from CapCut' or search here — we'll auto-trigger CapCut's library panel via CDP"
        ),
    }


def is_cdp_live_available() -> bool:
    if not is_connected():
        return False
    catalog = _load_catalog()
    return sum(len(v) for v in catalog.values()) > 0 or _capture_running


def search_captured(query: str, asset_type: str = "all", limit: int = 20) -> list[dict]:
    catalog = _load_catalog()
    type_map = {
        "all": ["music", "effects", "transitions"],
        "music": ["music"],
        "audio": ["music"],
        "effect": ["effects"],
        "effects": ["effects"],
        "transition": ["transitions"],
        "transitions": ["transitions"],
    }
    keys = type_map.get(asset_type, ["music", "effects", "transitions"])

    results = []
    for key in keys:
        list_key = key
        for item in catalog.get(list_key, []):
            score = _match_score(query, item.get("name", ""))
            if score > 0 or not query.strip():
                results.append({**item, "score": score if query.strip() else 0.5, "origin": "capcut_live"})

    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return results[:limit]


async def search_via_cdp_api(query: str, asset_type: str = "music", limit: int = 10) -> list[dict]:
    """Attempt live search through CapCut's CEF page (uses app's own session)."""
    page = get_capcut_page()
    if not page:
        return []

    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        return []

    effect_type = 4 if asset_type in ("music", "audio") else 2
    body = {
        "keyword": query,
        "offset": 0,
        "count": limit,
        "effect_type": effect_type,
        "search_option": {"cc_web_use": True},
    }

    try:
        text = await _cdp_fetch(
            ws_url,
            "https://editor-api-va.capcutapi.com/artist/v1/effect/search",
            body,
        )
        data = json.loads(text)
        if isinstance(data, dict) and data.get("ret") not in (None, "0", 0):
            return []

        items = _parse_capcut_payload(data)
        for item in items[:limit]:
            item["score"] = 0.9
            item["origin"] = "capcut_live"
        if items:
            catalog = _load_catalog()
            for item in items:
                key = "music" if item["type"] == "music" else "effects" if item["type"] == "effect" else "transitions"
                catalog[key] = _merge_items(catalog.get(key, []), [item])
            _save_catalog(catalog)
        return items[:limit]
    except Exception as e:
        logger.debug("CDP API search failed: %s", e)
        return []


def search_cdp_live(query: str, asset_type: str = "all", limit: int = 20) -> list[dict]:
    """Search captured catalog + attempt live CDP API."""
    if not is_connected():
        return []

    captured = search_captured(query, asset_type, limit=limit)

    if query.strip() and len(captured) < limit:
        types = ["music", "effect"] if asset_type == "all" else [asset_type]
        for t in types:
            try:
                live = asyncio.run(search_via_cdp_api(query, t, limit=5))
                seen = {_dedupe_key(i) for i in captured}
                for item in live:
                    if _dedupe_key(item) not in seen:
                        captured.append(item)
                        seen.add(_dedupe_key(item))
            except Exception:
                pass

    captured.sort(key=lambda x: x.get("score", 0), reverse=True)
    return captured[:limit]


def ensure_capcut_page() -> bool:
    """Navigate a CDP page to capcut.com so fetches use the app session."""
    if not is_connected():
        return False

    pages = get_pages()
    if any("capcut.com" in p.get("url", "") for p in pages):
        return True

    target = pages[0] if pages else None
    if not target:
        return False

    ws_url = target.get("webSocketDebuggerUrl")
    if not ws_url:
        return False

    async def navigate():
        async with websockets.connect(ws_url, open_timeout=5) as ws:
            await ws.send(json.dumps({
                "id": 1,
                "method": "Page.navigate",
                "params": {"url": "https://www.capcut.com/"},
            }))
            await asyncio.wait_for(ws.recv(), timeout=10)

    try:
        asyncio.run(navigate())
        return True
    except Exception as e:
        logger.warning("Failed to navigate CapCut CEF page: %s", e)
        return False
