"""Director: argv and seat cwd, mint-then-resume, decode, the one retry, and a status it cannot set."""

from __future__ import annotations

import json

import pytest

from protean import director
from protean.budget import Caps
from protean.dry import REPO, ScriptedRunner
from protean.runner import RunResult
from protean.state import Root, Task

UNIT = {"id": "u-2", "intent": "write b.txt", "predicates": [{"kind": "file_exists", "args": {"path": "b.txt"}}]}


def _reply(obj: object, cost: float = 0.25, session: str = "sess-1") -> dict:
    text = obj if isinstance(obj, str) else json.dumps(obj)
    return {"type": "result", "is_error": False, "session_id": session, "total_cost_usd": cost, "result": text}


@pytest.fixture
def seeded(root: Root) -> Root:
    root.path.mkdir(parents=True)
    root.director_prompt.write_text("# director prompt\n")
    return root


def test_first_call_mints_with_the_prompt_and_later_calls_resume(seeded: Root, task: Task):
    runner = ScriptedRunner([_reply({"units": [UNIT]}), _reply({"done": True})], [])
    first = director.plan(task, Caps(), seeded, runner)
    assert first.session_id == "sess-1" and [u.id for u in first.units] == ["u-2"] and first.cost_usd == 0.25
    argv, stdin, cwd, timeout = runner.calls[0]
    assert argv == [
        "claude", "-p", "--setting-sources", "", "--output-format", "json", "--max-budget-usd", "2.00",
        "--model", "claude-opus-5",
        "--permission-mode", "dontAsk", "--tools", "Read", "Grep", "Glob", "--allowedTools", "Read", "Grep", "Glob",
        "--add-dir", "/tmp/ws", "--system-prompt", "# director prompt\n",
    ]
    assert cwd == seeded.seat_dir(task.id) and cwd.is_dir() and timeout == 300
    view = json.loads(stdin)
    assert (view["goal"], view["units"][0]["id"], view["budget_left_usd"], view["notes"]) == ("make a.txt", "u1", 10.0, [])
    task.director_session = first.session_id
    assert director.plan(task, Caps(), seeded, runner).done
    argv2, _, cwd2, _ = runner.calls[1]
    assert argv2[-4:] == ["--resume", "sess-1", "--system-prompt", "# director prompt\n"] and cwd2 == cwd


def test_a_malformed_reply_is_retried_once_then_becomes_a_question(seeded: Root, task: Task):
    runner = ScriptedRunner([_reply("Let us start with a.txt."), _reply({"units": []}, cost=0.5)], [])
    reply = director.plan(task, Caps(), seeded, runner)
    assert len(runner.calls) == 2 and reply.cost_usd == 0.75 and not reply.units
    assert reply.question == "The director returned an invalid plan twice: units must be a non-empty list"
    assert "Your previous answer was rejected:\n- the reply holds no JSON object" in runner.calls[1][1]
    assert runner.calls[1][0][-4:-2] == ["--resume", "sess-1"]


def test_the_retry_recovers_a_misspelled_predicate(seeded: Root, task: Task):
    bad = {"units": [{**UNIT, "predicates": [{"kind": "exit_code", "args": {"expected": 0}}]}]}
    fenced = "Plan:\n```json\n" + json.dumps({"units": [UNIT]}) + "\n```"
    runner = ScriptedRunner([_reply(bad), _reply(fenced)], [])
    reply = director.plan(task, Caps(), seeded, runner)
    assert [u.id for u in reply.units] == ["u-2"] and reply.question is None
    assert "unit 'u-2': p1 exit_code: unknown arg 'expected'" in runner.calls[1][1]


def test_calls_are_clipped_to_what_is_left_and_no_retry_goes_below_the_floor(seeded: Root, task: Task):
    task.cost_usd = 9.0
    runner = ScriptedRunner([_reply("no plan here", cost=0.6)], [])
    reply = director.plan(task, Caps(), seeded, runner)
    argv = runner.calls[0][0]
    assert argv[argv.index("--max-budget-usd") + 1] == "1.00" and len(runner.calls) == 1
    assert (reply.stop, reply.errors, reply.kind) == (
        "max_usd: remaining $0.40 below the $0.50 call floor", ["the reply holds no JSON object"], "stopped")
    assert reply.cost_usd == 0.6 and reply.question is None


