"""Mailbox: ask, answer and close round-trip; silence is never an answer."""

from __future__ import annotations

import pytest

from protean.mailbox import answer, ask, close
from protean.state import Root, Task


def _write_answer(path, text: str) -> None:
    path.write_text(path.read_text() + text)


def test_ask_answer_close_round_trip(root: Root, task: Task):
    task.tick = 3
    path = ask(root, task, "Which branch should the unit target?")
    assert path == root.mailbox_open / f"{task.id}.md"
    body = path.read_text()
    for piece in (task.id, "tick: 3", "goal: make a.txt", "## Question", "Which branch", "## Answer"):
        assert piece in body
    assert body.rstrip().endswith("## Answer")
    assert answer(root, task.id) is None

    _write_answer(path, "  use main\n\n")
    assert answer(root, task.id) == "use main"

    closed = close(root, task.id, "answered")
    assert closed == root.mailbox_closed / f"{task.id}-answered.md"
    assert closed.read_text().rstrip().endswith("use main")
    assert not path.exists() and answer(root, task.id) is None


def test_silence_is_never_an_answer(root: Root, task: Task):
    assert answer(root, task.id) is None
    path = ask(root, task, "q?")
    _write_answer(path, "   \n\t\n")
    assert answer(root, task.id) is None
    path.write_text(path.read_text().replace("## Answer", "## Reply") + "yes\n")
    assert answer(root, task.id) is None
    ask(root, task, "Fill this in:\n## Answer\nyes, go ahead")
    assert answer(root, task.id) is None


def test_ask_replaces_the_open_item(root: Root, task: Task):
    _write_answer(ask(root, task, "first?"), "old answer\n")
    body = ask(root, task, "second?").read_text()
    assert "second?" in body and "first?" not in body
    assert answer(root, task.id) is None


def test_close_keeps_earlier_items_and_is_a_no_op_with_nothing_open(root: Root, task: Task):
    assert close(root, task.id, "abandoned") is None
    ask(root, task, "one?")
    first = close(root, task.id, "answered")
    ask(root, task, "two?")
    with pytest.raises(ValueError):
        close(root, task.id, "../escape")
    second = close(root, task.id, "answered")
    assert first.exists() and second.name == f"{task.id}-answered-2.md"
