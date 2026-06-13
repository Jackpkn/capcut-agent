import asyncio
import json
import logging
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import websockets

logger = logging.getLogger(__name__)

CDP_HOST = "http://localhost:9222"


def is_connected() -> bool:
    try:
        with urlopen(f"{CDP_HOST}/json", timeout=2) as resp:
            pages = json.loads(resp.read())
            return isinstance(pages, list) and len(pages) > 0
    except (URLError, TimeoutError, OSError):
        return False


def get_pages() -> list[dict]:
    try:
        with urlopen(f"{CDP_HOST}/json", timeout=2) as resp:
            return json.loads(resp.read())
    except (URLError, TimeoutError, OSError):
        return []


async def _send_cdp(ws_url: str, method: str, params: dict | None = None, msg_id: int = 1) -> bool:
    try:
        async with websockets.connect(ws_url, open_timeout=3) as ws:
            await ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
            await asyncio.wait_for(ws.recv(), timeout=3)
            return True
    except Exception as e:
        logger.warning("CDP %s failed for %s: %s", method, ws_url, e)
        return False


async def _reload_all() -> dict:
    pages = get_pages()
    if not pages:
        return {"connected": False, "reloaded": 0, "total": 0}

    tasks = []
    for i, page in enumerate(pages):
        ws_url = page.get("webSocketDebuggerUrl")
        if ws_url:
            tasks.append(_send_cdp(ws_url, "Page.reload", {"ignoreCache": True}, msg_id=i * 2 + 1))
            tasks.append(_send_cdp(ws_url, "Runtime.evaluate", {
                "expression": "window.dispatchEvent(new Event('resize')); true;",
            }, msg_id=i * 2 + 2))

    results = await asyncio.gather(*tasks) if tasks else []
    reloaded = sum(1 for r in results if r)
    return {"connected": True, "reloaded": reloaded, "total": len(pages)}


def touch_project_files(project_path: str):
    """Bump mtime so CapCut's file watcher picks up changes."""
    from capcut.reader import get_draft_write_paths

    base = Path(project_path)
    touched: set[Path] = set()
    for draft in get_draft_write_paths(project_path):
        if draft.exists():
            draft.touch()
            touched.add(draft)
            logger.info("Touched %s for CapCut reload", draft)
    for name in ("draft_meta_info.json",):
        f = base / name
        if f.exists() and f not in touched:
            f.touch()
            logger.info("Touched %s for CapCut reload", f)


def sync_capcut(project_path: str | None = None) -> dict:
    if project_path:
        touch_project_files(project_path)
        time.sleep(0.3)
    try:
        result = asyncio.run(_reload_all())
        result["file_touched"] = project_path is not None
        return result
    except Exception as e:
        logger.warning("CDP sync_capcut error: %s", e)
        return {
            "connected": is_connected(),
            "reloaded": 0,
            "file_touched": project_path is not None,
            "error": str(e),
        }


def trigger_reload(project_path: str | None = None) -> dict:
    return sync_capcut(project_path)
