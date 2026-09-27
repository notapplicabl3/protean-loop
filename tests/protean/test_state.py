"""State: the task round-trips through JSON and disk, the log appends, the unit helpers."""

from __future__ import annotations

import json
from datetime import datetime

from protean.state import (
    Predicate, Root, Task, Unit, all_verified, append_log, current, from_json, load,
    new_task_id, pending_unit, save, set_current, to_json,
)


def test_task_round_trips_through_json_and_disk(root: Root):
    units = [
        Unit("u1", "write a", [Predicate("file_exists", {"path": "a"})], "passed", 1, "unit/u1", "ok"),
        Unit("u2", "run it", [Predicate("exit_code", {"code": 0}), Predicate("command", {"cmd": "true"})]),
    ]
    task = Task("task-20260927T120000", "g", "/w", "p", 4, units, 1.25, "interrupted", "", "which?", "sess-1", "c")
    again = from_json(to_json(task))
    assert again == task and isinstance(again.units[1].predicates[0], Predicate)
    save(root, task)
    assert load(root, task.id) == task
    task.tick = 5
    save(root, task)
    assert load(root, task.id).tick == 5
    assert not list(root.state_dir(task.id).glob("*.tmp"))


def test_legacy_session_loads_and_saves_as_director():
    data = json.loads(to_json(Task("t", "g", "/w")))
    del data["director_session"]
    data["manager_session"] = "existing-session"
    task = from_json(json.dumps(data))
    assert task.director_session == "existing-session"
    saved = json.loads(to_json(task))
    assert saved["director_session"] == "existing-session" and "manager_session" not in saved


def test_new_task_id_format():
    assert new_task_id(datetime(2026, 9, 27, 8, 5, 3)) == "task-20260927T080503"
    assert len(new_task_id()) == len("task-YYYYMMDDTHHMMSS")


def test_root_layout(root: Root):
    p = root.path
    assert [root.state_dir("t"), root.task_file("t"), root.log_file("t"), root.seat_dir("t"), root.clones_dir("t")] == [
        p / "state/t", p / "state/t/task.json", p / "state/t/log.jsonl", p / "state/t/seat", p / "state/t/clones"
    ]
    assert [root.current_file, root.mailbox_open, root.mailbox_closed] == [
        p / "state/current", p / "mailbox/open", p / "mailbox/closed"
    ]
    assert [root.config_file, root.director_prompt, root.editor_prompt] == [
        p / "config.json", p / "director.md", p / "editor.md"
    ]


def test_current_is_none_on_an_empty_root_then_follows_set_current(root: Root, task: Task):
    assert current(root) is None
    save(root, task)
    set_current(root, task.id)
    assert root.current_file.read_text() == task.id + "\n"
    assert current(root) == task


def test_append_log_writes_one_stamped_line_per_event(root: Root):
    append_log(root, "t", {"event": "tick", "n": 1})
    append_log(root, "t", {"event": "verdict", "passed": False})
    lines = [json.loads(line) for line in root.log_file("t").read_text().splitlines()]
    assert [line["event"] for line in lines] == ["tick", "verdict"]
    assert all("ts" in line for line in lines) and lines[1]["passed"] is False


def test_pending_unit_and_all_verified(task: Task):
    task.units.append(Unit("u2", "more", [Predicate("file_exists", {"path": "b"})]))
    assert not all_verified(Task("t", "g", "/w"))
    assert pending_unit(task).id == "u1" and not all_verified(task)
    task.units[0].status = "passed"
    assert pending_unit(task).id == "u2" and not all_verified(task)
    task.units[1].status = "failed"
    assert pending_unit(task) is None and not all_verified(task)
    task.units[1].status = "descoped"
    assert all_verified(task)
    task.units[0].status = "descoped"
    assert not all_verified(task)
