"""Phase 4 — auto-download missing CapCut assets via UI + CDP reload."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from capcut.catalog import (
    asset_exists_on_disk,
    find_bundle_path,
    get_asset,
    refresh_resource,
)
from capcut.cdp import is_connected, sync_capcut
from capcut.ui_trigger import download_asset_ui

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 0.5
DEFAULT_TIMEOUT_SEC = 45


def _wait_for_resource(
    resource_id: str | None,
    asset_type: str,
    timeout: float = DEFAULT_TIMEOUT_SEC,
) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if resource_id:
            path = find_bundle_path(resource_id, asset_type)
            if path:
                return path
        time.sleep(POLL_INTERVAL_SEC)
    return None


def ensure_asset_cached(
    asset: dict,
    project_path: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SEC,
) -> dict:
    """
    Ensure asset files exist on disk. Downloads via CapCut UI when missing.
    Returns refreshed catalog entry with valid path.
    """
    if asset_exists_on_disk(asset):
        path = asset.get("path")
        if not path or not Path(path).exists():
            path = find_bundle_path(str(asset["resource_id"]), asset["type"])
            if path:
                asset = refresh_resource(str(asset["resource_id"]), asset["type"]) or asset
                asset["path"] = path
                asset["cached"] = True
        return asset

    if not is_connected():
        raise ValueError(
            f'"{asset["name"]}" is not cached — launch CapCut with '
            f"--remote-debugging-port=9222 and try again"
        )

    resource_id = str(asset.get("resource_id") or "")
    asset_type = asset.get("type", "music")
    search_name = asset.get("name", "")

    if search_name.endswith("…") or search_name.startswith(asset_type.title()):
        search_name = ""

    ui_result = download_asset_ui(
        query=search_name or resource_id[:8],
        asset_type=asset_type,
        item_name=search_name or None,
    )
    if not ui_result.get("success"):
        hint = ui_result.get("hint") or ui_result.get("error", "download failed")
        raise ValueError(f'Could not download "{asset.get("name")}": {hint}')

    bundle_path = _wait_for_resource(resource_id or None, asset_type, timeout=timeout)

    if not bundle_path and search_name:
        refreshed = get_asset(name=search_name, asset_type=asset_type)
        if refreshed and asset_exists_on_disk(refreshed):
            bundle_path = refreshed.get("path")

    if not bundle_path and resource_id:
        bundle_path = _wait_for_resource(resource_id, asset_type, timeout=5)

    if bundle_path and resource_id:
        asset = refresh_resource(resource_id, asset_type) or asset
    elif bundle_path:
        asset = {**asset, "path": bundle_path, "cached": True}
    else:
        raise ValueError(
            f'Download triggered for "{asset.get("name")}" but cache file did not appear in time. '
            f"Try downloading manually in CapCut, then Rebuild Index."
        )

    if project_path:
        sync_capcut(project_path)

    return asset


def download_asset(
    *,
    resource_id: str | None = None,
    name: str | None = None,
    asset_type: str = "music",
    project_path: str | None = None,
) -> dict:
    asset = get_asset(resource_id=resource_id, name=name, asset_type=asset_type)
    if not asset:
        raise ValueError(f"Asset not in catalog: resource_id={resource_id} name={name}")
    return ensure_asset_cached(asset, project_path=project_path)
