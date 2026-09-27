"""Task state: dataclasses, one JSON file per task, and an append-only event log."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class Predicate:
    """One checkable condition: a kind from `grade.PREDICATE_KINDS` and its arguments."""

    kind: str
    args: dict[str, Any]


@dataclass
class Unit:
    """A small piece of work. `status` is one of pending, passed, failed, descoped."""

    id: str
    intent: str
    predicates: list[Predicate]
    status: str = "pending"
    attempts: int = 0
    branch: str | None = None
    summary: str = ""


@dataclass
class Task:
    """A goal and its units. `terminal` is None while running, else done, stopped or interrupted."""

    id: str
    goal: str
    workspace: str
    project: str = "_root"
    tick: int = 0
    units: list[Unit] = field(default_factory=list)
    cost_usd: float = 0.0
    terminal: str | None = None
    stop_reason: str = ""
    question: str | None = None
    director_session: str | None = None
    created: str = ""
    extra_usd: float = 0.0
    extra_ticks: int = 0


def to_json(task: Task) -> str:
    """The task as indented JSON text."""
    return json.dumps(asdict(task), indent=2) + "\n"


def from_json(text: str) -> Task:
    """Rebuild a task, its units and their predicates from `to_json` output."""
    data = json.loads(text)
    if "manager_session" in data:  # Saved tasks from before the role rename.
        data.setdefault("director_session", data.pop("manager_session"))
    units = [
        Unit(**{**u, "predicates": [Predicate(**p) for p in u["predicates"]]})
        for u in data.pop("units", [])
    ]
    return Task(**data, units=units)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_task_id(now: datetime | None = None) -> str:
    """`task-YYYYMMDDTHHMMSS`, from `now` or the current UTC time."""
    return "task-" + (now or _utc_now()).strftime("%Y%m%dT%H%M%S")


@dataclass
class Root:
    """The brain root: tracked prompts and config, plus generated task state and mailbox."""

    path: Path

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    def state_dir(self, task_id: str) -> Path:
        return self.path / "state" / task_id

    def task_file(self, task_id: str) -> Path:
        return self.state_dir(task_id) / "task.json"

    def log_file(self, task_id: str) -> Path:
        return self.state_dir(task_id) / "log.jsonl"

    def seat_dir(self, task_id: str) -> Path:
        return self.state_dir(task_id) / "seat"

    def clones_dir(self, task_id: str) -> Path:
        return self.state_dir(task_id) / "clones"

    @property
    def current_file(self) -> Path:
        return self.path / "state" / "current"

    @property
    def mailbox_open(self) -> Path:
        return self.path / "mailbox" / "open"

    @property
    def mailbox_closed(self) -> Path:
        return self.path / "mailbox" / "closed"

    @property
    def config_file(self) -> Path:
        return self.path / "config.json"

    @property
    def director_prompt(self) -> Path:
        return self.path / "director.md"

    @property
    def editor_prompt(self) -> Path:
        return self.path / "editor.md"


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def save(root: Root, task: Task) -> None:
    """Write `task.json`, replacing the previous copy in one rename."""
    _write_atomic(root.task_file(task.id), to_json(task))


def load(root: Root, task_id: str) -> Task:
    """Read one task. A missing task file raises `FileNotFoundError`."""
    return from_json(root.task_file(task_id).read_text(encoding="utf-8"))


def current(root: Root) -> Task | None:
    """The task `state/current` names, or None when no task has been started."""
    try:
        task_id = root.current_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return load(root, task_id) if task_id else None


def set_current(root: Root, task_id: str) -> None:
    """Point `state/current` at a task id."""
    _write_atomic(root.current_file, task_id + "\n")


def append_log(root: Root, task_id: str, event: dict[str, Any]) -> None:
    """Append one event as a JSON line, stamped with a UTC `ts`."""
    path = root.log_file(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"ts": _utc_now().isoformat(timespec="seconds"), **event})
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def pending_unit(task: Task) -> Unit | None:
    """The first unit still pending, or None."""
    return next((unit for unit in task.units if unit.status == "pending"), None)


def all_verified(task: Task) -> bool:
    """Every unit passed or descoped, and at least one passed."""
    statuses = [unit.status for unit in task.units]
    return "passed" in statuses and all(s in ("passed", "descoped") for s in statuses)
