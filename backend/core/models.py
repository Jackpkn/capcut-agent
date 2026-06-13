"""Data models for the multi-agent editing team."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    TEXT = "text"
    EFFECTS = "effects"
    ASSETS = "assets"
    QA = "qa"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    DONE = "done"
    FAILED = "failed"


class SessionStatus(str, Enum):
    PLANNING = "planning"
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    APPLYING = "applying"
    DONE = "done"
    PAUSED = "paused"
    FAILED = "failed"


ACTION_DOMAIN: dict[str, TaskType] = {
    "update_clip_speed": TaskType.VIDEO,
    "trim_clip": TaskType.VIDEO,
    "reorder_clips": TaskType.VIDEO,
    "move_segment": TaskType.VIDEO,
    "set_segment_visibility": TaskType.VIDEO,
    "add_music": TaskType.AUDIO,
    "replace_music": TaskType.AUDIO,
    "update_volume": TaskType.AUDIO,
    "generate_captions": TaskType.TEXT,
    "update_text": TaskType.TEXT,
    "batch_update_texts": TaskType.TEXT,
    "add_text_template": TaskType.TEXT,
    "add_transition": TaskType.EFFECTS,
    "add_effect": TaskType.EFFECTS,
    "remove_effect": TaskType.EFFECTS,
    "add_sticker": TaskType.EFFECTS,
    "update_transition": TaskType.EFFECTS,
}

SPECIALIST_FOR_TYPE: dict[TaskType, str] = {
    TaskType.VIDEO: "Video Agent",
    TaskType.AUDIO: "Audio Agent",
    TaskType.TEXT: "Text Agent",
    TaskType.EFFECTS: "FX Agent",
    TaskType.ASSETS: "Assets Agent",
    TaskType.QA: "QA Agent",
}


def domain_for_action(action: str) -> TaskType:
    return ACTION_DOMAIN.get(action, TaskType.EFFECTS)


@dataclass
class Goal:
    id: str
    description: str
    type: TaskType
    priority: int = 3
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "type": self.type.value,
            "priority": self.priority,
            "depends_on": self.depends_on,
        }


@dataclass
class Task:
    id: str
    type: TaskType
    instruction: str
    action: str
    params: dict
    description: str = ""
    specialist: str = ""
    context_summary: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    agent_reasoning: str = ""
    qa_feedback: list[str] = field(default_factory=list)
    qa_approved: bool = False
    requires_human_approval: bool = True
    priority: int = 0
    chapter_id: str = ""
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "instruction": self.instruction,
            "action": self.action,
            "params": self.params,
            "description": self.description,
            "specialist": self.specialist or SPECIALIST_FOR_TYPE.get(self.type, "Agent"),
            "context_summary": self.context_summary,
            "status": self.status.value,
            "agent_reasoning": self.agent_reasoning,
            "qa_feedback": self.qa_feedback,
            "qa_approved": self.qa_approved,
            "requires_human_approval": self.requires_human_approval,
            "priority": self.priority,
            "chapter_id": self.chapter_id,
            "depends_on": self.depends_on,
        }


@dataclass
class EditSession:
    id: str
    project_path: str
    human_message: str
    status: SessionStatus = SessionStatus.PLANNING
    goals: list[Goal] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    chapters: list = field(default_factory=list)  # list[Chapter] — avoid circular import
    current_chapter_index: int = 0
    session_memory: dict = field(default_factory=dict)  # SessionMemory.to_dict()
    brief_markdown: str = ""
    brief_data: dict = field(default_factory=dict)
    critic_notes: list[str] = field(default_factory=list)
    timeline_summary: dict = field(default_factory=dict)
    human_feedback: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_path": self.project_path,
            "human_message": self.human_message,
            "status": self.status.value,
            "goals": [g.to_dict() for g in self.goals],
            "tasks": [t.to_dict() for t in self.tasks],
            "chapters": [
                c.to_dict() if hasattr(c, "to_dict") else c for c in self.chapters
            ],
            "current_chapter_index": self.current_chapter_index,
            "session_memory": self.session_memory,
            "brief_markdown": self.brief_markdown,
            "brief_data": self.brief_data,
            "critic_notes": self.critic_notes,
            "timeline_summary": self.timeline_summary,
            "human_feedback": self.human_feedback,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "pending_count": sum(1 for t in self.tasks if t.status == TaskStatus.PENDING),
            "done_count": sum(1 for t in self.tasks if t.status == TaskStatus.DONE),
        }


def new_id() -> str:
    return str(uuid.uuid4())
