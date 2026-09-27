"""CLI: the dry scenarios' exit codes, status on an empty and a live root, the --extend grammar."""

from __future__ import annotations

import fcntl
import json
import os
import signal
import time
from pathlib import Path

import pytest

from protean import cli
from protean.dry import ScriptedRunner
from protean.state import Root, Task, load, save, set_current


def test_dry_dry_ends_done_and_exits_0(capsys: pytest.CaptureFixture[str]):
    assert cli.main(["dry", "dry"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[-2].startswith("tick 4:") and lines[-1].startswith("terminal: done")


def test_dry_stuck_ends_interrupted_and_exits_12(capsys: pytest.CaptureFixture[str]):
    assert cli.main(["dry", "stuck"]) == 12
    assert capsys.readouterr().out.strip().splitlines()[-1].startswith("terminal: interrupted")


def test_an_unknown_scenario_is_a_usage_error(capsys: pytest.CaptureFixture[str]):
    assert cli.main(["dry", "nope"]) == 2
    assert "unknown scenario 'nope' (known: dry, stuck)" in capsys.readouterr().err


def test_status_on_an_empty_root_says_there_is_no_task(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert cli.main(["--brain", str(tmp_path / "empty"), "status"]) == 0
    assert capsys.readouterr().out.startswith("no task in ")


def test_status_shows_the_current_task(root: Root, task: Task, capsys: pytest.CaptureFixture[str]):
    task.cost_usd, task.terminal, task.stop_reason = 10.2, "stopped", "max_usd: 10.20 >= 10.0"
    save(root, task)
    set_current(root, task.id)
    assert cli.main(["--brain", str(root.path), "status"]) == 0
    out = capsys.readouterr().out
    for piece in (task.id, "terminal: stopped — max_usd", "cost: $10.20 of $10.00", "u1", "pending", "tick: 0 of 30"):
        assert piece in out


def test_resume_without_a_task_is_a_usage_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert cli.main(["--brain", str(tmp_path), "resume"]) == 2
    assert "no task in" in capsys.readouterr().err
    assert cli.main(["--brain", str(tmp_path), "resume", "--extend", "10m"]) == 2
    assert "no wall-clock ceiling" in capsys.readouterr().err


def test_resume_on_a_locked_task_is_a_usage_error(root: Root, task: Task, capsys: pytest.CaptureFixture[str]):
    task.terminal, task.question = "interrupted", "q?"
    save(root, task)
    set_current(root, task.id)
    with (root.state_dir(task.id) / "lock").open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.write("4242\n")
        handle.flush()
        assert cli.main(["--brain", str(root.path), "resume"]) == 2
    assert f"task {task.id} is already running (pid 4242)" in capsys.readouterr().err


def test_extend_repeats_to_widen_ticks_and_dollars_together(root: Root, task: Task, monkeypatch: pytest.MonkeyPatch):
    task.tick, task.cost_usd, task.terminal, task.stop_reason = 30, 9.8, "stopped", "max_ticks: 30 >= 30"
    task.units[0].status = "failed"
    save(root, task)
    set_current(root, task.id)
    root.director_prompt.write_text("m\n")
    question = {"type": "result", "is_error": False, "session_id": "s", "total_cost_usd": 0.1,
                "result": json.dumps({"question": "q?"})}
    runner = ScriptedRunner([question], [])
    monkeypatch.setattr(cli, "real_runner", runner)
    assert cli.main(["--brain", str(root.path), "resume", "--extend", "5", "--extend", "$1"]) == 12
    saved = load(root, task.id)
    assert (saved.extra_ticks, saved.extra_usd, len(runner.calls)) == (5, 1.0, 1)


def _ctrl_c() -> None:
    raise KeyboardInterrupt


def _sigterm() -> None:
    os.kill(os.getpid(), signal.SIGTERM)
    time.sleep(1)


def _sighup() -> None:
    os.kill(os.getpid(), signal.SIGHUP)
    time.sleep(1)


@pytest.mark.parametrize("stop", [_ctrl_c, _sigterm, _sighup])
def test_a_ctrl_c_mid_call_exits_130_with_the_charge_on_disk(root: Root, task: Task, tmp_path: Path, stop,
                                                            capsys: pytest.CaptureFixture[str]):
    from protean.dry import make_workspace
    task.workspace = str(make_workspace(tmp_path / "ws"))
    task.terminal, task.question = "interrupted", "q?"
    save(root, task)
    set_current(root, task.id)
    root.editor_prompt.write_text("e\n")
    (root.mailbox_open / f"{task.id}.md").parent.mkdir(parents=True)
    (root.mailbox_open / f"{task.id}.md").write_text("## Question\nq?\n\n## Answer\ngo on\n")
    def interrupt(argv, stdin, cwd, timeout):
        stop()
        raise AssertionError("the stop signal did not interrupt the call")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(cli, "real_runner", interrupt)
    try:
        assert cli.main(["--brain", str(root.path), "resume"]) == 130
    finally:
        monkeypatch.undo()
    assert "booked" in capsys.readouterr().err
    saved = load(root, task.id)
    assert (saved.cost_usd, saved.units[0].attempts, saved.terminal) == (4.0, 1, None)


@pytest.mark.parametrize("text, parsed", [("5", (0.0, 5)), ("$2.5", (2.5, 0)), ("$3", (3.0, 0))])
def test_extend_takes_ticks_or_dollars(text: str, parsed: tuple[float, int]):
    assert cli.parse_extend(text) == parsed


@pytest.mark.parametrize("text", ["10m", "0", "$0", "five", "-3", "3$"])
def test_extend_refuses_anything_else(text: str):
    with pytest.raises(ValueError):
        cli.parse_extend(text)