def test_a_status_carried_in_the_plan_is_ignored(seeded: Root, task: Task):
    claimed = {**UNIT, "status": "passed", "attempts": 3, "summary": "already done", "branch": "main"}
    reply = director.plan(task, Caps(), seeded, ScriptedRunner([_reply({"units": [claimed]})], []))
    (unit,) = reply.units
    assert (unit.status, unit.attempts, unit.summary, unit.branch) == ("pending", 0, "", None)


@pytest.mark.parametrize("stdout, timed_out, cost", [
    ("", True, 4.0),
    ('{"is_error": true, "subtype": "error_max_budget_usd", "total_cost_usd": 2.05}', False, 4.1),
    ("Error: not logged in", False, 4.0),
])
def test_timeouts_capped_calls_and_garbage_are_failures_whose_dollars_still_count(
    seeded: Root, task: Task, stdout: str, timed_out: bool, cost: float
):
    calls = []
    def runner(argv, stdin, cwd, timeout):
        calls.append(argv)
        return RunResult(-9 if timed_out else 1, stdout, "", timed_out)
    reply = director.plan(task, Caps(), seeded, runner)
    assert len(calls) == 2 and reply.question.startswith("The director returned an invalid plan twice")
    assert reply.cost_usd == pytest.approx(cost)


def test_a_call_with_no_receipt_is_charged_its_clipped_cap(seeded: Root, task: Task):
    task.cost_usd = 9.0
    reply = director.plan(task, Caps(), seeded, lambda *_: RunResult(-9, "", "", True))
    assert (reply.cost_usd, reply.kind) == (1.0, "stopped")


def test_the_view_carries_the_attempt_cap_the_prompt_names(task: Task):
    assert director.view(task, Caps(max_attempts_per_unit=3), [])["max_attempts_per_unit"] == 3
    prompt = (REPO / "brain" / "protean" / "director.md").read_text()
    assert "`max_attempts_per_unit`" in prompt and "fails twice" not in prompt
    assert "at least one unit has passed" in prompt


def test_the_prompt_says_the_operator_approves_every_descope():
    prompt = (REPO / "brain" / "protean" / "director.md").read_text()
    (descope_rule,) = [line for line in prompt.splitlines() if line.startswith('- `{"descope"')]
    assert descope_rule.endswith("The operator approves every descope first; the task pauses until they answer.")


@pytest.mark.parametrize("obj, error", [
    ({"units": [UNIT, UNIT]}, "id is already used"),
    ({"units": [{**UNIT, "id": "u1"}]}, "id is already used"),
    ({"units": [{**UNIT, "id": "../escape"}]}, "id must match"),
    ({"units": [{**UNIT, "predicates": []}]}, "a unit needs at least one predicate"),
    ({"units": [{**UNIT, "predicates": [{"kind": "file_exists"}]}]}, "predicates must be a list"),
    ({"done": False}, "done must be true"),
    ({"done": True, "question": "?"}, "exactly one of"),
    ({"descope": ["u-9"]}, "existing unit ids"),
    ({"question": "  "}, "non-empty string"),
])
def test_decode_rejects(task: Task, obj: dict, error: str):
    reply, errors = director.decode(json.dumps(obj), task)
    assert reply is None and any(error in e for e in errors), errors


def test_decode_accepts_each_reply_kind(task: Task):
    assert director.decode('{"question": "which?"}', task)[0].question == "which?"
    assert director.decode('Finished. {"done": true} Thanks.', task)[0].done
    descope = director.decode('{"descope": ["u1"], "reason": "not needed"}', task)[0]
    assert (descope.descope, descope.reason, descope.kind) == (["u1"], "not needed", "descope")


# live-2 (2026-09-27): the director twice ended a valid plan one `}` short; the decoder then took the
# first nested object that parsed (a unit) and reported "carried none", so the retry was told the wrong error.
TRUNCATED = '{"units": [{"id": "u-2", "intent": "write b.txt", "predicates": [{"kind": "file_exists", "args": {"path": "b.txt"}}]}]'


