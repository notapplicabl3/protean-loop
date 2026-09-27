"""Questions for the operator: one open file per task, answered by hand under `## Answer`.

Silence is never assent: an item with nothing written under `## Answer` has no answer.
"""

from __future__ import annotations

import re
from pathlib import Path

from protean.state import Root, Task

ANSWER_HEADING = "## Answer"


def open_path(root: Root, task_id: str) -> Path:
    """Where a task's open question lives."""
    return root.mailbox_open / f"{task_id}.md"


def ask(root: Root, task: Task, question: str) -> Path:
    """Write the task's open question, replacing any earlier open one, and return its path."""
    path = open_path(root, task.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Question for {task.id}\n\n"
        f"- task: {task.id}\n"
        f"- tick: {task.tick}\n"
        f"- goal: {task.goal}\n\n"
        f"Write the answer under {ANSWER_HEADING}, then run `protean resume`.\n\n"
        f"## Question\n\n{question.strip()}\n\n"
        f"{ANSWER_HEADING}\n\n",
        encoding="utf-8",
    )
    return path


def answer(root: Root, task_id: str) -> str | None:
    """The text under the last `## Answer` heading, stripped; None when empty or no item."""
    try:
        lines = open_path(root, task_id).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    headings = [i for i, line in enumerate(lines) if line.strip() == ANSWER_HEADING]
    if not headings:
        return None
    text = "\n".join(lines[headings[-1] + 1 :]).strip()
    return text or None


def close(root: Root, task_id: str, disposition: str) -> Path | None:
    """Move the open item to `mailbox/closed/<task_id>-<disposition>.md`; None if none is open.

    An earlier closed item of the same name is kept; the new one takes a `-2`, `-3`... suffix.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", disposition):
        raise ValueError(f"disposition must be a plain word, got {disposition!r}")
    source = open_path(root, task_id)
    if not source.exists():
        return None
    root.mailbox_closed.mkdir(parents=True, exist_ok=True)
    stem = f"{task_id}-{disposition}"
    target, n = root.mailbox_closed / f"{stem}.md", 1
    while target.exists():
        n += 1
        target = root.mailbox_closed / f"{stem}-{n}.md"
    source.replace(target)
    return target
