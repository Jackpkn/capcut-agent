"""Layer 3 — sandboxed Python scripting against CapCut drafts."""

from __future__ import annotations

import ast
import io
import textwrap
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any

_BLOCKED_NAMES = frozenset({
    "__import__", "eval", "exec", "compile", "open", "input",
    "breakpoint", "exit", "quit", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "help", "memoryview",
})

_BLOCKED_MODULES = frozenset({
    "os", "sys", "subprocess", "socket", "pathlib", "shutil",
    "importlib", "pickle", "ctypes", "multiprocessing", "signal",
    "requests", "httpx", "urllib", "builtins",
})


class ScriptSecurityError(ValueError):
    pass


def _validate_ast(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _BLOCKED_MODULES:
                    raise ScriptSecurityError(f"Import blocked: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root in _BLOCKED_MODULES:
                    raise ScriptSecurityError(f"Import blocked: {node.module}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _BLOCKED_NAMES:
                raise ScriptSecurityError(f"Call blocked: {node.func.id}()")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "__builtins__":
                raise ScriptSecurityError("Direct __builtins__ access blocked")


def _safe_builtins() -> dict[str, Any]:
    return {
        "abs": abs,
        "min": min,
        "max": max,
        "round": round,
        "len": len,
        "range": range,
        "float": float,
        "int": int,
        "str": str,
        "bool": bool,
        "list": list,
        "dict": dict,
        "tuple": tuple,
        "set": set,
        "enumerate": enumerate,
        "zip": zip,
        "sum": sum,
        "sorted": sorted,
        "reversed": reversed,
        "any": any,
        "all": all,
        "print": print,
    }


def build_script_namespace(project_path: str) -> dict[str, Any]:
    """Expose safe CapCut APIs to agent-written scripts."""
    import capcut.draft_ops as draft_ops
    import capcut.filters as filters
    import capcut.primitives as primitives
    from capcut.reader import get_project_summary, read_project
    from capcut.writer import (
        add_effect,
        add_filter,
        add_transition,
        apply_color_preset,
        duck_audio,
        fade_project_music,
        reorder_clips,
        set_audio_fade,
        split_clip,
        trim_clip,
        write_project,
    )

    return {
        "project_path": project_path,
        "read_project": read_project,
        "write_project": write_project,
        "get_summary": lambda: get_project_summary(project_path),
        "primitives": primitives,
        "filters": filters,
        "draft_ops": draft_ops,
        "add_filter": lambda preset, **kw: add_filter(project_path, preset, **kw),
        "add_transition": lambda **kw: add_transition(project_path, **kw),
        "add_effect": lambda **kw: add_effect(project_path, **kw),
        "apply_color_preset": lambda preset, **kw: apply_color_preset(project_path, preset, **kw),
        "duck_audio": lambda **kw: duck_audio(project_path, **kw),
        "fade_project_music": lambda **kw: fade_project_music(project_path, **kw),
        "set_audio_fade": lambda **kw: set_audio_fade(project_path, **kw),
        "split_clip": lambda **kw: split_clip(project_path, **kw),
        "trim_clip": lambda **kw: trim_clip(project_path, **kw),
        "reorder_clips": lambda **kw: reorder_clips(project_path, **kw),
        "result": None,
    }


def execute_capcut_script(
    project_path: str,
    code: str,
    *,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    """Run sandboxed Python that mutates a CapCut project via writer primitives."""
    cleaned = textwrap.dedent(code or "").strip()
    if not cleaned:
        raise ValueError("code cannot be empty")

    try:
        tree = ast.parse(cleaned, mode="exec")
    except SyntaxError as exc:
        raise ValueError(f"Script syntax error: {exc}") from exc

    _validate_ast(tree)

    namespace = build_script_namespace(project_path)
    namespace["__builtins__"] = _safe_builtins()

    stdout = io.StringIO()

    def _run() -> Any:
        import sys

        old_stdout = sys.stdout
        sys.stdout = stdout
        try:
            compiled = compile(tree, "<capcut_script>", "exec")
            exec(compiled, namespace, namespace)  # noqa: S102 — sandboxed agent scripting
            return namespace.get("result")
        finally:
            sys.stdout = old_stdout

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run)
        try:
            script_result = future.result(timeout=timeout_sec)
        except FuturesTimeout as exc:
            raise TimeoutError(f"Script exceeded {timeout_sec}s timeout") from exc
        except Exception as exc:
            tb = traceback.format_exc()
            raise RuntimeError(f"Script failed: {exc}\n{tb}") from exc

    return {
        "ok": True,
        "result": script_result,
        "stdout": stdout.getvalue().strip(),
        "project_path": project_path,
    }