def test_a_plan_cut_off_before_its_closing_brackets_is_completed(task: Task):
    reply, errors = director.decode(TRUNCATED, task)
    assert errors == [] and [u.id for u in reply.units] == ["u-2"]
    reply, errors = director.decode(TRUNCATED[: TRUNCATED.rindex("}}]")] + "}}", task)  # two closers short
    assert errors == [] and reply.units[0].predicates[0].args == {"path": "b.txt"}
    assert director.decode('{"question": "which?', task)[0] is None  # cut inside a string stays unreadable


def test_a_broken_outer_object_names_its_parse_error_instead_of_a_nested_object(task: Task):
    broken = '{"units": [{"id": "u-2", "intent": "write b.txt", "predicates": []}] oops}'
    reply, errors = director.decode(broken, task)
    assert reply is None and "carried none" in errors[0] and "did not parse" in errors[0], errors


def test_pending_notes_cross_the_role_rename(root: Root):
    from protean.state import append_log
    for event in [{"to_manager": "stale"}, {"event": "manager"},
                  {"to_manager": "The operator answered"}, {"to_director": "retry"}]:
        append_log(root, "t", event)
    assert director.pending_notes(root, "t") == ["The operator answered", "retry"]
    append_log(root, "t", {"event": "director"})
    assert director.pending_notes(root, "t") == []


def _unit(uid: str, *needs: str) -> dict:
    return {**UNIT, "id": uid, "needs": list(needs)}


@pytest.mark.parametrize("units, error", [
    ([_unit("u-2", "u-9")], "unit 'u-2': needs 'u-9', which is no unit in the task or this plan"),
    ([_unit("u-2", "u-2")], "unit 'u-2': needs itself"),
    ([_unit("u-2", "u-3"), _unit("u-3", "u-4"), _unit("u-4", "u-2")], "unit 'u-2': needs form a cycle: u-2 -> u-3 -> u-4 -> u-2"),
    ([{**UNIT, "needs": "u1"}], "unit 'u-2': needs must be a list of unit ids"),
])
def test_decode_rejects_bad_needs(task: Task, units: list, error: str):
    reply, errors = director.decode(json.dumps({"units": units}), task)
    assert reply is None and error in errors, errors


def test_decode_takes_needs_on_the_task_and_later_in_the_same_plan(task: Task):
    reply, errors = director.decode(json.dumps({"units": [_unit("u-3", "u-2", "u1"), _unit("u-2")]}), task)
    assert errors == [] and [(u.id, u.needs) for u in reply.units] == [("u-3", ["u-2", "u1"]), ("u-2", [])]
    assert director.decode(json.dumps({"units": [UNIT]}), task)[0].units[0].needs == []


def test_the_view_shows_needs_and_the_prompt_documents_them(task: Task):
    task.units[0].needs = ["u0"]
    assert director.view(task, Caps(), [])["units"][0]["needs"] == ["u0"]
    prompt = (REPO / "brain" / "protean" / "director.md").read_text()
    assert '"needs"' in prompt and "`blocked`" in prompt


def test_decode_refuses_to_descope_a_passed_unit(task: Task):
    task.units[0].status, task.units[0].candidate, task.units[0].integrated = "passed", "abc", True
    reply, errors = director.decode('{"descope": ["u1"], "reason": "not needed"}', task)
    assert reply is None and "u1 has passed and cannot be descoped" in errors, errors


def test_decode_refuses_a_need_on_a_unit_that_passed_before_the_accepted_branch(task: Task):
    task.units[0].status = "passed"
    reply, errors = director.decode(json.dumps({"units": [_unit("u-2", "u1")]}), task)
    assert reply is None and errors == [
        "unit 'u-2': needs 'u1', which passed before the accepted branch existed and cannot be built on"], errors
    task.units[0].candidate, task.units[0].integrated = "abc", True
    assert director.decode(json.dumps({"units": [_unit("u-2", "u1")]}), task)[1] == []
