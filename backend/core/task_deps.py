"""Phase B — infer task dependencies and topological sort for team/auto-edit."""

from __future__ import annotations

from core.models import Task, domain_for_action

# Lower runs earlier within a chapter/session batch.
_ACTION_ORDER: dict[str, int] = {
    "trim_clip": 10,
    "reorder_clips": 15,
    "update_clip_speed": 20,
    "move_segment": 25,
    "set_segment_visibility": 30,
    "replace_music": 40,
    "add_music": 41,
    "update_volume": 45,
    "add_transition": 50,
    "update_transition": 51,
    "add_effect": 55,
    "remove_effect": 56,
    "add_sticker": 60,
    "generate_captions": 70,
    "update_text": 71,
    "batch_update_texts": 72,
    "add_text_template": 73,
    "draft_operations": 80,
}

_DOMAIN_ORDER: dict[str, int] = {
    "video": 0,
    "audio": 1,
    "effects": 2,
    "text": 3,
    "assets": 4,
    "qa": 5,
}

_PACING_ACTIONS = frozenset({"trim_clip", "reorder_clips", "update_clip_speed", "move_segment"})
_MUSIC_ACTIONS = frozenset({"add_music", "replace_music"})
_CAPTION_ACTIONS = frozenset({"generate_captions", "batch_update_texts", "update_text", "add_text_template"})
_TRANSITION_ACTIONS = frozenset({"add_transition", "update_transition"})


def _sort_key(task: Task) -> tuple[int, int, int]:
    domain = domain_for_action(task.action).value
    return (
        _DOMAIN_ORDER.get(domain, 9),
        _ACTION_ORDER.get(task.action, 50),
        -int(task.priority or 0),
    )


def infer_task_dependencies(tasks: list[Task]) -> list[Task]:
    """Assign depends_on from edit semantics (pacing → music → transitions → captions)."""
    pacing_ids = [t.id for t in tasks if t.action in _PACING_ACTIONS]
    music_ids = [t.id for t in tasks if t.action in _MUSIC_ACTIONS]
    transition_ids = [t.id for t in tasks if t.action in _TRANSITION_ACTIONS]

    for task in tasks:
        deps: list[str] = []
        if task.action in _MUSIC_ACTIONS and pacing_ids:
            deps.extend(pacing_ids)
        if task.action in _TRANSITION_ACTIONS:
            if pacing_ids:
                deps.extend(pacing_ids)
            if music_ids:
                deps.extend(music_ids)
        if task.action in _CAPTION_ACTIONS:
            if music_ids:
                deps.extend(music_ids)
            if pacing_ids:
                deps.extend(pacing_ids[:1])
        task.depends_on = list(dict.fromkeys(deps))
    return tasks


def topological_sort_tasks(tasks: list[Task]) -> list[Task]:
    """Stable topo sort; independent tasks fall back to domain/action order."""
    by_id = {t.id: t for t in tasks}
    visited: set[str] = set()
    result: list[Task] = []

    def visit(task: Task) -> None:
        if task.id in visited:
            return
        visited.add(task.id)
        for dep_id in task.depends_on or []:
            dep = by_id.get(dep_id)
            if dep:
                visit(dep)
        result.append(task)

    for task in sorted(tasks, key=_sort_key):
        visit(task)
    return result


def order_tasks(tasks: list[Task]) -> list[Task]:
    """Infer deps then topo-sort for execution / apply."""
    if not tasks:
        return []
    return topological_sort_tasks(infer_task_dependencies(list(tasks)))


def order_action_dicts(actions: list[dict]) -> list[dict]:
    """Order pending action dicts using the same rules as team tasks."""
    if len(actions) < 2:
        return actions

    tasks = [
        Task(
            id=f"action_{i}",
            type=domain_for_action(action.get("action", "")),
            instruction="",
            action=action.get("action", ""),
            params=action.get("params") or {},
            description=action.get("description", ""),
            priority=0,
        )
        for i, action in enumerate(actions)
    ]
    ordered = order_tasks(tasks)
    index_by_id = {f"action_{i}": i for i in range(len(actions))}
    return [actions[index_by_id[task.id]] for task in ordered if task.id in index_by_id]
