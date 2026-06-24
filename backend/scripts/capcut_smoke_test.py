#!/usr/bin/env python3
"""CapCut automation smoke test — run before trusting MCP for real edits.

Usage:
  cd backend && uv run python scripts/capcut_smoke_test.py
  cd backend && uv run python scripts/capcut_smoke_test.py --live   # needs CapCut open
  cd backend && uv run python scripts/capcut_smoke_test.py --live --project 0613
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# backend/ on path when run as script
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


def _warn(msg: str) -> None:
    print(f"  ~ {msg}")


def check_offline() -> dict[str, bool]:
    """Tests that need no CapCut app open."""
    results: dict[str, bool] = {}
    print("\n=== Offline checks (no CapCut needed) ===\n")

    try:
        from capcut.reader import get_all_projects

        projects = get_all_projects()
        if projects:
            _ok(f"Found {len(projects)} CapCut project(s) — latest: {projects[0]['name']}")
            results["projects"] = True
        else:
            _fail("No CapCut projects in drafts folder — create one in CapCut first")
            results["projects"] = False
    except Exception as e:
        _fail(f"Project scan: {e}")
        results["projects"] = False

    try:
        import subprocess

        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        if r.returncode == 0:
            _ok("FFmpeg available (captions / media probe)")
            results["ffmpeg"] = True
        else:
            _warn("FFmpeg not found — captions may fail")
            results["ffmpeg"] = False
    except Exception:
        _warn("FFmpeg not found")
        results["ffmpeg"] = False

    try:
        from agent.runtime.model import llm_available, provider_order

        if llm_available():
            _ok(f"LLM available — providers: {', '.join(provider_order())}")
            results["llm"] = True
        else:
            _warn("No LLM — UI agent will use rule playbook only (set GROQ_API_KEY or run ollama)")
            results["llm"] = False
    except Exception as e:
        _warn(f"LLM check: {e}")
        results["llm"] = False

    try:
        from capcut.capabilities import all_capabilities

        caps = all_capabilities()
        layers = {}
        for c in caps:
            layers[c.layer] = layers.get(c.layer, 0) + 1
        _ok(f"Capability catalog: {len(caps)} entries — {layers}")
        results["capabilities"] = True
    except Exception as e:
        _fail(f"Capabilities: {e}")
        results["capabilities"] = False

    return results


def check_live(project_name: str | None = None, dry_ui: bool = False) -> dict[str, bool]:
    """Tests that need CapCut running + Accessibility."""
    results: dict[str, bool] = {}
    print("\n=== Live checks (CapCut must be open & focused) ===\n")

    from capcut.accessibility import accessibility_status
    from capcut.guard import is_capcut_running

    if is_capcut_running():
        _ok("CapCut process is running")
        results["capcut_running"] = True
    else:
        _fail("CapCut is not running — open CapCut with your project first")
        results["capcut_running"] = False
        return results

    ax = accessibility_status()
    if ax.get("granted"):
        _ok(f"Accessibility granted (host: {ax.get('host_app')})")
        results["accessibility"] = True
    else:
        _fail(f"Accessibility OFF — enable {ax.get('host_app')} in System Settings → Privacy")
        results["accessibility"] = False

    if not results.get("accessibility"):
        return results

    from capcut.ui_discover import discover_capcut_ui

    ui = discover_capcut_ui(max_items=30)
    count = ui.get("count", 0)
    if ui.get("success") and count > 5:
        _ok(f"UI discovery: {count} visible elements")
        for el in (ui.get("elements") or [])[:5]:
            print(f"      · [{el.get('kind')}] {el.get('label', '')[:50]}")
        results["ui_discover"] = True
    elif ui.get("success") and count > 0:
        _warn(f"UI discovery: only {count} elements — CapCut window visible?")
        results["ui_discover"] = True
    else:
        _fail(f"UI discovery failed: {ui.get('error', 'unknown')}")
        results["ui_discover"] = False

    if dry_ui:
        _warn("Skipping shortcut test (--dry-ui)")
        return results

    from capcut.shortcuts import run_shortcut

    save = run_shortcut("save")
    if save.get("success"):
        _ok("Shortcut test: save (Cmd+S) sent to CapCut")
        results["shortcut_save"] = True
    else:
        _fail(f"Shortcut save failed: {save.get('error')}")
        results["shortcut_save"] = False

    from capcut.reader import get_all_projects, get_project_summary

    projects = get_all_projects()
    path = None
    if project_name:
        for p in projects:
            if p.get("name") == project_name:
                path = p["path"]
                break
    if not path and projects:
        path = projects[0]["path"]

    if path:
        try:
            summary = get_project_summary(path)
            ov = summary.get("overview", {})
            _ok(
                f"Timeline read: {ov.get('video_clip_count', 0)} clips, "
                f"{ov.get('duration_sec', 0)}s — project {Path(path).name}"
            )
            results["timeline_read"] = True
        except Exception as e:
            _fail(f"Timeline read: {e}")
            results["timeline_read"] = False

    return results


def print_capability_matrix() -> None:
    print("\n=== What advanced editing can do TODAY ===\n")
    matrix = [
        ("Basic", "Read timeline, list projects", "disk", "✓ reliable"),
        ("Basic", "Trim / split / reorder clips", "disk", "✓ reliable"),
        ("Basic", "Save / export dialog", "UI shortcut", "✓ if Accessibility ON"),
        ("Intermediate", "Whisper captions", "disk", "✓ needs FFmpeg + audio"),
        ("Intermediate", "Color presets (cinematic, warm…)", "disk", "✓ reliable"),
        ("Intermediate", "Music duck, fade, beat sync", "disk", "✓ reliable"),
        ("Intermediate", "Transitions & effects from catalog", "disk", "✓ if catalog built"),
        ("Intermediate", "CapCut library search/download", "UI RPA", "~ needs CapCut open"),
        ("Advanced", "Native auto captions (CapCut UI)", "UI menu", "~ version-dependent"),
        ("Advanced", "Filters panel via click", "UI discover", "~ label must match"),
        ("Advanced", "AutoCut / AI design", "UI RPA", "~ best-effort"),
        ("Advanced", "Background cutout", "UI RPA", "~ clip must be selected"),
        ("Advanced", "Keyframes, zoom, shake", "disk script", "✓ execute_capcut_script"),
        ("Advanced", "Multi-step auto edit (Director team)", "agent", "✓ needs LLM + web/MCP"),
        ("Expert", "Every CapCut Pro feature", "UI vision", "✗ not built yet — Phase 3"),
    ]
    for tier, feat, layer, status in matrix:
        print(f"  [{tier:12}] {feat:40} {layer:12} {status}")


def print_mcp_tests() -> None:
    print("\n=== MCP tests to run in Cursor (after smoke test passes) ===\n")
    tests = [
        ("1. Discovery", "discover_capcut_ui()", "Returns 10+ UI elements"),
        ("2. Safe UI", "capcut_shortcut('save')", "CapCut saves — no visual change maybe"),
        ("3. Preview", "plan_capcut_automation(goal='add captions and export')", "Shows planned steps"),
        ("4. UI automate", "capcut_ui_automate(goal='open export dialog')", "Export dialog opens"),
        ("5. Disk edit", "get_timeline_summary()", "Full clip list"),
        ("6. Color", "apply_color_preset(preset='cinematic')", "Filter on timeline (check in CapCut)"),
        ("7. Captions", "generate_captions(style='travel')", "Subtitles appear (Whisper)"),
        ("8. Full UI", "capcut_ui_automate(goal='filters panel, then save')", "Multi-step UI log"),
        ("9. Verify", "verify_project(expectations={min_video_clips: 1})", "QA pass/fail"),
    ]
    for name, cmd, expect in tests:
        print(f"  {name}")
        print(f"    → {cmd}")
        print(f"    expect: {expect}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="CapCut automation smoke test")
    parser.add_argument("--live", action="store_true", help="Run live CapCut + UI tests")
    parser.add_argument("--project", type=str, default=None, help="Project name e.g. 0613")
    parser.add_argument("--dry-ui", action="store_true", help="Skip sending shortcuts to CapCut")
    parser.add_argument("--json", action="store_true", help="JSON output only")
    args = parser.parse_args()

    offline = check_offline()
    live: dict[str, bool] = {}
    if args.live:
        live = check_live(project_name=args.project, dry_ui=args.dry_ui)

    if not args.json:
        print_capability_matrix()
        print_mcp_tests()

    all_results = {**offline, **live}
    passed = sum(1 for v in all_results.values() if v)
    total = len(all_results)

    print(f"\n=== Score: {passed}/{total} checks passed ===\n")

    if args.json:
        print(json.dumps({"passed": passed, "total": total, "results": all_results}, indent=2))

    if not offline.get("projects"):
        return 2
    if args.live and not live.get("accessibility"):
        return 1
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
