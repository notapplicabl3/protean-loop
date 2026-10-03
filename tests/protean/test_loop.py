"""Loop: the dry scenario's ticks, attempts then failure, delivery, done checked not believed, ceilings, resume."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
from pathlib import Path

import pytest

from protean import grade, loop, mailbox, director, state
from protean.budget import Caps
from protean.dry import FIXTURES, ScriptedRunner, make_workspace, read_jsonl
from protean.runner import RunResult
from protean.state import Predicate, Root, Task, Unit, load, save, set_current

UNIT = {"id": "u-1", "intent": "write a.txt", "predicates": [
    {"kind": "file_exists", "args": {"path": "a.txt"}}, {"kind": "exit_code", "args": {"code": 0}}]}
PASS = {"write": {"a.txt": "A\n"}, "commit": True, "exit_code": 0, "result": "wrote a.txt", "total_cost_usd": 0.5}
FAIL = {"write": {"b.txt": "wrong file\n"}, "commit": True, "exit_code": 1, "result": "could not do it", "total_cost_usd": 0.5}


def _reply(obj: dict, cost: float = 0.1) -> dict:
    return {"type": "result", "is_error": False, "session_id": "s-1", "total_cost_usd": cost, "result": json.dumps(obj)}


@pytest.fixture
def env(tmp_path: Path, root: Root) -> tuple[Root, Path]:
    root.path.mkdir(parents=True)
    root.director_prompt.write_text("m\n")
    root.editor_prompt.write_text("e\n")
    return root, make_workspace(tmp_path / "ws")


def _task(root: Root, workspace: Path, **fields: object) -> Task:
    task = Task(id="task-20260927T120000", goal="g", workspace=str(workspace), **fields)
    save(root, task)
    set_current(root, task.id)
    return task


def test_the_dry_scenario_reaches_done_in_four_ticks(env: tuple[Root, Path]):
    root, workspace = env
    runner = ScriptedRunner(read_jsonl(FIXTURES / "dry/director.jsonl"), read_jsonl(FIXTURES / "dry/worker.jsonl"))
    lines: list[str] = []
    task = loop.run("dry", workspace, root, Caps(), runner, echo=lines.append)
    assert (task.terminal, task.tick, round(task.cost_usd, 2)) == ("done", 4, 1.3)
    assert [(u.id, u.status, u.branch) for u in task.units] == [
        ("u-1", "passed", f"unit/{task.id}/u-1"), ("u-2", "passed", f"unit/{task.id}/u-2")]
    assert [line.split(":")[0] for line in lines[1:5]] == ["tick 1", "tick 2", "tick 3", "tick 4"]
    assert lines[-1].startswith("terminal: done") and load(root, task.id) == task
    assert list(root.clones_dir(task.id).iterdir()) == []
    branches = subprocess.run(["git", "branch", "--list", "unit/*"], cwd=workspace, capture_output=True, text=True).stdout
    assert branches.split() == [f"unit/{task.id}/u-1", f"unit/{task.id}/u-2"]
    verdicts = [e for e in director.read_log(root, task.id) if e["event"] == "verdict"]
    assert [v["passed_ids"] for v in verdicts] == [["p1", "p2"], ["p1", "p2"]]


def test_a_failing_unit_stays_pending_then_fails_after_two_attempts(env: tuple[Root, Path]):
    root, workspace = env
    task = _task(root, workspace)
    runner = ScriptedRunner([_reply({"units": [UNIT]})], [FAIL, FAIL])
    seen = []
    for _ in range(3):
        loop.run_tick(task, Caps(), root, runner)
        seen.append((task.units[0].status, task.units[0].attempts))
    assert seen == [("pending", 0), ("pending", 1), ("failed", 2)]
    assert ("[grade: p1 file_exists: the worker reported exit_code 1; nothing was graded; "
            "p2 exit_code: the worker reported exit_code 1; nothing was graded]") in task.units[0].summary


def test_an_uncommitted_write_is_not_delivered_and_cannot_pass(env: tuple[Root, Path], monkeypatch: pytest.MonkeyPatch):
    root, workspace = env
    graded = []
    real_grade = grade.grade
    monkeypatch.setattr(grade, "grade", lambda *a: graded.append(a) or real_grade(*a))
    task = _task(root, workspace)
    uncommitted = {**PASS, "commit": False}
    runner = ScriptedRunner([_reply({"units": [UNIT]}), _reply({"done": True})], [uncommitted, uncommitted])
    loop.run_tick(task, Caps(), root, runner)
    loop.run_tick(task, Caps(), root, runner)
    assert (task.units[0].status, task.units[0].attempts) == ("pending", 1)
    (verdict,) = [e for e in director.read_log(root, task.id) if e["event"] == "verdict"]
    assert (verdict["passed_ids"], verdict["ungradeable_ids"], verdict["passed"]) == ([], ["p1", "p2"], False)
    assert all("uncommitted changes in the clone: a.txt" in note for note in verdict["notes"].values())
    assert "uncommitted changes in the clone: a.txt" in task.units[0].summary
    loop.run_tick(task, Caps(), root, runner)
    loop.run_tick(task, Caps(), root, runner)
    assert (task.units[0].status, task.terminal, graded) == ("failed", None, [])


def test_a_status_claim_in_the_plan_does_not_pass_the_unit(env: tuple[Root, Path]):
    root, workspace = env
    task = _task(root, workspace)
    runner = ScriptedRunner([_reply({"units": [{**UNIT, "status": "passed"}]})], [FAIL])
    loop.run_tick(task, Caps(), root, runner)
    assert task.units[0].status == "pending"
    loop.run_tick(task, Caps(), root, runner)
    assert (task.units[0].status, task.units[0].attempts, task.terminal) == ("pending", 1, None)


def test_done_with_an_unverified_unit_does_not_end_the_task(env: tuple[Root, Path]):
    root, workspace = env
    failed = Unit("u-1", "write a.txt", [Predicate("file_exists", {"path": "a.txt"})], "failed", 2)
    task = _task(root, workspace, units=[failed])
    runner = ScriptedRunner([_reply({"done": True}) for _ in range(4)], [])
    for _ in range(3):
        loop.run_tick(task, Caps(max_replans=3), root, runner)
        assert task.terminal is None
    assert json.loads(runner.calls[1][1])["notes"] == ["not all units verified: u-1"]
    loop.run_tick(task, Caps(max_replans=3), root, runner)
    assert task.terminal == "interrupted" and task.question.startswith("The director said done 4 times")
    assert mailbox.open_path(root, task.id).exists()


def test_the_task_stops_at_max_usd_before_any_call(env: tuple[Root, Path]):
    root, workspace = env
    task = _task(root, workspace, cost_usd=10.0)
    runner = ScriptedRunner([], [])
    loop.run_tick(task, Caps(), root, runner)
    assert (task.terminal, task.stop_reason, runner.calls) == ("stopped", "max_usd: 10.00 >= 10.0", [])
    assert load(root, task.id).terminal == "stopped"


def test_the_task_stops_at_the_call_floor_without_a_call(env: tuple[Root, Path]):
    root, workspace = env
    task = _task(root, workspace, cost_usd=9.8)
    runner = ScriptedRunner([], [])
    loop.run_tick(task, Caps(), root, runner)
    assert (task.terminal, task.stop_reason, runner.calls) == (
        "stopped", "max_usd: remaining $0.20 below the $0.50 call floor", [])


def test_resume_waits_for_an_answer_then_hands_it_to_the_director(env: tuple[Root, Path]):
    root, workspace = env
    runner = ScriptedRunner([_reply({"question": "which file?"})], [])
    task = loop.run("g", workspace, root, Caps(), runner)
    assert task.terminal == "interrupted"
    assert loop.resume(root, Caps(), runner).terminal == "interrupted" and len(runner.calls) == 1
    path = mailbox.open_path(root, task.id)
    path.write_text(path.read_text() + "use a.txt\n")
    runner.director += [_reply({"units": [UNIT]}), _reply({"done": True})]
    runner.worker.append(PASS)
    task = loop.resume(root, Caps(), runner)
    assert task.terminal == "done" and task.question is None
    assert json.loads(runner.calls[1][1])["notes"] == ["The operator answered your question (which file?): use a.txt"]
    assert (root.mailbox_closed / f"{task.id}-answered.md").exists()


def test_an_extend_that_leaves_another_ceiling_binding_is_not_saved(env: tuple[Root, Path]):
    root, workspace = env
    task = _task(root, workspace, cost_usd=10.0, tick=30, terminal="stopped", stop_reason="max_usd: 10.00 >= 10.0")
    runner = ScriptedRunner([], [])
    task = loop.resume(root, Caps(), runner, extend_usd=5.0)
    assert (task.terminal, task.extra_usd, runner.calls) == ("stopped", 0.0, [])
    assert load(root, task.id).extra_usd == 0.0
    assert not [e for e in director.read_log(root, task.id) if e["event"] == "extend"]


def test_resume_refuses_while_another_process_holds_the_task_lock(env: tuple[Root, Path]):
    root, workspace = env
    task = _task(root, workspace, terminal="interrupted", question="q?")
    with (root.state_dir(task.id) / "lock").open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.write("4242\n")
        handle.flush()
        with pytest.raises(RuntimeError, match=rf"^task {task.id} is already running \(pid 4242\)$"):
            loop.resume(root, Caps(), ScriptedRunner([], []))
    assert loop.resume(root, Caps(), ScriptedRunner([], [])).terminal == "interrupted"


def test_run_holds_the_task_lock_while_it_drives(env: tuple[Root, Path]):
    root, workspace = env
    scripted, seen = ScriptedRunner([_reply({"question": "q?"})], []), []
    def runner(argv, stdin, cwd, timeout):
        with (root.state_dir(state.current(root).id) / "lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                seen.append("free")
            except BlockingIOError:
                seen.append("held")
        return scripted(argv, stdin, cwd, timeout)
    task = loop.run("g", workspace, root, Caps(), runner)
    assert seen == ["held"] and (root.state_dir(task.id) / "lock").read_text().strip() == str(os.getpid())
    with (root.state_dir(task.id) / "lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


DESCOPE_QUESTION = ("The director wants to descope u-2: not needed. "
                    "Answer `yes` to accept, anything else is sent back to the director.")


def _descope_asked(root: Root, workspace: Path, runner: ScriptedRunner) -> Task:
    units = [Unit("u-1", "write a.txt", [Predicate("file_exists", {"path": "a.txt"})], "passed", 1),
             Unit("u-2", "write b.txt", [Predicate("file_exists", {"path": "b.txt"})], "failed", 2)]
    task = _task(root, workspace, units=units)
    loop.run_tick(task, Caps(), root, runner)
    assert (task.terminal, task.question, [u.status for u in task.units]) == (
        "interrupted", DESCOPE_QUESTION, ["passed", "failed"])
    assert DESCOPE_QUESTION in mailbox.open_path(root, task.id).read_text()
    return task


def _answer(root: Root, task: Task, text: str) -> None:
    path = mailbox.open_path(root, task.id)
    path.write_text(path.read_text() + text)


def test_a_descope_waits_for_the_operator_and_yes_applies_it(env: tuple[Root, Path]):
    root, workspace = env
    runner = ScriptedRunner([_reply({"descope": ["u-2"], "reason": "not needed"}), _reply({"done": True})], [])
    task = _descope_asked(root, workspace, runner)
    assert loop.resume(root, Caps(), runner).terminal == "interrupted" and len(runner.calls) == 1
    _answer(root, task, "Yes, drop it\n")
    task = loop.resume(root, Caps(), runner)
    assert [u.status for u in task.units] == ["passed", "descoped"] and task.terminal == "done"
    assert json.loads(runner.calls[1][1])["notes"] == ["The operator accepted your descope of u-2."]


def test_a_descope_answered_otherwise_goes_back_to_the_director(env: tuple[Root, Path]):
    root, workspace = env
    runner = ScriptedRunner([_reply({"descope": ["u-2"], "reason": "not needed"}), _reply({"question": "how?"})], [])
    task = _descope_asked(root, workspace, runner)
    _answer(root, task, "yesterday's plan still stands; split it\n")
    task = loop.resume(root, Caps(), runner)
    assert [u.status for u in task.units] == ["passed", "failed"] and task.question == "how?"
    assert json.loads(runner.calls[1][1])["notes"] == [
        "The operator did not accept your descope of u-2: yesterday's plan still stands; split it"]


def test_extend_widens_a_stopped_task_and_abandon_is_final(env: tuple[Root, Path]):
    root, workspace = env
    caps = Caps(max_usd=0.5)
    runner = ScriptedRunner([_reply({"units": [UNIT]}, cost=0.6), _reply({"done": True})], [PASS])
    task = loop.run("g", workspace, root, caps, runner)
    assert (task.terminal, task.stop_reason) == ("stopped", "max_usd: 0.60 >= 0.5")
    assert loop.resume(root, caps, runner).terminal == "stopped" and len(runner.calls) == 1
    task = loop.resume(root, caps, runner, extend_usd=1.0)
    assert (task.terminal, task.stop_reason) == ("stopped", "max_usd: remaining $0.40 below the $0.50 call floor")
    assert loop.resume(root, caps, runner).terminal == "stopped" and len(runner.calls) == 2
    task = loop.resume(root, caps, runner, extend_usd=1.0)
    assert (task.terminal, task.extra_usd, round(task.cost_usd, 2)) == ("done", 2.0, 1.2)
    other = _task(root, workspace, terminal="interrupted", question="q?")
    mailbox.ask(root, other, "q?")
    task = loop.resume(root, caps, runner, abandon=True)
    assert (task.terminal, task.stop_reason) == ("stopped", "abandoned")
    assert (root.mailbox_closed / f"{task.id}-abandoned.md").exists()
    assert loop.resume(root, caps, runner, extend_ticks=5).stop_reason == "abandoned"


def test_a_unit_that_changes_nothing_cannot_pass_on_pre_existing_files(env: tuple[Root, Path]):
    root, workspace = env
    task = _task(root, workspace)
    unit = {"id": "u-1", "intent": "write README.md", "predicates": [
        {"kind": "file_exists", "args": {"path": "README.md"}}, {"kind": "exit_code", "args": {"code": 0}}]}
    idle = {"exit_code": 0, "result": "it was already there", "total_cost_usd": 0.5}
    runner = ScriptedRunner([_reply({"units": [unit]})], [idle, idle])
    for _ in range(2):
        loop.run_tick(task, Caps(), root, runner)
    assert (task.units[0].status, task.units[0].attempts) == ("pending", 1)
    (verdict,) = [e for e in director.read_log(root, task.id) if e["event"] == "verdict"]
    assert (verdict["passed_ids"], verdict["ungradeable_ids"], verdict["passed"]) == ([], ["p1", "p2"], False)
    assert all("nothing was delivered" in note for note in verdict["notes"].values())
    loop.run_tick(task, Caps(), root, runner)
    assert task.units[0].status == "failed"


def _interrupt(argv, stdin, cwd, timeout):
    raise KeyboardInterrupt


def test_an_interrupted_director_call_is_charged_and_saved_before_it_propagates(env: tuple[Root, Path]):
    root, workspace = env
    task = _task(root, workspace)
    with pytest.raises(KeyboardInterrupt):
        loop.run_tick(task, Caps(), root, _interrupt)
    saved = load(root, task.id)
    assert (saved.cost_usd, saved.terminal, saved.tick) == (2.0, None, 0)
    (event,) = [e for e in director.read_log(root, task.id) if e["event"] == "interrupted"]
    assert (event["seat"], event["charged_usd"]) == ("director", 2.0)


def test_an_interrupted_retry_charges_the_first_call_too(env: tuple[Root, Path]):
    root, workspace = env
    task = _task(root, workspace)
    replies = [RunResult(0, json.dumps(_reply({"nonsense": 1}, cost=0.3)), "")]
    def runner(argv, stdin, cwd, timeout):
        if replies:
            return replies.pop()
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        loop.run_tick(task, Caps(), root, runner)
    assert round(load(root, task.id).cost_usd, 2) == 2.3


def test_an_interrupted_worker_call_is_charged_with_its_attempt_and_resume_carries_it(env: tuple[Root, Path]):
    root, workspace = env
    task = _task(root, workspace, units=[Unit("u-1", "write a.txt", [Predicate("file_exists", {"path": "a.txt"})])])
    with pytest.raises(KeyboardInterrupt):
        loop.run_tick(task, Caps(), root, _interrupt)
    saved = load(root, task.id)
    assert (saved.cost_usd, saved.units[0].attempts, saved.units[0].status, saved.terminal) == (4.0, 1, "pending", None)
    runner = ScriptedRunner([_reply({"done": True})], [PASS])
    task = loop.resume(root, Caps(), runner)
    assert (task.terminal, round(task.cost_usd, 2), task.units[0].attempts) == ("done", 4.6, 2)


def test_an_interrupted_worker_call_with_little_left_is_charged_the_clipped_cap(env: tuple[Root, Path]):
    root, workspace = env
    task = _task(root, workspace, cost_usd=8.5,
                 units=[Unit("u-1", "write a.txt", [Predicate("file_exists", {"path": "a.txt"})])])
    with pytest.raises(KeyboardInterrupt):
        loop.run_tick(task, Caps(), root, _interrupt)
    assert load(root, task.id).cost_usd == 10.0


NO_EXIT_UNIT = {"id": "u-1", "intent": "write a.txt", "predicates": [{"kind": "file_exists", "args": {"path": "a.txt"}}]}


def _one_verdict(root: Root, task: Task) -> dict:
    (verdict,) = [e for e in director.read_log(root, task.id) if e["event"] == "verdict"]
    return verdict


def test_a_worker_reporting_exit_code_1_cannot_pass_even_when_every_predicate_holds(env: tuple[Root, Path]):
    root, workspace = env
    task = _task(root, workspace)
    unmet = {**PASS, "exit_code": 1, "result": "wrote a.txt but the intent is unmet"}
    runner = ScriptedRunner([_reply({"units": [NO_EXIT_UNIT]})], [unmet])
    loop.run_tick(task, Caps(), root, runner)
    loop.run_tick(task, Caps(), root, runner)
    assert (task.units[0].status, task.units[0].attempts) == ("pending", 1)
    verdict = _one_verdict(root, task)
    assert (verdict["passed_ids"], verdict["ungradeable_ids"], verdict["passed"]) == ([], ["p1"], False)
    assert verdict["notes"]["p1"] == "file_exists: the worker reported exit_code 1; nothing was graded"


def test_a_worker_with_no_exit_code_line_cannot_pass(env: tuple[Root, Path]):
    root, workspace = env
    task = _task(root, workspace)
    silent = {key: value for key, value in PASS.items() if key != "exit_code"}
    runner = ScriptedRunner([_reply({"units": [NO_EXIT_UNIT]})], [silent])
    loop.run_tick(task, Caps(), root, runner)
    loop.run_tick(task, Caps(), root, runner)
    assert (task.units[0].status, task.units[0].attempts) == ("pending", 1)
    verdict = _one_verdict(root, task)
    assert (verdict["ungradeable_ids"], verdict["passed"]) == (["p1"], False)
    assert verdict["notes"]["p1"] == "file_exists: the worker reported no exit_code line; nothing was graded"


def test_a_deletion_is_delivered_and_graded_in_the_clone(env: tuple[Root, Path]):
    root, workspace = env
    task = _task(root, workspace)
    unit = {"id": "u-1", "intent": "remove README.md", "predicates": [
        {"kind": "command", "args": {"cmd": "test ! -e README.md", "expect_exit": 0}}]}
    removal = {"delete": ["README.md"], "commit": True, "exit_code": 0, "result": "removed it", "total_cost_usd": 0.5}
    runner = ScriptedRunner([_reply({"units": [unit]})], [removal])
    loop.run_tick(task, Caps(), root, runner)
    loop.run_tick(task, Caps(), root, runner)
    assert (task.units[0].status, task.units[0].attempts) == ("passed", 1)
    verdict = _one_verdict(root, task)
    assert (verdict["passed_ids"], verdict["changed"]) == (["p1"], ["README.md"])


def test_exit_code_0_permits_grading_and_never_substitutes_for_it(env: tuple[Root, Path]):
    root, workspace = env
    task = _task(root, workspace)
    wrong = {**PASS, "write": {"b.txt": "not the file asked for\n"}}
    runner = ScriptedRunner([_reply({"units": [NO_EXIT_UNIT]})], [wrong, wrong])
    for _ in range(3):
        loop.run_tick(task, Caps(), root, runner)
    assert (task.units[0].status, task.units[0].attempts) == ("failed", 2)
    first, _ = [e for e in director.read_log(root, task.id) if e["event"] == "verdict"]
    assert (first["failed_ids"], first["ungradeable_ids"], first["passed"]) == (["p1"], [], False)
    assert first["notes"]["p1"] == "file_exists: missing: a.txt"
