"""The live adapter against a stand-in binary: the argv, the scrub, the refusals, the one retry.

`the build specification (not in this mirror)` § Deliverable 1 — S1's invocation and decode halves, the
failure path and the containment paragraph. Order W2's DoD rows **K2** (the decode retry) and
**K1**'s argv clause, and the adapter half of **W9**'s three forced failures.

**Every case here is a shape on the wire, and no case spends money.** The adapter under test is
the shipping one — it builds the real argv, scrubs the real environment and spawns a real
process; only the process on the other end is `tests/cortex/fake_cli`. Two of the three failure
envelopes are not hand-authored at all: `fixtures/envelopes/live_refusal.json` and
`live_budget_exhausted.json` are order W1's captured bytes, so what is asserted is what the CLI
actually did at a refusal and at the dollar cap.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from protean import config
from pydantic import ValidationError

from protean.cortex.calls import (
    REFUSAL_CAP_EXCEEDED,
    CallRefusal,
    DelegatePayload,
    EscalatePayload,
    NodeCallDesk,
    ThinkPayload,
)
from protean.cortex.bodies import Body, BodyRefused
from protean.cortex.layer import build_live_layer
from protean.cortex.live.config import (
    CALLS_BLOCK,
    ENV_ALLOWED,
    CallCapExceeded,
    SeatConfigError,
)
from protean.cortex.live.invoke import (
    ADD_DIR_FLAG,
    ALLOWED_TOOLS_FLAG,
    BUDGET_FLAG,
    CAP_BUDGET,
    CAP_WALL,
    DISALLOWED_TOOLS_FLAG,
    EFFORT_FLAG,
    MESSAGE_LIMIT,
    MODEL_FLAG,
    OUTPUT_FORMAT_FLAG,
    PERMISSION_MODE_FLAG,
    PRINT_FLAG,
    REASON_SPAWN,
    REASON_TIMEOUT,
    RESUMED_AS_NEW,
    SCHEMA_FLAG,
    SEAT_CWD_DIRNAME,
    SETTING_SOURCES_FLAG,
    SYSTEM_PROMPT_FLAG,
    TOOLS_FLAG,
    VERSION_FLAG,
    _message_of,
    names_a_path,
    spawn_scaffold_dir,
)
from protean.cortex.live.audit import OWN_SCAFFOLD_MARKERS
from protean.cortex.live.kinds import EGRESS_REMOTE
from protean.cortex.live.schema import schema_argument
from protean.cortex.live.session import SESSION_MINT_FLAG, SESSION_RESUME_FLAG
from protean.runtime.errors import SeatUnavailable
from protean.runtime.seat import (
    OUTCOME_DECODE_RETRY,
    OUTCOME_OK,
    OUTCOME_UNAVAILABLE,
    SeatCallFacts,
    SeatDecodeError,
    decode_seat_result,
)
from protean.state.calls import BODY_PRINT, BODY_TERMINAL
from protean.state.enums import CallType, Escalation, NodeName, Tier
from protean.state.primitives import GoalItem
from protean.state.calls import NodeCall
from protean.state.seat_calls import SeatCallRecord
from protean.state.seats import SeatEnvelope, WaveMember
from protean.state.workspace import (
    DirectorRequest,
    ManagerRequest,
    Workspace,
)
from tests.cortex import fake_cli
from tests.cortex.conftest import (
    SHIM_DIR,
    arm_the_shim,
    director_request,
    manager_request,
    one_goal,
    one_goal_workspace,
    seeded_live_root,
)

TASK = "task-live"
UNIT = "u1"
GOAL = "g1"


def _workspace() -> Workspace:
    return one_goal_workspace(TASK, tick=1, goal=one_goal(GOAL, text="do the thing"))


def request_for(tier: Tier, workspace_path: str = "") -> object:
    """The per-seat request. **Two seats** — a dispatch is a call type and has no seat request
    (`the build specification (not in this mirror)` § Deliverable 3); its member requests are order W8's.
    """
    if tier is Tier.DIRECTOR:
        return director_request(_workspace())
    if tier is Tier.MANAGER:
        return manager_request(_workspace())
    raise AssertionError(f"{tier} is not a seat and takes no seat request")


@pytest.fixture(scope="module")
def director_call(tmp_path_factory: pytest.TempPathFactory):
    """One structured director call on the stand-in, once for the module, and what it was handed.

    Seven cases read a different facet of this **one** recording — the envelope handed back, the
    recorded `num_turns`, the throwaway cwd, the request on stdin, the assembled system prompt,
    the call facts and the seats' own farm and cwd — and not one of them mutates the root, the
    recording or the book, so the spawn and its seeding are paid once rather than seven times.
    `test_the_child_sees_five_variables_and_cannot_find_the_binary` stays out: it `setenv`s before
    the call, so the call has to happen inside its own test.

    The `MonkeyPatch` context is held open for the module's lifetime on purpose — the adapter
    resolves its binary off the **parent's** `PATH` (`config.resolved_binary()`), which the
    consumers below still read through `seat.binary()`.
    """
    base = tmp_path_factory.mktemp("director")
    with pytest.MonkeyPatch.context() as patch:
        root, binaries = seeded_live_root(
            base, patch, [fake_cli.envelope(fake_cli.director_result())]
        )
        seat = fake_cli.live_seat(root)
        seat.sessions.open_task(TASK)
        request = request_for(Tier.DIRECTOR)
        envelope = seat(Tier.DIRECTOR, request)
        yield SimpleNamespace(
            seat=seat, binaries=binaries, root=root, request=request, envelope=envelope
        )


@pytest.fixture()
def live(tmp_path: Path, monkeypatch):
    """A shipping `LiveSeat` whose binary is the stand-in, and the directory it records into."""

    def _build(
        responses=(),
        *,
        exit_codes=(),
        sleep_seconds=None,
        workspace_path="",
        retries=1,
        reject_resume=False,
        spawn_child_seconds=None,
    ):
        root, binaries = seeded_live_root(
            tmp_path,
            monkeypatch,
            responses,
            exit_codes=exit_codes,
            sleep_seconds=sleep_seconds,
            reject_resume=reject_resume,
            spawn_child_seconds=spawn_child_seconds,
        )
        seat = fake_cli.live_seat(
            root, workspace_path=workspace_path, decode_retries=retries
        )
        seat.sessions.open_task(TASK)
        return seat, binaries

    return _build


# --------------------------------------------------------------------------------------
# S1's invocation half: the argv, the cwd, the environment
# --------------------------------------------------------------------------------------


def test_a_structured_success_comes_back_as_received(director_call) -> None:
    """"The adapter's job ends at the envelope" — parsed, not amended (folded: S-17)."""
    envelope, binaries = director_call.envelope, director_call.binaries

    assert isinstance(envelope, SeatEnvelope)
    raw = json.loads((binaries / "response-1.json").read_text(encoding="utf-8"))
    assert envelope.result == raw["result"], "the result string is the CLI's, unedited"
    assert envelope.model_extra["subtype"] == "success", "extras preserved, not dropped"
    assert envelope.model_extra["session_id"] == raw["session_id"]


@pytest.mark.parametrize("tier", [Tier.DIRECTOR, Tier.MANAGER])
def test_no_tools_tier_carries_no_add_dir_and_the_probed_tools_flag(live, tier) -> None:
    """K1: "the argv the adapter recorded carries no `--add-dir`" (folded: S-6, D5-9)."""
    result = fake_cli.director_result() if tier is Tier.DIRECTOR else fake_cli.planner_result(
        UNIT, GOAL
    )
    seat, binaries = live([fake_cli.envelope(result)], workspace_path="/tmp/should-not-appear")
    seat(tier, request_for(tier))

    argv = fake_cli.argv_of(binaries)
    assert "--add-dir" not in argv
    assert "--allowedTools" not in argv
    assert "--permission-mode" not in argv
    assert argv[argv.index("--tools") + 1] == ""


#: The one real `--tools ""` probe, driven once through the shipping adapter with the real seat
#: prefix and a real request on stdin (dispatch-5 ledger D5-9). It is the receipt row K1's
#: fourth clause closes on, and no case below spends a second call to re-take it.
TOOLS_FLAG_CAPTURE = Path(__file__).resolve().parent / "captures" / "tools-flag-probe.json"


@pytest.mark.parametrize("tier", ["director", "planner"])
def test_a_real_no_tools_call_recorded_the_flag_no_add_dir_and_its_turn_count(tier: str) -> None:
    """K1's fourth clause **as S-38 restated it**, over the argv the adapter actually recorded.

    Toollessness is proven by the *mechanism* — `--tools ""` on the recorded argv and no
    `--add-dir` — and `num_turns` is **recorded rather than bounded**: a structured call is a
    forced tool call (`stop_reason: tool_use`), so it is never one turn, and the two real calls
    in this capture came back at 2 and 3 (dispatch-5 ledger D5-10, ruled S-38).
    """
    capture = json.loads(TOOLS_FLAG_CAPTURE.read_text(encoding="utf-8"))
    call = next(item for item in capture["calls"] if item["tier"] == tier)
    assert len(call["facts"]) == 1, "one invocation, one SeatCallFacts"
    fact = call["facts"][0]
    argv = fact["argv"]
    print(f"    [K1] {tier}: --tools {argv[argv.index('--tools') + 1]!r} · "
          f"--add-dir {'--add-dir' in argv} · num_turns {fact['num_turns']} · "
          f"stop_reason {call['stop_reason']!r}")

    assert argv[argv.index("--tools") + 1] == "", 'the recorded argv carries --tools ""'
    assert "--add-dir" not in argv
    assert call["structured"] is True and call["stop_reason"] == "tool_use"
    assert isinstance(fact["num_turns"], int), "`num_turns` is recorded on the facts"
    assert fact["num_turns"] >= 1
    assert fact["model"] == ("claude-fable-5-1" if tier == "director" else "claude-opus-5")


#: The live containment receipt, taken once by `tests/cortex/probe_containment.py` on
#: `claude-haiku-4-5-20251001`. The cases below **read** it; nothing here spends.
CONTAINMENT_CAPTURE = Path(__file__).resolve().parent / "captures" / "containment-dontask.json"


@pytest.fixture(scope="module")
def containment_receipt() -> dict:
    return json.loads(CONTAINMENT_CAPTURE.read_text(encoding="utf-8"))


def test_the_containment_receipt_was_taken_under_the_shipping_argv(containment_receipt) -> None:
    """The receipt is only worth anything if the call that produced it was the shipping one."""
    argv = containment_receipt["argv"]
    assert argv[0] == "/usr/bin/sandbox-exec" and argv[1] == "-p"
    assert argv[2] == containment_receipt["sandbox_profile"]
    assert argv[2].startswith("(version 1)(allow default)(deny file-write* ")
    for tree in containment_receipt["deny_write"]:
        assert f'(subpath "{tree}")' in argv[2]
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--tools") + 1] == "Bash,Read,Edit,Write,Grep,Glob"
    assert containment_receipt["cli_version"].startswith("2.1.263")


def test_the_containment_receipt_names_the_unlisted_calls_in_permission_denials(
    containment_receipt,
) -> None:
    """The S-44 half, measured on the executor seat: the allow-list binds and says what it refused.

    Under `auto` the same session shape returned `permission_denials: []` with thirteen tools
    used outside the list (D14-8). Under `dontAsk` beside `--tools`, every unlisted call is here.
    """
    denied = [one["tool_input"]["command"] for one in containment_receipt["permission_denials"]]
    print(f"    [C2] executor denials: {denied}")
    assert "ls /" in denied, "the unlisted `ls` was refused"
    brain_probe = containment_receipt["probe_paths_after"]["brain"]["path"]
    assert f"touch {brain_probe}" in denied, "the out-of-tree `touch` was refused"
    assert not [one for one in denied if one.startswith("echo ")], (
        "`echo ok` ran: the containment binds the session, it does not brick it"
    )
    assert [one for one in denied if one.startswith("python3 ")], (
        "measured, and pinned because the executor's real work leans on it: `Bash(python:*)` "
        "does not license `python3` (dispatch ledger S1-6)"
    )


def test_the_containment_receipt_shows_the_kernel_refusing_the_write(containment_receipt) -> None:
    """The S-45 half: a write the permission layer let through still cannot reach a denied tree.

    The receipt's own shape is recorded in the dispatch ledger (S1-6): `python3` was refused at
    the permission layer, so the write that reached the filesystem was the `Write` fallback the
    probe's prompt carries. What is asserted is the fact the row turns on — a write into a denied
    tree came back `operation not permitted` — not the tool that attempted it.
    """
    body = json.dumps(containment_receipt)
    workload_probe = containment_receipt["probe_paths_after"]["workload"]["path"]
    assert "operation not permitted" in body.lower()
    assert workload_probe in body
    print(f"    [C2] executor kernel refusal recorded for {workload_probe}")


def test_neither_probe_path_exists_after_the_containment_receipt(containment_receipt) -> None:
    """Both readings: what the probe recorded at the time, and what is on disk right now."""
    for tree in ("brain", "workload"):
        recorded = containment_receipt["probe_paths_after"][tree]
        assert recorded["exists"] is False
        assert not Path(recorded["path"]).exists(), "and it is still not there"


def test_the_adapter_records_num_turns_off_the_wire_and_invents_none(director_call) -> None:
    """The recorded number is the CLI's own: the fake answers 2 and the facts carry 2."""
    assert director_call.seat.calls()[0].num_turns == 2


def test_no_seat_carries_a_workspace_an_allow_list_or_a_tool_at_all(live, tmp_path: Path) -> None:
    """Re-based by build A.1: the tool-bearing seat is **gone**, and nothing replaced it here.

    Build 1's executor seat carried `--add-dir`, `--permission-mode dontAsk` and a six-name tool
    set. A.1 deletes it: the cortex holds two tool-less seats, and the work is done by a wave of
    subagents the manager dispatches. **A subagent's model, effort, tools, `add_dir`, prompt and
    both caps come from a kind block, and kind blocks, their container, their containment floor
    and the ceiling that bounds them are build A.1.i's** (§ Deliverable 2, § Out of scope) — so
    the allow-list assertions above have no subject in A.1 and are not restated against a seat
    that has no tools. What is asserted instead is the claim that replaced them.
    """
    workspace = tmp_path / "clone"
    workspace.mkdir()
    seat, binaries = live(
        [fake_cli.envelope(fake_cli.planner_result(UNIT, GOAL))], workspace_path=str(workspace)
    )
    seat(Tier.MANAGER, request_for(Tier.MANAGER, str(workspace)))

    argv = fake_cli.argv_of(binaries)
    print(f"    [A.1] manager argv tools: {argv[argv.index('--tools') + 1]!r}")
    assert argv[argv.index("--tools") + 1] == "", "a seat is tool-less by load-time refusal"
    assert "--add-dir" not in argv, "no seat reaches a directory"
    assert "Task" not in argv, "no seat spawns a child"
    for tier in config.TIERS:
        block = seat.config.tier(tier)
        assert block.tools == "" and block.add_dir is False


@pytest.mark.parametrize("tier", [Tier.DIRECTOR, Tier.MANAGER])
def test_every_spawn_goes_through_the_sandbox_and_the_cli_never_sees_the_wrapper(
    live, tmp_path: Path, tier
) -> None:
    """S-45, on **both seats**: the wrapper is the argv's head and the CLI's own argv is intact.

    Both seats are tool-less and both are wrapped — one code path, so a seat that ever gained a
    tool cannot gain it outside the sandbox — and the fake CLI's `$@` proves the wrapper is
    consumed by `sandbox-exec` rather than handed on to the binary. **Tier three's containment
    is build A.1.i's** (§ Out of scope): there is no kind block and no spawn path to wrap yet.
    """
    workspace = tmp_path / "clone"
    workspace.mkdir()
    result = {
        Tier.DIRECTOR: fake_cli.director_result(),
        Tier.MANAGER: fake_cli.planner_result(UNIT, GOAL),
    }[tier]
    seat, binaries = live([fake_cli.envelope(result)], workspace_path=str(workspace))
    seat(tier, request_for(tier, str(workspace)))

    sandbox = seat.config.sandbox
    recorded = list(seat.calls()[0].argv)
    print(f"    [S-45] {tier}: {recorded[0]} {recorded[1]} {recorded[2][:60]}…")
    assert recorded[:3] == sandbox.wrap([])
    assert recorded[2] == sandbox.profile()
    assert "file-write*" in recorded[2] and str(seat.config.root.resolve()) in recorded[2]
    seen = fake_cli.argv_of(binaries)
    assert sandbox.binary not in seen and recorded[2] not in seen
    assert seen == recorded[4:], "the CLI got its own argv, and only its own"


def test_a_binary_the_wrapper_cannot_exec_is_still_a_spawn_refusal(live) -> None:
    """The wrapper moved this failure surface and the classification is restored (S-45).

    Before the wrapper a missing CLI raised `OSError` in the parent. Wrapped, the parent's spawn
    succeeds and `sandbox-exec` exits non-zero instead — but no CLI process ever existed, which
    is exactly what `REASON_SPAWN` means and what leaves the session handle unconfirmed.

    Also owns what `test_a_spawn_that_never_happened_leaves_the_session_unopened` proved (removed
    as a strict subset): the rule `session_flag()` states that a call which never left the adapter
    strands nothing — the `SESSION_MINT_FLAG` assertion below.
    """
    seat, binaries = live([fake_cli.envelope(fake_cli.director_result())])
    fake_cli.unspawnable(binaries)
    with pytest.raises(SeatUnavailable) as raised:
        seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))
    assert raised.value.reason == REASON_SPAWN
    assert "execvp()" in seat.calls()[0].error
    assert seat.sessions.session_flag(Tier.DIRECTOR)[0] == SESSION_MINT_FLAG, (
        "a call that never reached the CLI strands no session"
    )


def test_a_no_tools_tier_runs_in_an_empty_runtime_owned_directory(director_call) -> None:
    """"cwd an empty, runtime-owned directory, no `--add-dir`" (folded: S-6, as
    `the build specification (not in this mirror)` § Scaffold clause 2(a) amends it for the seats): the
    seat's per-task directory, empty; "cannot see the repo" is carried by the seats' `--tools ""`."""
    cwd = Path(fake_cli.cwd_of(director_call.binaries))
    assert cwd.is_dir()
    assert list(cwd.iterdir()) == []


def test_the_request_model_travels_on_stdin_as_sent(director_call) -> None:
    sent = json.loads(fake_cli.stdin_of(director_call.binaries))
    assert sent == director_call.request.model_dump(mode="json")


def test_the_system_prompt_is_the_two_seed_files_concatenated_verbatim(director_call) -> None:
    """folded: S-4 — no templating; a seat call's prompt is recoverable from the checkpoint, a
    dispatch member's from the receipt's recorded `argv` (A.2 § Deliverable 7).

    Folded in from `test_a_seat_calls_prefix_is_still_the_cortex_node_md_first`: the seat half is
    unchanged by A.1's call types — build 2's **order**, the cortex `NODE.md` first and the seat's
    own prefix file second, asserted beside the new one (the call-type order is
    `test_the_assembled_prefix_puts_the_calling_nodes_node_md_first`'s, below).
    """
    seat, binaries = director_call.seat, director_call.binaries
    argv = fake_cli.argv_of(binaries)
    sent = argv[argv.index("--system-prompt") + 1]
    root = seat.config.root
    node_md = (root / "nodes" / "cortex" / "NODE.md").read_text(encoding="utf-8")
    seat_md = (root / "seats" / "director.md").read_text(encoding="utf-8")
    assert node_md in sent
    assert seat_md in sent
    assert sent.startswith(node_md), "the cortex NODE.md is the FIRST half"
    assert sent.endswith(seat_md), "and the seat's own prefix file is the second"


def test_the_child_sees_five_variables_and_cannot_find_the_binary(live, monkeypatch) -> None:
    """The containment, captured from **inside** the call rather than from the caller's side.

    Five since S-37 (`USER` joined the four), which is why the assertion is written against
    `ENV_ALLOWED` itself rather than a list restated here.
    """
    monkeypatch.setenv("RIG_TOKEN", "secret")
    monkeypatch.setenv("PROTEAN_BRAIN", "/somewhere")
    seat, binaries = live([fake_cli.envelope(fake_cli.director_result())])
    seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))

    environment = fake_cli.environment_of(binaries)
    assert set(environment) <= set(ENV_ALLOWED) | {"PWD", "SHLVL", "_"}, environment
    assert "RIG_TOKEN" not in environment and "PROTEAN_BRAIN" not in environment
    assert str(binaries) not in environment["PATH"], "the binary's own directory is excluded"


def test_the_first_call_mints_and_the_second_resumes(live) -> None:
    """*fresh per task, cached within task*, as it reaches the wire.

    **One two-call state, read three ways** — the three claims are sequential and overlap
    nowhere, so they are three readings of one recording rather than three recordings.

    Folded in from `test_calls_are_cleared_at_the_top_of_every_port_call`: a boundary read is
    this call's invocations, never a running total.

    Folded in from `test_the_ordinal_counter_is_untouched_for_the_seats_and_the_calls_blocks`
    (folded: S-i53) — **the two keys sit on the two paths and neither loses a count**. A decode
    retry and a resumed session share one id, so the seats keep the shared counter that
    `invocations()` reads; only a spawn re-keys, because that counter's read-modify-write races
    the moment four members run at once against one directory.
    """
    responses = [fake_cli.envelope(fake_cli.director_result())] * 2
    seat, binaries = live(responses)
    seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))
    seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))

    first, second = fake_cli.argv_of(binaries, 1), fake_cli.argv_of(binaries, 2)
    assert "--session-id" in first and "--resume" not in first
    assert "--resume" in second and "--session-id" not in second
    assert first[first.index("--session-id") + 1] == second[second.index("--resume") + 1]
    assert len(seat.calls()) == 1, "a boundary read is this call's invocations, not a total"
    assert fake_cli.invocations(binaries) == 2, "two calls, two ordinals"
    assert fake_cli.argv_of(binaries, 1) and fake_cli.argv_of(binaries, 2)


def test_the_call_facts_carry_what_the_record_will_need(director_call) -> None:
    """folded: S-18 — the facts leave through `calls()`; order W3 writes the record."""
    seat, binaries, request = director_call.seat, director_call.binaries, director_call.request

    facts = seat.calls()
    assert len(facts) == 1
    fact = facts[0]
    assert fact.tier == "director"
    sandbox = seat.config.sandbox
    assert fact.argv[0] == sandbox.binary, "the wrapper is what the parent spawns (S-45)"
    assert list(fact.argv[:3]) == sandbox.wrap([])
    assert fact.argv[3] == str(seat.binary()), "spawned by absolute path, after the scrub"
    assert list(fact.argv[4:]) == fake_cli.argv_of(binaries)
    assert fact.cli_version == "0.0.0-fake (stand-in)"
    assert fact.session_handle == seat.sessions.handle(Tier.DIRECTOR)
    assert fact.model == "claude-fable-5-1" and fact.effort == "high"
    assert fact.request == request.model_dump(mode="json")
    assert fact.outcome == OUTCOME_OK
    assert fact.usage["cache_creation_input_tokens"] == 40000
    assert fact.num_turns == 2
    assert fact.wall_seconds >= 0


# --------------------------------------------------------------------------------------
# Decision 11: an error is not an envelope
# --------------------------------------------------------------------------------------


def _the_message_is_the_clis_own_words(payload: dict, refusal: SeatUnavailable) -> None:
    """What the mailbox item will hold: the CLI's own words, unedited — up to the bound.

    W1's captured refusal is 406 characters, so this is also where `MESSAGE_LIMIT` shows: the
    words are the CLI's, and the length is the adapter's (nothing unbounded reaches a mailbox
    interrupt a human has to read).
    """
    assert refusal.message == payload["result"].strip()[:MESSAGE_LIMIT]


def _the_at_cap_body_is_a_refusal_and_never_a_decode_failure(
    payload: dict, refusal: SeatUnavailable
) -> None:
    """The at-cap shape is a refusal by name, with the CLI's own sentence and its exit code."""
    assert "Reached maximum budget" in refusal.message
    assert refusal.exit_code == 1


@pytest.mark.parametrize(
    "name,exit_code,tier,message_check",
    [
        ("live_refusal.json", 1, Tier.DIRECTOR, _the_message_is_the_clis_own_words),
        (
            "live_budget_exhausted.json",
            1,
            Tier.MANAGER,
            _the_at_cap_body_is_a_refusal_and_never_a_decode_failure,
        ),
        ("live_rate_limit.json", 0, Tier.DIRECTOR, None),
    ],
    ids=["refusal", "budget_exhausted", "rate_limit"],
)
def test_an_error_response_raises_seat_unavailable_by_name(
    live, load_envelope, name: str, exit_code: int, tier: Tier, message_check
):
    """Row W9's three shapes: a non-zero exit, an `is_error` body, and a rate limit.

    The `message_check` column is where the two folded cases went: each drove one of these very
    fixtures a second time to add one message assertion, so the assertion travels beside its own
    row instead. `tier` is a column for the same reason — the at-cap case reads it on the
    manager.
    """
    payload = load_envelope(name)
    # W1 measured it: at the cap an envelope comes back with **no `result` key at all** — the
    # pre-assert the folded at-cap case brought with it, checked before the call as it was there.
    if name == "live_budget_exhausted.json":
        assert "result" not in payload
    seat, _ = live([payload], exit_codes=[exit_code])
    with pytest.raises(SeatUnavailable) as raised:
        seat(tier, request_for(tier))

    assert raised.value.tier == str(tier)
    assert seat.calls()[0].outcome == OUTCOME_UNAVAILABLE
    assert len(seat.calls()) == 1, "a refusal is not retried; it is reported"
    if message_check is not None:
        message_check(payload, raised.value)


def test_a_non_zero_exit_with_no_json_at_all_still_refuses_by_name(live) -> None:
    seat, _ = live(["not json, a crash message"], exit_codes=[2])
    with pytest.raises(SeatUnavailable) as raised:
        seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))
    assert raised.value.exit_code == 2


def test_a_call_that_outruns_its_wall_cap_is_killed_and_refuses(live) -> None:
    """folded: S-32 — `timeout_seconds` is the bound that holds; the adapter kills the process."""
    seat, _ = live([fake_cli.envelope(fake_cli.director_result())], sleep_seconds=5)
    seat.config.tiers["director"].__class__  # the seed's value is 300s; narrow it for the test
    import dataclasses

    narrowed = dataclasses.replace(seat.config.tier("director"), timeout_seconds=0.2)
    seat.config.tiers["director"] = narrowed  # type: ignore[index]
    with pytest.raises(SeatUnavailable) as raised:
        seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))
    assert "wall cap" in raised.value.reason


def test_no_validation_error_ever_escapes_the_adapter(live) -> None:
    """folded: S-7 — the classification happens on raw stdout, before `SeatEnvelope`."""
    broken = fake_cli.envelope(fake_cli.director_result())
    del broken["usage"]["cache_read_input_tokens"]
    seat, _ = live([broken, broken], retries=1)
    with pytest.raises(SeatDecodeError):
        seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))


# --------------------------------------------------------------------------------------
# Row K2: one retry, and one only
# --------------------------------------------------------------------------------------


def _decode_failures() -> list[tuple[str, dict]]:
    """K2's three shapes: a validation error, a wrong `stop_reason`, an unparseable `result`."""
    validation = fake_cli.envelope({"narrative": "no unit_id, so the model refuses it"})
    stop_reason = fake_cli.envelope(fake_cli.director_result(), stop_reason="end_turn")
    unparseable = fake_cli.envelope(fake_cli.director_result())
    unparseable["result"] = "{not json"
    return [
        ("validation", validation),
        ("stop_reason", stop_reason),
        ("unparseable", unparseable),
    ]


@pytest.mark.parametrize("name,bad", _decode_failures(), ids=[n for n, _ in _decode_failures()])
def test_a_decode_failure_retries_exactly_once_then_raises(live, name: str, bad: dict) -> None:
    """K2: two invocations, the first marked `decode_retry`, then `SeatDecodeError`."""
    tier = Tier.MANAGER if name == "validation" else Tier.DIRECTOR
    seat, binaries = live([bad, bad])
    with pytest.raises(SeatDecodeError) as raised:
        seat(tier, request_for(tier))

    assert fake_cli.invocations(binaries) == 2, "exactly one retry, and exactly one"
    facts = seat.calls()
    assert [fact.outcome for fact in facts] == [OUTCOME_DECODE_RETRY, OUTCOME_UNAVAILABLE]
    assert str(tier) in str(raised.value), "the error names the tier"
    assert facts[0].error and facts[1].error


def test_the_retry_is_a_second_invocation_on_the_same_resumed_session(live) -> None:
    """folded: S-8 — same session, the validation error carried on stdin."""
    bad = fake_cli.envelope(fake_cli.director_result(), stop_reason="end_turn")
    good = fake_cli.envelope(fake_cli.director_result())
    seat, binaries = live([bad, good])
    seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))

    first, second = fake_cli.argv_of(binaries, 1), fake_cli.argv_of(binaries, 2)
    assert "--session-id" in first
    assert "--resume" in second, "the retry joins the session the first call minted"
    assert second[second.index("--resume") + 1] == first[first.index("--session-id") + 1]
    retry_stdin = fake_cli.stdin_of(binaries, 2)
    assert "did not validate" in retry_stdin and "end_turn" in retry_stdin


def test_a_retry_that_succeeds_returns_the_envelope_and_records_two_calls(live) -> None:
    bad = fake_cli.envelope(fake_cli.director_result(), stop_reason="end_turn")
    good = fake_cli.envelope(fake_cli.director_result())
    seat, binaries = live([bad, good])
    envelope = seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))

    assert isinstance(envelope, SeatEnvelope)
    assert fake_cli.invocations(binaries) == 2
    assert [fact.outcome for fact in seat.calls()] == [OUTCOME_DECODE_RETRY, OUTCOME_OK]
    assert decode_seat_result(Tier.DIRECTOR, envelope, 1).tick == 1


def test_the_adapter_never_lets_a_pydantic_error_out(live) -> None:
    """The public failure surface is two names, and `ValidationError` is not one of them."""
    bad = fake_cli.envelope({"narrative": "no unit_id"})
    seat, _ = live([bad, bad])
    with pytest.raises((SeatDecodeError, SeatUnavailable)) as raised:
        seat(Tier.MANAGER, request_for(Tier.MANAGER))
    assert not isinstance(raised.value, ValidationError)
    assert not isinstance(raised.value.__cause__, ValidationError)


# --------------------------------------------------------------------------------------
# A restored handle is opened-but-unconfirmed: one fallback from `--resume` to `--session-id`
# --------------------------------------------------------------------------------------

#: What a checkpoint carries into a resumed process. Both seats are minted at task open and one
#: seat runs per tick, so a crash before a seat's first invocation checkpoints a handle whose
#: session the CLI was never asked to create.
CARRIED = {"director": "carried-d", "manager": "carried-m"}


def test_a_resume_the_cli_accepts_is_exactly_one_invocation(live) -> None:
    """The unchanged half: a session that exists is joined, and nothing else happens.

    Row W2: a resume in a new process reuses the checkpoint's handles, no `--session-id`.
    """
    seat, binaries = live([fake_cli.envelope(fake_cli.director_result())])
    seat.sessions.restore(TASK, dict(CARRIED))
    seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))

    argv = fake_cli.argv_of(binaries)
    assert fake_cli.invocations(binaries) == 1, "no fallback where none is needed"
    assert "--session-id" not in argv
    assert argv[argv.index("--resume") + 1] == CARRIED["director"]
    assert seat.calls()[0].error == "", "nothing to record: the resume was accepted"
    assert seat.sessions.is_unconfirmed(Tier.DIRECTOR) is False


def test_a_rejected_resume_after_a_restore_is_re_sent_once_under_the_same_uuid(live) -> None:
    """The fix: the CLI never created this session, so the same handle is *minted* instead."""
    good = fake_cli.envelope(fake_cli.director_result())
    seat, binaries = live([good, good], reject_resume=True)
    seat.sessions.restore(TASK, dict(CARRIED))
    envelope = seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))

    assert isinstance(envelope, SeatEnvelope), "the tick gets its answer"
    assert fake_cli.invocations(binaries) == 2, "one fallback, and one only"
    first, second = fake_cli.argv_of(binaries, 1), fake_cli.argv_of(binaries, 2)
    print(f"    [H1] 1: --resume {first[first.index('--resume') + 1]} · "
          f"2: --session-id {second[second.index('--session-id') + 1]}")
    assert "--session-id" not in first
    assert first[first.index("--resume") + 1] == CARRIED["director"]
    assert "--resume" not in second, "the retry mints rather than resuming again"
    assert second[second.index(SESSION_MINT_FLAG) + 1] == CARRIED["director"], "same uuid"


def test_the_fallback_is_recorded_on_the_facts_and_the_outcome_stays_ok(live) -> None:
    """One `SeatCallFacts` for the invocation, carrying the marker and the answering argv."""
    good = fake_cli.envelope(fake_cli.director_result())
    seat, _ = live([good, good], reject_resume=True)
    seat.sessions.restore(TASK, dict(CARRIED))
    seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))

    facts = seat.calls()
    assert len(facts) == 1
    print(f"    [H1] facts: outcome={facts[0].outcome!r} error={facts[0].error!r}")
    assert facts[0].outcome == OUTCOME_OK, "the call succeeded; the fallback is not a failure"
    assert facts[0].error.startswith(RESUMED_AS_NEW)
    assert CARRIED["director"] in facts[0].error
    assert facts[0].session_handle == CARRIED["director"]
    assert SESSION_MINT_FLAG in facts[0].argv, "the argv that answered is the one recorded"


def test_the_fallback_opens_the_tier_so_the_next_call_resumes_what_it_minted(live) -> None:
    """"and mark the tier opened": the minted session is the one the next call joins."""
    good = fake_cli.envelope(fake_cli.director_result())
    seat, binaries = live([good] * 3, reject_resume=True)
    seat.sessions.restore(TASK, dict(CARRIED))
    seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))
    # The fallback created the session, so the CLI stops refusing the resume.
    (binaries / "reject_resume").unlink()
    seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))

    third = fake_cli.argv_of(binaries, 3)
    assert fake_cli.invocations(binaries) == 3
    assert seat.sessions.is_unconfirmed(Tier.DIRECTOR) is False
    assert third[third.index("--resume") + 1] == CARRIED["director"]
    assert seat.calls()[0].error == "", "the second port call did not fall back again"


def test_a_confirmed_handle_never_falls_back_and_its_refusal_is_reported(
    live, load_envelope
) -> None:
    """The bound on the fallback: only the **first** invocation of a restored tier.

    Once an invocation has run against a handle, a non-zero exit is the CLI's answer about the
    call, not evidence that the session is missing — so it is refused by name rather than
    re-sent, and no second process is spawned.
    """
    good = fake_cli.envelope(fake_cli.director_result())
    seat, binaries = live([good, load_envelope("live_refusal.json")], exit_codes=[0, 1])
    seat.sessions.restore(TASK, dict(CARRIED))
    seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))

    with pytest.raises(SeatUnavailable) as raised:
        seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))

    assert raised.value.exit_code == 1
    assert fake_cli.invocations(binaries) == 2, "no third call: the handle was confirmed"
    assert RESUMED_AS_NEW not in seat.calls()[0].error


# --------------------------------------------------------------------------------------
# Every spawn-level failure is classified, and no message is unbounded
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,text",
    [("missing", "No such file or directory"), ("permission", "Permission denied")],
)
def test_a_binary_that_cannot_be_spawned_refuses_by_name(live, kind: str, text: str) -> None:
    """`OSError` at the spawn is `SeatUnavailable`, so decision 11's path applies to it too."""
    seat, binaries = live([fake_cli.envelope(fake_cli.director_result())])
    fake_cli.unspawnable(binaries, kind)

    with pytest.raises(SeatUnavailable) as raised:
        seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))

    print(f"    [H2] {kind}: {raised.value.reason} — {raised.value.message}")
    assert raised.value.reason == REASON_SPAWN
    assert text in raised.value.message, "the OS error text, which is all there is to say"
    assert raised.value.exit_code is None, "no process ran, so there is no exit code"
    assert fake_cli.invocations(binaries) == 0
    facts = seat.calls()
    assert len(facts) == 1 and facts[0].outcome == OUTCOME_UNAVAILABLE
    assert REASON_SPAWN in facts[0].error


def test_no_refusal_message_is_longer_than_the_bound(live) -> None:
    """A ten-kilobyte error body reaches the mailbox interrupt as 400 characters."""
    body = fake_cli.envelope(fake_cli.director_result())
    body["is_error"] = True
    body["result"] = "x" * 10_000
    seat, _ = live([body], exit_codes=[1])

    with pytest.raises(SeatUnavailable) as raised:
        seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))

    print(f"    [H2] 10 kB body → message of {len(raised.value.message)} chars")
    assert len(raised.value.message) == MESSAGE_LIMIT == 400


@pytest.mark.parametrize(
    "parsed",
    [
        {"errors": ["y" * 10_000]},
        {"result": "z" * 10_000},
        {"subtype": "w" * 10_000},
    ],
    ids=["errors", "result", "subtype"],
)
def test_every_branch_of_the_message_reader_is_capped(parsed: dict) -> None:
    """All three shapes `_message_of` reads, held to the one bound."""
    assert len(_message_of(parsed)) == MESSAGE_LIMIT


# --------------------------------------------------------------------------------------
# The timeout kill reaches the process group
# --------------------------------------------------------------------------------------


def test_the_timeout_kill_reaches_the_whole_process_group(live) -> None:
    """A tool the seat started cannot outlive the call that started it.

    `subprocess.run(timeout=)` kills the direct child only, which would leave `uv`, `pytest` or
    `git` running against the clone after the seat call has been declared unavailable. The fake
    stands in for that: it spawns a sleeping grandchild, records its pid and never exits.
    """
    seat, binaries = live(
        [fake_cli.envelope(fake_cli.director_result())],
        sleep_seconds=30,
        spawn_child_seconds=30,
    )
    seat.config.tiers["director"] = dataclasses.replace(  # type: ignore[index]
        seat.config.tier("director"), timeout_seconds=0.3
    )

    with pytest.raises(SeatUnavailable) as raised:
        seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))
    assert raised.value.reason == REASON_TIMEOUT

    pid = fake_cli.grandchild_pid(binaries)
    deadline = time.monotonic() + 5.0
    alive = True
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            alive = False
            break
        time.sleep(0.05)
    print(f"    [H3] grandchild pid {pid} alive after the timeout: {alive}")
    assert alive is False, "the grandchild outlived the kill: the group was not killed"


# --------------------------------------------------------------------------------------
# The two `calls:` blocks take the seats' containment whole (row G10, folded: S-A70)
# --------------------------------------------------------------------------------------

#: The calling node each fixture below asks from. Two different nodes on purpose: the assembled
#: prefix's first half is the **calling node's** `NODE.md`, so a single node could not tell that
#: apart from a constant.
CALL_NODES = {CallType.THINK: NodeName.HIPPOCAMPUS, CallType.ESCALATE: NodeName.THALAMUS}

#: What each block's addressee may legally return, under the narrowed schema (no `tick`, no
#: `emitter` — the runtime fills both back).
CALL_ANSWERS = {
    CallType.THINK: {"answer": "the citation is stale", "confidence": 0.4, "cited_ids": []},
    CallType.ESCALATE: {"answer": "re-plan the unit", "proposed": []},
}


def call_payload(call_type: CallType):
    if call_type is CallType.THINK:
        return ThinkPayload(question="is the citation stale?", context="tick 1")
    return EscalatePayload(concern="the unit stack is empty", proposal="re-plan")


def node_call(seat, call_type: CallType, node: NodeName | None = None):
    """One C1 `NodeCall`, built through the desk's own constructor rather than by hand."""
    desk = NodeCallDesk(port=seat, task=TASK, tick=1)
    return desk.build_call(node or CALL_NODES[call_type], call_type, call_payload(call_type))


@pytest.mark.parametrize("call_type", [CallType.THINK, CallType.ESCALATE])
def test_a_calls_block_is_spawned_under_the_seats_containment_whole(live, call_type) -> None:
    """G10's containment half: the same wrapper, scrub, PATH exclusion and tool-lessness.

    Nothing here is a second code path — the block is `TIER_KEYS` exactly, so the adapter reads
    it exactly as it reads a seat's.
    """
    seat, binaries = live([fake_cli.envelope(CALL_ANSWERS[call_type])])
    envelope = seat(call_type, node_call(seat, call_type))

    assert isinstance(envelope, SeatEnvelope)
    sandbox = seat.config.sandbox
    recorded = list(seat.calls()[0].argv)
    print(f"    [G10] {call_type}: {recorded[0]} {recorded[1]} {recorded[2][:52]}…")
    assert recorded[:3] == sandbox.wrap([]), "the sandbox wrapper is the argv's head"
    assert recorded[2] == sandbox.profile() and "file-write*" in recorded[2]
    seen = fake_cli.argv_of(binaries)
    assert seen == recorded[4:], "and the CLI got its own argv, wrapper consumed"
    assert seen[seen.index("--tools") + 1] == "", "tool-less by load-time refusal"
    assert "--add-dir" not in seen and "--allowedTools" not in seen
    assert "--permission-mode" not in seen, "nothing to grant, so the flag is omitted"
    assert "Task" not in seen, "no `Task` in the resolved tool set — the runtime spawns"


@pytest.mark.parametrize("call_type", [CallType.THINK, CallType.ESCALATE])
def test_a_calls_block_child_path_cannot_resolve_the_binary(live, call_type) -> None:
    """The **positive** assertion row G10 names, on the built child `PATH`."""
    import shutil as shutil_

    seat, binaries = live([fake_cli.envelope(CALL_ANSWERS[call_type])])
    seat(call_type, node_call(seat, call_type))

    built = seat.config.child_path()
    print(f"    [G10] which({seat.config.binary}) on the child PATH: "
          f"{shutil_.which(seat.config.binary, path=built)}")
    assert shutil_.which(seat.config.binary, path=built) is None
    environment = fake_cli.environment_of(binaries)
    assert set(environment) <= set(ENV_ALLOWED) | {"PWD", "SHLVL", "_"}, environment
    assert str(binaries) not in environment["PATH"], "the binary's own directory is excluded"
    assert Path(fake_cli.cwd_of(binaries)).is_dir()
    assert list(Path(fake_cli.cwd_of(binaries)).iterdir()) == [], "a throwaway empty cwd"


@pytest.mark.parametrize("call_type", [CallType.THINK, CallType.ESCALATE])
def test_the_assembled_prefix_puts_the_calling_nodes_node_md_first(live, call_type) -> None:
    """"the calling node's `NODE.md` first" — the ORDER, not just the presence (folded: S-A66).

    Not the cortex `NODE.md`: the question belongs to the node, so the node's contract is what
    frames it, and a body that substituted a different first half would change the result while
    passing a file-level comparison (§ Deliverable 5).
    """
    seat, binaries = live([fake_cli.envelope(CALL_ANSWERS[call_type])])
    node = CALL_NODES[call_type]
    seat(call_type, node_call(seat, call_type))

    argv = fake_cli.argv_of(binaries)
    sent = argv[argv.index("--system-prompt") + 1]
    root = seat.config.root
    node_md = (root / "nodes" / str(node) / "NODE.md").read_text(encoding="utf-8")
    prefix = (root / "seats" / "calls" / f"{call_type}.md").read_text(encoding="utf-8")
    cortex_md = (root / "nodes" / "cortex" / "NODE.md").read_text(encoding="utf-8")

    print(f"    [G10] {call_type}: first half is {node}/NODE.md, second is calls/{call_type}.md")
    assert sent.startswith(node_md), "the calling node's NODE.md is the FIRST half"
    assert sent.endswith(prefix), "and the call-type prefix file is the second"
    assert sent.index(node_md) < sent.index(prefix), "in that order"
    assert not sent.startswith(cortex_md), "not the cortex NODE.md — the question is the node's"


# The seat half's own order — the cortex `NODE.md` first, then `seats/<tier>.md` — is folded into
# `test_the_system_prompt_is_the_two_seed_files_concatenated_verbatim` above, which reads the same
# assembled prefix off the same recording.


def test_a_call_type_prefix_with_no_calling_node_refuses_rather_than_guessing(live) -> None:
    """The first half is a fact of the call, not of the addressee — so it is never defaulted."""
    seat, _ = live([fake_cli.envelope(CALL_ANSWERS[CallType.THINK])])
    with pytest.raises(SeatConfigError) as raised:
        seat.system_prompt(CallType.THINK)
    assert "CALLING node" in str(raised.value)


@pytest.mark.parametrize("call_type", [CallType.THINK, CallType.ESCALATE])
def test_a_call_type_is_session_less_and_mints_a_fresh_handle_every_time(live, call_type):
    """folded: S-A31 — mint, discard, checkpoint nothing. `seat_sessions` is keyed by tier."""
    seat, binaries = live([fake_cli.envelope(CALL_ANSWERS[call_type])] * 2)
    seat(call_type, node_call(seat, call_type))
    seat(call_type, node_call(seat, call_type))

    first, second = fake_cli.argv_of(binaries, 1), fake_cli.argv_of(binaries, 2)
    handles = [
        first[first.index(SESSION_MINT_FLAG) + 1],
        second[second.index(SESSION_MINT_FLAG) + 1],
    ]
    print(f"    [S-A31] two cold handles: {handles[0][:8]}… {handles[1][:8]}…")
    assert SESSION_RESUME_FLAG not in first and SESSION_RESUME_FLAG not in second
    assert handles[0] != handles[1], "a fresh --session-id per invocation, then discarded"
    assert str(call_type) not in seat.sessions.for_task(TASK), "no entry in the book"
    assert sorted(seat.sessions.for_task(TASK)) == sorted(config.TIERS)


@pytest.mark.parametrize("call_type", [CallType.DELEGATE, CallType.DISPATCH])
def test_delegate_and_dispatch_reach_no_block_and_therefore_no_process(live, call_type):
    """"no A.1 fixture creates a tier-three process at all" — there is nothing to spawn with.

    **Re-based by A.1.i's route row R13**: the refusal named a kind block as a future build's when
    this case was written, and now names the landed `kinds:` container and the resolver that reads
    it. What the case asserts is unchanged — this root defines no kind, so the addressee resolves to
    no block and no process is created.
    """
    seat, binaries = live([fake_cli.envelope(CALL_ANSWERS[CallType.THINK])])
    with pytest.raises(SeatConfigError) as raised:
        seat(call_type, node_call(seat, CallType.THINK))
    message = str(raised.value)
    assert CALLS_BLOCK in message and f"kinds.{call_type}.<kind>" in message
    assert fake_cli.invocations(binaries) == 0, "no process was ever spawned"


# --------------------------------------------------------------------------------------
# A call that crosses one of its own caps: no envelope, a refusal to the calling node
# --------------------------------------------------------------------------------------


def test_an_at_cap_call_fabricates_no_envelope_and_raises_the_cap_class(
    live, load_envelope
) -> None:
    """Row G10's last clause, on the CLI's own at-cap bytes (order W1's capture).

    § Resolutions D5-8: `cap_exceeded` is raised where the cap is enforced — here, beside the
    `calls:` block that owns it — rather than type-classified in `protean.cortex.calls`. A seat
    at the same envelope still raises `SeatUnavailable`, because a fault on a seat call ends the
    task and a fault on an advisory call does not.
    """
    payload = load_envelope("live_budget_exhausted.json")
    assert "result" not in payload, "the CLI returns no result at all at the cap"
    seat, _ = live([payload], exit_codes=[1])
    with pytest.raises(CallCapExceeded) as raised:
        seat(CallType.THINK, node_call(seat, CallType.THINK))

    print(f"    [G10] {raised.value}")
    assert raised.value.cap == CAP_BUDGET
    assert raised.value.limit == seat.config.call(CallType.THINK).max_call_usd
    assert raised.value.reason == REFUSAL_CAP_EXCEEDED
    assert not isinstance(raised.value, SeatUnavailable), "it is not a stop"
    assert [fact.outcome for fact in seat.calls()] == [OUTCOME_UNAVAILABLE]
    assert "Reached maximum budget" in seat.calls()[0].error


def test_a_call_that_outruns_its_own_wall_cap_raises_the_cap_class_too(live) -> None:
    """Both caps, one class: `timeout_seconds` is the bound that holds when the dollar cap cannot."""
    seat, _ = live([fake_cli.envelope(CALL_ANSWERS[CallType.THINK])], sleep_seconds=5)
    seat.config.calls["think"] = dataclasses.replace(  # type: ignore[index]
        seat.config.call(CallType.THINK), timeout_seconds=0.2
    )
    with pytest.raises(CallCapExceeded) as raised:
        seat(CallType.THINK, node_call(seat, CallType.THINK))
    assert raised.value.cap == CAP_WALL and raised.value.reason == REFUSAL_CAP_EXCEEDED


def test_the_at_cap_refusal_reaches_the_calling_node_and_the_tick_carries_on(
    live, load_envelope
) -> None:
    """"returning a refusal to the calling node" — through the desk's public `refuse()` seam.

    The class is carried on the fault by the site that enforced the cap, which is what
    `NodeCallDesk.refuse()` is public for; the desk records it and the node proceeds without an
    answer. No `SeatEnvelope` was constructed anywhere on this path.
    """
    seat, _ = live([load_envelope("live_budget_exhausted.json")], exit_codes=[1])
    desk = NodeCallDesk(port=seat, task=TASK, tick=1)
    call = desk.build_call(NodeName.HIPPOCAMPUS, CallType.THINK, call_payload(CallType.THINK))

    try:
        envelope = seat(call.addressee, call)
    except CallCapExceeded as crossed:
        envelope = None
        answer = desk.refuse(call, crossed.reason, detail=str(crossed))

    print(f"    [G10] {answer.reason}: {answer.detail[:72]}")
    assert envelope is None, "no envelope was fabricated"
    assert isinstance(answer, CallRefusal) and answer.reason == REFUSAL_CAP_EXCEEDED
    assert desk.records[-1].refused and desk.records[-1].envelope is None
    assert desk.calls_for(NodeName.HIPPOCAMPUS)[0].call.call_number == 1


# --------------------------------------------------------------------------------------
# The two bodies run under the same containment, by construction (row G13, folded: A1-8)
# --------------------------------------------------------------------------------------

#: The flags this module names for the `claude -p` body, transcribed from the module's own
#: constants rather than restated. Row G13's bounded negative is a **set difference** against
#: this: "no flag outside the named `-p` set is added". It is deliberately not a whole-argv
#: equality — the interactive flag list is the part § Named assumptions 1 leaves unfixed, and
#: asserting one would be a claim this build cannot make (folded: S-A86).
NAMED_PRINT_FLAGS = frozenset(
    {
        PRINT_FLAG,
        SETTING_SOURCES_FLAG,
        OUTPUT_FORMAT_FLAG,
        SCHEMA_FLAG,
        SYSTEM_PROMPT_FLAG,
        MODEL_FLAG,
        EFFORT_FLAG,
        PERMISSION_MODE_FLAG,
        ALLOWED_TOOLS_FLAG,
        DISALLOWED_TOOLS_FLAG,
        TOOLS_FLAG,
        ADD_DIR_FLAG,
        BUDGET_FLAG,
        VERSION_FLAG,
        SESSION_MINT_FLAG,
        SESSION_RESUME_FLAG,
    }
)



@pytest.fixture()
def bodied(tmp_path: Path, monkeypatch):
    """A `LiveSeat` whose `runtime.body` is the one named — and, on a second call, the **same**
    root and the same stand-in binary under the other body.

    One root on purpose: the sandbox profile names the brain root, so two roots would differ by
    a path and "the same wrapper" could not be asserted at all. Flipping the key on one seed is
    also what "on the same state" means — the body is the only thing that moved.
    """
    seeded = {}

    def _build(body: str, responses=(), *, handed=None, again: bool = False):
        if not again:
            seeded["root"], seeded["bin"] = seeded_live_root(
                tmp_path, monkeypatch, responses
            )
        fake_cli.select_body(seeded["root"], body)
        seat = fake_cli.live_seat(seeded["root"])
        if handed is not None:
            seat.body = handed
        seat.sessions.open_task(TASK)
        return seat, seeded["bin"], seeded["root"]

    return _build


def test_the_terminal_body_records_the_same_wrapper_environment_and_tool_set(bodied) -> None:
    """Row G13's three identities **and its bounded negative**, on one recorded state, read off
    what each child actually saw.

    Not a whole-argv equality: the three the row names — the sandbox wrapper, the five-name
    environment and the resolved tool set — and then, folded in from
    `test_the_terminal_body_adds_no_flag_outside_the_named_print_set`, the bounded negative as a
    **set difference**: no flag outside the named `-p` set is added, and the print flag is the
    whole difference.
    """
    answer = fake_cli.envelope(fake_cli.planner_result(UNIT, GOAL))
    printed, binaries, _ = bodied(BODY_PRINT, [answer, answer])
    printed(Tier.MANAGER, request_for(Tier.MANAGER))
    terminal, _, _ = bodied(BODY_TERMINAL, again=True)
    terminal(Tier.MANAGER, request_for(Tier.MANAGER))

    print_argv, terminal_argv = list(printed.calls()[0].argv), list(terminal.calls()[0].argv)
    print(f"    [G13] wrapper: {terminal_argv[:2]} … profile {len(terminal_argv[2])} bytes")

    # 1. the same sandbox wrapper — the binary, the profile flag and the profile itself
    assert print_argv[:3] == terminal_argv[:3]
    assert terminal_argv[:3] == terminal.config.sandbox.wrap([])
    assert "file-write*" in terminal_argv[2]

    # 2. the same five-name environment, captured from INSIDE each call
    print_env = fake_cli.environment_of(binaries, 1)
    terminal_env = fake_cli.environment_of(binaries, 2)
    scrubbed = {name: terminal_env.get(name) for name in ENV_ALLOWED}
    print(f"    [G13] environment: {sorted(scrubbed)}")
    assert scrubbed == {name: print_env.get(name) for name in ENV_ALLOWED}
    assert set(terminal_env) <= set(ENV_ALLOWED) | {"PWD", "SHLVL", "_"}, terminal_env

    # 3. the same resolved tool set
    seen = fake_cli.argv_of(binaries, 2)
    assert seen[seen.index(TOOLS_FLAG) + 1] == ""
    assert ADD_DIR_FLAG not in seen and "Task" not in seen
    assert (
        terminal.config.tier(Tier.MANAGER).tools_argument()
        == printed.config.tier(Tier.MANAGER).tools_argument()
    )

    # 4. the bounded negative, as a set difference against the named `-p` set
    print_flags = fake_cli.flags_of(fake_cli.argv_of(binaries, 1))
    terminal_flags = fake_cli.flags_of(fake_cli.argv_of(binaries, 2))
    added = terminal_flags - print_flags
    print(f"    [G13] added: {sorted(added)}; dropped: {sorted(print_flags - terminal_flags)}")
    assert added == set(), "no flag outside the named `-p` set is added"
    assert terminal_flags <= NAMED_PRINT_FLAGS
    assert print_flags - terminal_flags == {PRINT_FLAG}, "the print flag is the whole difference"
    assert fake_cli.argv_of(binaries, 2)[0] != PRINT_FLAG


def test_the_terminal_body_mints_its_handle_through_the_same_book(bodied) -> None:
    """"the same … session handles": a runtime-launched session is the book's, like the other."""
    answer = fake_cli.envelope(fake_cli.planner_result(UNIT, GOAL))
    terminal, binaries, _ = bodied(BODY_TERMINAL, [answer, answer])
    terminal(Tier.MANAGER, request_for(Tier.MANAGER))
    terminal(Tier.MANAGER, request_for(Tier.MANAGER))

    first, second = fake_cli.argv_of(binaries, 1), fake_cli.argv_of(binaries, 2)
    assert SESSION_MINT_FLAG in first and SESSION_RESUME_FLAG in second
    minted, resumed = first.index(SESSION_MINT_FLAG), second.index(SESSION_RESUME_FLAG)
    assert first[minted + 1] == second[resumed + 1]
    assert terminal.sessions.minted_tasks == [TASK]


@pytest.mark.parametrize("call_type", [CallType.THINK, CallType.ESCALATE])
def test_the_key_reaches_the_two_seats_and_a_calls_block_still_runs_under_print(
    bodied, call_type
) -> None:
    """"It applies to the two cortex seats only" — the cheap calls keep the `-p` body."""
    terminal, binaries, _ = bodied(BODY_TERMINAL, [fake_cli.envelope(CALL_ANSWERS[call_type])])
    terminal(call_type, node_call(terminal, call_type))

    argv = fake_cli.argv_of(binaries)
    print(f"    [G13] {call_type} under runtime.body=terminal: argv[0]={argv[0]!r}")
    assert argv[0] == PRINT_FLAG, "a `calls:` block is not a seat and keeps the print body"
    assert terminal.body_of(call_type).name == BODY_PRINT
    assert terminal.body_of(Tier.DIRECTOR).name == BODY_TERMINAL


def test_a_body_the_runtime_did_not_launch_is_refused_before_a_handle_is_minted(
    bodied, tmp_path: Path, monkeypatch
) -> None:
    """Row G13's negative, with the recording shim in front of it and its log at zero bytes.

    The shim is `tests/shim/claude`, the same one M21's harness uses: the log is created
    **empty before the run**, so "zero bytes" is a read and not an absence (that module's
    control fires it on purpose and proves an invocation would fill it).

    The addressee is a **call type** on purpose: its handle is minted inside the call by
    `call_session()`, so "no session handle was minted" is a fact about this call rather than
    about a task that was already open.
    """
    attached = Body(name=BODY_TERMINAL, runtime_launched=False)
    seat, binaries, _ = bodied(
        BODY_TERMINAL, [fake_cli.envelope(CALL_ANSWERS[CallType.THINK])], handed=attached
    )
    # Armed **after** the root is built, so the shim sits in front of the stand-in the fixture
    # just put on `PATH`: a spawn that should never happen lands in this log, not in a recording.
    log = arm_the_shim(monkeypatch, tmp_path / "invocations.txt")
    seat.sessions.close_task()

    with pytest.raises(BodyRefused) as raised:
        seat(CallType.THINK, node_call(seat, CallType.THINK))

    print(f"    [G13] {raised.value}")
    assert BODY_TERMINAL in str(raised.value)
    assert "before any session handle is minted" in str(raised.value)
    assert log.stat().st_size == 0, f"the shim was invoked: {log.read_text(encoding='utf-8')}"
    assert fake_cli.invocations(binaries) == 0, "no process was spawned either"
    assert seat.calls() == (), "no facts, so no handle was ever recorded"
    assert seat.sessions.handles == {}, "and the book holds none"


def test_a_seat_call_under_an_unlaunched_body_leaves_its_session_unopened(bodied) -> None:
    """The same refusal on the seat path: nothing ran, so the handle is still unopened."""
    attached = Body(name=BODY_TERMINAL, runtime_launched=False)
    seat, binaries, _ = bodied(
        BODY_TERMINAL, [fake_cli.envelope(fake_cli.director_result())], handed=attached
    )
    with pytest.raises(BodyRefused):
        seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))

    assert fake_cli.invocations(binaries) == 0
    assert seat.calls() == ()
    assert seat.sessions.session_flag(Tier.DIRECTOR)[0] == SESSION_MINT_FLAG


# --------------------------------------------------------------------------------------
# A.1.i § Deliverable 3 — the spawn: the argv as it runs, and the two pre-process refusals
#
# Rows G4 and G5 (a) and (b). Every case drives the **shipping** adapter against the stand-in on a
# fixture kind root: one port instance per spawn, constructed with the resolved kind block, the
# workspace the test hands it and nothing else. G5's (c) `REASON_NO_KIND` and (d)
# `REASON_NO_WORKSPACE` are raised from the desk and are order W4's.
# --------------------------------------------------------------------------------------

SPAWN_TASK = "task-spawn"
SPAWN_TICK = 1
DISPATCH_KIND = "fixture_one"
DELEGATE_KIND = "fixture_two"

#: **Row G4's named flag set, as the CLI itself sees it** — built from this module's own flag
#: constants rather than re-spelled, so a flag that is ever renamed cannot pass this row by
#: agreeing with a second copy of its old name. The set equality below is what makes "**and no flag
#: outside it**" a check rather than a hope; `--add-dir` is absent for a kind that declares
#: `add_dir: false`, which is the one member of the set a block may decline.
SPAWN_FLAGS: set[str] = {
    PRINT_FLAG,
    SETTING_SOURCES_FLAG,
    SESSION_MINT_FLAG,
    MODEL_FLAG,
    EFFORT_FLAG,
    OUTPUT_FORMAT_FLAG,
    SCHEMA_FLAG,
    SYSTEM_PROMPT_FLAG,
    PERMISSION_MODE_FLAG,
    ALLOWED_TOOLS_FLAG,
    DISALLOWED_TOOLS_FLAG,
    TOOLS_FLAG,
    ADD_DIR_FLAG,
    BUDGET_FLAG,
}


def spawn_answer(kind_class: str) -> dict:
    """What each fixture kind's addressee may legally return, under the narrowed schema."""
    if kind_class == str(CallType.DISPATCH):
        return fake_cli.executor_result(UNIT)
    return {"kind": DELEGATE_KIND, "verdict": "it is stale", "information": "read it", "cited_ids": []}


def member_request(**overrides) -> dict:
    """A `dispatch` member's payload — `WaveMember`'s three fields, dumped as the wave sends it."""
    member = WaveMember(kind=DISPATCH_KIND, unit_id=UNIT, admitted_ref="admitted-1")
    return {**member.model_dump(mode="json"), **overrides}


def delegate_request(seat, **overrides) -> dict:
    """A `delegate` call's payload — the landed C1 `NodeCall` shape, built through the desk."""
    desk = NodeCallDesk(port=seat, task=SPAWN_TASK, tick=SPAWN_TICK)
    call = desk.build_call(
        NodeName.HIPPOCAMPUS,
        CallType.DELEGATE,
        DelegatePayload(kind=DELEGATE_KIND, question="is the citation stale?"),
    )
    return {**call.model_dump(mode="json"), **overrides}


def _with_bin_links(root: Path, names: list[str]) -> None:
    """Give a fixture root a link farm to build, by mutating its loaded payload.

    `seed_live_root()` empties `runtime.bin_links` so the stand-in needs no farm at all; the farm's
    **location** is row G4's clause, so one case puts a name back on the landed
    `tests/cortex/test_live_config.py` precedent rather than adding a seed.
    """
    seats = root / "seats.yaml"
    payload = yaml.safe_load(seats.read_text(encoding="utf-8"))
    payload["runtime"]["bin_links"] = names
    seats.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _spawn_world(
    base: Path,
    patch,
    kind_class: str = "dispatch",
    name: str = DISPATCH_KIND,
    *,
    bin_links=(),
    members=(),
) -> SimpleNamespace:
    """One **spawn instance** over a fixture kind root, and the stand-in it records into.

    The `evidence=` entry is § Deliverable 7's fixture-`spawn_writable` clause (folded: S-i37): under
    the inverted per-spawn profile the stand-in writes its argv, stdin, cwd and env files beside
    `$0`, so a row that closes on those files would otherwise be closing on files the kernel refused
    to let it write (D5-5).
    """
    binaries = fake_cli.install(
        base / "bin",
        answer=fake_cli.envelope(spawn_answer(kind_class)),
        members=members,
    )
    fake_cli.on_path(patch, binaries)
    root = fake_cli.seed_kinds_root(base / "brain", evidence=binaries)
    if bin_links:
        _with_bin_links(root, list(bin_links))
    workspace = (base / "clone").resolve()
    workspace.mkdir(exist_ok=True)
    seat = fake_cli.spawn_seat(
        root, kind_class, name, workspace=workspace, task=SPAWN_TASK, tick=SPAWN_TICK
    )
    return SimpleNamespace(
        seat=seat,
        binaries=binaries,
        root=root,
        workspace=workspace,
        scaffold=spawn_scaffold_dir(root, SPAWN_TASK, SPAWN_TICK),
    )


@pytest.fixture()
def spawning(tmp_path: Path, monkeypatch):
    """`_spawn_world()`, per test, for the cases that need their own root or their own answer."""

    def _build(kind_class: str = "dispatch", name: str = DISPATCH_KIND, *, bin_links=(), members=()):
        return _spawn_world(
            tmp_path, monkeypatch, kind_class, name, bin_links=bin_links, members=members
        )

    return _build


@pytest.fixture(scope="module")
def dispatch_spawn(tmp_path_factory: pytest.TempPathFactory):
    """One legal dispatch spawn, once for the module — row G4's cluster reads its facets.

    Nine clauses each read a different part of this **one** recording: the argv's head and its
    exact flag set, the two tool flags, the appended egress list, the caps, the minted handle and
    the empty book, the child environment, the child `PATH`, the assembled prefix, the untouched
    ordinal counter and the granted `--add-dir`. Every one of them is a read, so the seeding and
    the spawn are paid once instead of nine times; a case that needs its own answer, its own
    `bin_links` or a refusal takes the function-scoped `spawning` above.

    The `MonkeyPatch` context is held for the module because `config.child_path()` and
    `binary_directories()` still resolve the binary off the parent's `PATH`.
    """
    base = tmp_path_factory.mktemp("dispatch")
    with pytest.MonkeyPatch.context() as patch:
        spawn = _spawn_world(base, patch)
        spawn.envelope = spawn.seat(CallType.DISPATCH, member_request())
        yield spawn


def recorded_argv(spawn) -> list[str]:
    """The spawn's own recording, read back on the **`--session-id` it was handed** (row G4)."""
    return fake_cli.argv_of(spawn.binaries, spawn.seat.calls()[0].session_handle)


def test_a_dispatch_spawns_argv_is_the_named_flag_set_and_nothing_outside_it(dispatch_spawn) -> None:
    """Row G4's first clause, **exhaustively**: set equality against the named set, not containment.

    The head is the wrapper and the absolute binary; the flags are the fourteen the SPEC names and
    no fifteenth. The recording is keyed by the minted `--session-id`, which is what a concurrent
    wave needs and what the ordinal counter could not survive (folded: S-i53).
    """
    spawn = dispatch_spawn
    assert isinstance(spawn.envelope, SeatEnvelope)
    fact = spawn.seat.calls()[0]
    argv = recorded_argv(spawn)
    print(f"    [G4] dispatch flags: {sorted(fake_cli.flags_of(argv))}")
    assert list(fact.argv[:3]) == [
        spawn.seat.config.sandbox.binary,
        "-p",
        fact.argv[2],
    ], "sandbox-exec -p <profile> is the argv's head"
    assert fact.argv[3] == str(spawn.seat.binary()), "then the ABSOLUTE-path binary"
    assert Path(fact.argv[3]).is_absolute()
    assert list(fact.argv[4:]) == argv, "and the CLI got its own argv, wrapper consumed"
    assert fake_cli.flags_of(argv) == SPAWN_FLAGS, "exactly the named set, and no flag outside it"


def test_a_delegate_spawns_argv_is_the_same_set_less_the_directory_it_declines(spawning) -> None:
    """The same builder, the other class: one code path, and `add_dir: false` drops one flag."""
    spawn = spawning("delegate", DELEGATE_KIND)
    spawn.seat(CallType.DELEGATE, delegate_request(spawn.seat))

    argv = recorded_argv(spawn)
    print(f"    [G4] delegate flags: {sorted(fake_cli.flags_of(argv))}")
    assert fake_cli.flags_of(argv) == SPAWN_FLAGS - {ADD_DIR_FLAG}
    assert ADD_DIR_FLAG not in argv, "a kind with add_dir: false reaches no directory"


def test_the_two_tool_flags_carry_the_two_halves_of_the_granted_pair(dispatch_spawn) -> None:
    """Row G4: **patterns** on `--allowedTools`, the **derived names** on `--tools`, never the same
    strings — and the names in the block's own seed order, the emission order being the flag's where
    the loader's own check was set equality (folded: S-i1, folded: S-i27, folded: S-i46)."""
    spawn = dispatch_spawn
    argv = recorded_argv(spawn)
    block = spawn.seat.config.kind("dispatch", DISPATCH_KIND)
    profile = spawn.seat.capability_of(block, str(spawn.workspace))
    patterns = argv[argv.index(ALLOWED_TOOLS_FLAG) + 1 : argv.index(DISALLOWED_TOOLS_FLAG)]
    names = argv[argv.index(TOOLS_FLAG) + 1]
    print(f"    [G4] --allowedTools {patterns[:3]}… · --tools {names}")

    assert patterns == list(profile.granted_patterns) == list(block.allowed_tools)
    assert names == ",".join(block.tools), "the block's own seed order, comma-joined"
    assert set(names.split(",")) == set(profile.granted_names), "derived from those very patterns"
    assert patterns != names.split(","), "never the same strings: two vocabularies, two flags"
    assert names.split(",") != list(profile.granted_names), (
        "the fixture's `tools` is deliberately permuted, so the emission order is the seed's"
    )


def test_every_egress_verb_is_appended_by_the_runtime_whatever_the_block_says(dispatch_spawn) -> None:
    """Row G4: **all eight on every spawn**, proven on a kind whose own `disallowed_tools` is empty.

    The block is never held to the eight — the runtime appends the one `EGRESS_REMOTE` literal
    itself — so there is no superset refusal for a seed to fail (folded: S-i15).
    """
    spawn = dispatch_spawn
    argv = recorded_argv(spawn)
    block = spawn.seat.config.kind("dispatch", DISPATCH_KIND)
    refused = argv[argv.index(DISALLOWED_TOOLS_FLAG) + 1 : argv.index(TOOLS_FLAG)]
    print(f"    [G4] --disallowedTools {refused}")
    assert block.disallowed_tools == (), "the fixture kind names none of them"
    assert refused == list(EGRESS_REMOTE), "and all eight are on the wire regardless"
    assert len(EGRESS_REMOTE) == 8


def test_the_spawns_caps_model_and_effort_are_the_kind_blocks_own(dispatch_spawn) -> None:
    """Row G4's `--model`, `--effort` and `--max-budget-usd <the effective cap>`."""
    spawn = dispatch_spawn
    argv = recorded_argv(spawn)
    block = spawn.seat.config.kind("dispatch", DISPATCH_KIND)
    assert argv[argv.index(MODEL_FLAG) + 1] == block.model
    assert argv[argv.index(EFFORT_FLAG) + 1] == block.effort
    assert argv[argv.index(BUDGET_FLAG) + 1] == f"{block.max_call_usd}"
    assert argv[argv.index(PERMISSION_MODE_FLAG) + 1] == "dontAsk", "the one mode that binds"
    assert argv[argv.index(SETTING_SOURCES_FLAG) + 1] == "", "the isolation lever"
    assert argv[argv.index(OUTPUT_FORMAT_FLAG) + 1] == "json"
    assert argv[argv.index(SCHEMA_FLAG) + 1] == schema_argument(CallType.DISPATCH)


def test_a_spawn_is_session_less_and_writes_no_seat_sessions_entry(dispatch_spawn) -> None:
    """Row G4's last clause: a freshly minted `--session-id`, and **no entry in the book**."""
    spawn = dispatch_spawn
    argv = recorded_argv(spawn)
    minted = argv[argv.index(SESSION_MINT_FLAG) + 1]
    print(f"    [G4] minted --session-id {minted}")
    assert SESSION_RESUME_FLAG not in argv, "nothing to resume: a spawn carries no handle forward"
    assert minted == spawn.seat.calls()[0].session_handle
    assert spawn.seat.sessions.handles == {}, "no seat_sessions entry — the mapping is tier-keyed"
    assert not list((spawn.root / "state").rglob("checkpoint*")), "and nothing is checkpointed"


def test_the_child_environment_is_the_five_names_and_carries_no_tmpdir(dispatch_spawn) -> None:
    """Row G4's environment clause, read back from **inside** the spawn.

    `TMPDIR` is absent on purpose (folded: S-i48): with no per-user temp root reaching the child, the
    CLI and Python fall back to `/tmp`, which `runtime.spawn_writable` seeds — which is why no
    per-user temp root has to appear in a spawn's profile.
    """
    spawn = dispatch_spawn
    environment = fake_cli.environment_of(spawn.binaries, spawn.seat.calls()[0].session_handle)
    print(f"    [G4] child env: {sorted(set(environment) - {'PWD', 'SHLVL', '_'})}")
    assert set(environment) <= set(ENV_ALLOWED) | {"PWD", "SHLVL", "_"}, environment
    assert "TMPDIR" not in environment, "no per-user temp root reaches a spawn"
    assert str(spawn.binaries) not in environment["PATH"], "the binary's own directory is excluded"


def test_the_child_path_cannot_resolve_the_seat_binary_positively(dispatch_spawn) -> None:
    """Row G4: `shutil.which(binary, path=child_path()) is None` **holds positively**."""
    spawn = dispatch_spawn
    built = spawn.seat.config.child_path()
    print(f"    [G4] which({spawn.seat.config.binary}) on the child PATH: "
          f"{shutil.which(spawn.seat.config.binary, path=built)}")
    assert shutil.which(spawn.seat.config.binary, path=built) is None


def test_the_link_farm_and_the_throwaway_cwd_sit_under_the_brain_root(spawning) -> None:
    """Row G4: both resolve inside `brain/state/<task>/spawns/<tick>/`, never a per-user temp root.

    A tree `sandbox.deny_write` already names, which is what makes order W4's open-time farm check
    an assertion that holds **structurally**: a spawn cannot rewrite the `PATH` it was given
    (folded: S-i48). The farm is proven on a root that names one `bin_links` entry, because the
    fixture seed empties the list.
    """
    spawn = spawning("delegate", DELEGATE_KIND, bin_links=["sh"])
    spawn.seat(CallType.DELEGATE, delegate_request(spawn.seat))

    session = spawn.seat.calls()[0].session_handle
    environment = fake_cli.environment_of(spawn.binaries, session)
    farm = Path(environment["PATH"].split(os.pathsep)[0])
    cwd = Path(fake_cli.cwd_of(spawn.binaries, session))
    root = spawn.root.resolve()
    print(f"    [G4] farm {farm} · cwd {cwd}")

    assert farm == spawn.scaffold / "bin", "the farm is runtime-owned, at the SPEC's own path"
    assert (farm / "sh").is_symlink(), "and it is still one name at a time"
    assert cwd == (spawn.scaffold / "cwd").resolve(), "so is an add_dir: false cwd"
    assert list(cwd.iterdir()) == [], "still a throwaway EMPTY directory"
    for path in (farm, cwd):
        assert root in path.resolve().parents, f"{path} is not under the brain root"
        assert path.resolve().is_relative_to(root / "state" / SPAWN_TASK / "spawns" / str(SPAWN_TICK))
    assert not farm.name.startswith("protean-seat-"), (
        "not a `mkdtemp` product: the seats' throwaway prefix is what a spawn no longer uses"
    )
    assert farm.parent == spawn.scaffold and cwd.parent == spawn.scaffold.resolve(), (
        "both sit inside the ONE runtime-owned directory rather than under a per-user temp root"
    )


def test_a_seats_cwd_is_its_tasks_directory_inside_the_brain_root(director_call) -> None:
    """A seat's cwd is **no longer** a throwaway: it is `<root>/state/<task>/seat-cwd/`, inside the
    brain root, and still empty (`the build specification (not in this mirror)` § Deliverable 1). The seats'
    farm is still the landed `mkdtemp` one; this fixture seeds no `bin_links` and builds no farm, so
    `test_G3_a_seats_link_farm_is_still_a_mkdtemp_outside_the_brain_root` asserts it (AUDIT R2-F3)."""
    seat = director_call.seat
    cwd = Path(fake_cli.cwd_of(director_call.binaries)).resolve()
    assert seat.config.root.resolve() in cwd.parents, "a seat's cwd is in the brain root"
    assert cwd == (seat.config.root / "state" / TASK / SEAT_CWD_DIRNAME).resolve()
    assert list(cwd.iterdir()) == []


def test_the_assembled_prefix_is_the_cortex_node_md_then_the_kinds_own_prefix_file(
    dispatch_spawn,
) -> None:
    """Row G4: the **calling node's `NODE.md` first** — the cortex's for a dispatch member, resolved
    with no payload key at all — then the kind's prefix file, read from the block's own confined
    path rather than from `prompt_path()` (A1-8, folded: S-i2, folded: S-i35)."""
    spawn = dispatch_spawn
    argv = recorded_argv(spawn)
    sent = argv[argv.index(SYSTEM_PROMPT_FLAG) + 1]
    root = spawn.seat.config.root
    cortex_md = (root / "nodes" / "cortex" / "NODE.md").read_text(encoding="utf-8")
    block = spawn.seat.config.kind("dispatch", DISPATCH_KIND)
    prefix = block.prompt_path.read_text(encoding="utf-8")

    print(f"    [G4] prefix: cortex/NODE.md then {block.prompt_path.name}")
    assert spawn.seat.prefix_node(CallType.DISPATCH) == str(NodeName.CORTEX), "no payload key"
    assert sent.startswith(cortex_md), "the cortex NODE.md is the FIRST half: the wave is its call"
    assert sent.endswith(prefix), "and the kind's own prefix file is the second"
    assert block.prompt_path == (root / "seats" / "kinds" / f"{DISPATCH_KIND}.md").resolve()


def test_a_delegates_first_prefix_half_is_still_the_calling_nodes_node_md(spawning) -> None:
    """The channel a delegate's calling node travels on is untouched: `NodeCall.node` (D3-2)."""
    spawn = spawning("delegate", DELEGATE_KIND)
    spawn.seat(CallType.DELEGATE, delegate_request(spawn.seat))

    argv = recorded_argv(spawn)
    sent = argv[argv.index(SYSTEM_PROMPT_FLAG) + 1]
    root = spawn.seat.config.root
    node_md = (root / "nodes" / str(NodeName.HIPPOCAMPUS) / "NODE.md").read_text(encoding="utf-8")
    cortex_md = (root / "nodes" / "cortex" / "NODE.md").read_text(encoding="utf-8")
    assert sent.startswith(node_md), "the CALLING node's, off the NodeCall payload"
    assert not sent.startswith(cortex_md)
    assert sent.endswith(
        spawn.seat.config.kind("delegate", DELEGATE_KIND).prompt_path.read_text(encoding="utf-8")
    )


def test_the_member_request_travels_on_stdin_exactly_as_the_wave_sends_it(spawning) -> None:
    """A1-8: stdin is the member request as A.1 sends it, unwrapped (D9-1) — and it is what selects
    the stand-in's response, the `kind` and the `unit_id` being all a test can name in advance."""
    spawn = spawning(members=[((DISPATCH_KIND, UNIT), fake_cli.envelope(spawn_answer("dispatch")))])
    spawn.seat(CallType.DISPATCH, member_request())

    session = spawn.seat.calls()[0].session_handle
    assert json.loads(fake_cli.stdin_of(spawn.binaries, session)) == member_request()
    assert (spawn.binaries / f"response-{DISPATCH_KIND}-{UNIT}.json").exists(), (
        "the answer this member read was keyed by its own kind and unit id"
    )


# The seats' half of S-i53 — two calls, two ordinals on the shared counter — is folded into
# `test_the_first_call_mints_and_the_second_resumes`, which drives the same two-call state; the
# spawn half is `test_a_spawn_never_advances_the_shared_counter` below.


def test_a_spawn_never_advances_the_shared_counter(dispatch_spawn) -> None:
    """The race is the counter's read-modify-write, so a spawn does not perform it at all."""
    spawn = dispatch_spawn
    assert fake_cli.invocations(spawn.binaries) == 0, "the counter was never read or written"
    assert (spawn.binaries / f"argv-{spawn.seat.calls()[0].session_handle}.txt").exists()
    assert not list(spawn.binaries.glob("argv-1.txt")), "and no ordinal recording exists"


# ---- row G5 (a): the two pre-process refusals, before any process exists ---------------


def test_the_control_fires_the_shim_on_purpose_and_fills_its_log(shim_log: Path) -> None:
    """The control. An empty log below means nothing unless a real invocation would fill it."""
    completed = subprocess.run(
        [str(SHIM_DIR / "claude"), "-p", "a spawn that should never happen"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PROTEAN_SHIM_LOG": str(shim_log)},
    )
    print(f"    [G5 control] exit {completed.returncode} · log {shim_log.stat().st_size} bytes")
    assert completed.returncode != 0, "loudly"
    assert shim_log.stat().st_size > 0, "the log fills when a process really is spawned"


def refused_before_any_process(spawn, shim_log: Path, addressee, payload) -> str:
    """One pre-process refusal: the message, with nothing spawned and nothing recorded."""
    with pytest.raises(SeatConfigError) as raised:
        spawn.seat(addressee, payload)
    assert shim_log.stat().st_size == 0, f"the shim ran: {shim_log.read_text(encoding='utf-8')}"
    assert fake_cli.invocations(spawn.binaries) == 0, "no process was created"
    assert not list(spawn.binaries.glob("argv-*.txt")), "and the stand-in recorded nothing"
    assert spawn.seat.calls() == (), "no facts either: the refusal is before the record"
    return str(raised.value)


@pytest.mark.parametrize(
    "label, overrides",
    [
        ("a fourth key", {"extra": "anything"}),
        ("a workspace path", {"workspace_path": "/tmp/not-the-runtimes"}),
    ],
)
def test_a_dispatch_payload_outside_wave_members_three_fields_refuses_by_name(
    spawning, shim_log: Path, label: str, overrides: dict
) -> None:
    """Row G5 (a): the key set must **equal** `WaveMember`'s three fields, with no process created."""
    spawn = spawning()
    message = refused_before_any_process(
        spawn, shim_log, CallType.DISPATCH, member_request(**overrides)
    )
    print(f"    [G5a] dispatch, {label}: {message[:120]}")
    assert str(CallType.DISPATCH) in message
    assert all(name in message for name in WaveMember.model_fields)


def test_a_dispatch_payload_missing_a_field_refuses_by_the_same_equality(
    spawning, shim_log: Path
) -> None:
    """Equality, not containment: a payload that is a strict subset is refused too."""
    spawn = spawning()
    payload = member_request()
    payload.pop("admitted_ref")
    message = refused_before_any_process(spawn, shim_log, CallType.DISPATCH, payload)
    print(f"    [G5a] dispatch, a missing field: {message[:120]}")
    assert "admitted_ref" in message


def test_a_delegate_payload_outside_the_landed_node_call_shape_refuses_by_name(
    spawning, shim_log: Path
) -> None:
    """Row G5 (a)'s other half, against C1 `NodeCall`'s own field set — read off the contract."""
    spawn = spawning("delegate", DELEGATE_KIND)
    payload = delegate_request(spawn.seat, add_dir="/tmp/not-the-runtimes")
    message = refused_before_any_process(spawn, shim_log, CallType.DELEGATE, payload)
    print(f"    [G5a] delegate, a fourth key: {message[:120]}")
    assert str(CallType.DELEGATE) in message
    assert all(name in message for name in NodeCall.model_fields)


def test_a_path_named_anywhere_under_either_shape_refuses_by_name(
    spawning, shim_log: Path
) -> None:
    """"any key naming a path **under** either shape" — including nested in a dumped mapping, which
    is the hole this refusal exists for: A.1 removed the field a directory would have travelled in.
    """
    spawn = spawning("delegate", DELEGATE_KIND)
    payload = delegate_request(spawn.seat)
    payload["payload"] = {**payload["payload"], "output_dir": "/tmp/not-the-runtimes"}
    message = refused_before_any_process(spawn, shim_log, CallType.DELEGATE, payload)
    print(f"    [G5a] delegate, a nested path key: {message[:140]}")
    assert "payload.output_dir" in message, "named by its position, at depth"


def test_the_legal_member_request_is_not_refused_by_either_check(spawning, shim_log: Path) -> None:
    """The positive control for both refusals: the shapes the wave really sends go through."""
    spawn = spawning()
    assert isinstance(spawn.seat(CallType.DISPATCH, member_request()), SeatEnvelope)
    assert fake_cli.invocations(spawn.binaries) == 0, "spawn-keyed, so the counter stays at zero"
    assert recorded_argv(spawn), "and the process really did run"


# ---- row G5 (b): the workspace's single channel, proven positively ---------------------


def test_the_recorded_add_dir_equals_the_workspace_the_test_handed_it(dispatch_spawn) -> None:
    """Row G5 (b), **positively**: with (a) closing the only other channel there is nothing left to
    assert against, so what is read back is the value itself.

    The `/`-and-sibling identity fixture is retired with the assertion it proved (folded: S-i7 —
    superseded, folded: S-i22): a runtime identity check would compare one value with itself.
    """
    spawn = dispatch_spawn
    argv = recorded_argv(spawn)
    print(f"    [G5b] --add-dir {argv[argv.index(ADD_DIR_FLAG) + 1]}")
    assert argv[argv.index(ADD_DIR_FLAG) + 1] == str(spawn.workspace)
    assert fake_cli.cwd_of(spawn.binaries, spawn.seat.calls()[0].session_handle) == str(
        spawn.workspace
    ), "and a dispatch spawn's cwd is that same workspace"


def test_no_payload_workspace_arm_is_reachable_for_a_spawn_addressee(spawning) -> None:
    """Row G5 (b)'s "including when a payload carries one": the arm is not reachable at all.

    Asserted on `workspace_for()` directly as well as through the call, because the payload that
    would carry one is refused one method up — so the two halves of the closure are proven
    separately rather than one hiding the other.
    """
    spawn = spawning()
    block = spawn.seat.config.kind("dispatch", DISPATCH_KIND)
    smuggled = {"workspace_path": "/tmp/not-the-runtimes"}

    assert spawn.seat.workspace_for(smuggled, block) == str(spawn.workspace)
    assert spawn.seat.workspace_for(smuggled) == "/tmp/not-the-runtimes", (
        "the seats' arm is left exactly as it is: their batteries hand a workspace that way"
    )


def test_wave_member_still_carries_exactly_three_fields(spawning) -> None:
    """Row G5's last clause: `src/protean/state/seats.py` gains no field (folded: A1-4)."""
    spawn = spawning()
    print(f"    [G5] WaveMember fields: {list(WaveMember.model_fields)}")
    assert tuple(WaveMember.model_fields) == ("kind", "unit_id", "admitted_ref")
    assert len(WaveMember.model_fields) == 3
    assert not [name for name in WaveMember.model_fields if names_a_path(name)]
    assert spawn.seat.config.kind("dispatch", DISPATCH_KIND).add_dir is True


# --------------------------------------------------------------------------------------
# G1: the CLI files a session by the directory it ran in, so a second process must resume there
# --------------------------------------------------------------------------------------


def test_G1_a_second_layer_resumes_the_session_the_first_layer_minted(
    tmp_path: Path, monkeypatch
) -> None:
    """Row G1 (`the build specification (not in this mirror)` § Deliverable 5, "A dry repro first").

    Two separately built live layers on one fixture root and one task, with the stand-in keying
    its session store by the invocation's `$PWD` (`cwd_sessions`). The first layer opens the task
    and mints the manager's session with one call; the second restores the first's handles, as a
    new process restores a checkpoint, and makes one call. On the pre-fix tree each layer's seat
    runs in its own throwaway directory, so the resume is refused and the call falls back
    (`resumed_as_new`); § Deliverable 1's per-task directory is what makes it resume.

    It asserts only the second call's argv and its facts' `error`, both as `SeatCallFacts` record
    them, and each message prints that `error`.
    """
    answer = fake_cli.envelope(fake_cli.planner_result(UNIT, GOAL))
    root, _ = seeded_live_root(tmp_path, monkeypatch, [answer] * 3, cwd_sessions=True)

    first = build_live_layer(root=root)
    handles = first.sessions.open_task(TASK)
    first.port(Tier.MANAGER, request_for(Tier.MANAGER))
    minted = first.calls()[0].session_handle

    second = build_live_layer(root=root)
    second.sessions.restore(TASK, handles)
    second.port(Tier.MANAGER, request_for(Tier.MANAGER))

    facts = second.calls()[0]
    argv = list(facts.argv)
    resumed = argv[argv.index(SESSION_RESUME_FLAG) + 1] if SESSION_RESUME_FLAG in argv else None
    print(f"    [G1] second call: {SESSION_RESUME_FLAG} {resumed} · error={facts.error!r}")
    assert (resumed, SESSION_MINT_FLAG in argv) == (minted, False), (
        f"the second call must resume {minted} and mint nothing; error={facts.error!r}"
    )
    assert RESUMED_AS_NEW not in facts.error, (
        f"the second call fell back rather than resuming; error={facts.error!r}"
    )


# --------------------------------------------------------------------------------------
# G2 and G3: the seats run in one runtime-owned directory per task; the cwd is on the facts
# --------------------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]

#: G2's never-collected child interpreter, on `live_replay_child.py`'s precedent: run with
#: `sys.executable`, argv in, JSON out, and this module owns every assertion.
SEAT_CWD_CHILD = Path(__file__).resolve().parent / "seat_cwd_child.py"

#: The prefix of a `calls:` block's landed per-instance throwaway cwd, which `audit.py` owns.
CALLS_CWD_PREFIX = "protean-seat-cwd-"

#: A second task on the same root, for "two tasks on one root run in two directories".
OTHER_TASK = "task-live-2"


def _seat_directory(root: Path, task: str = TASK) -> Path:
    """`<root>/state/<task>/<dirname>/`, spelled from the SPEC's own components, resolved."""
    return (root / "state" / task / SEAT_CWD_DIRNAME).resolve()


def _ran_in(binaries: Path, index: int | str = 1) -> Path:
    """The `$PWD` the stand-in recorded for one invocation, resolved."""
    return Path(fake_cli.cwd_of(binaries, index)).resolve()


def _flag_value(argv, flag: str) -> str | None:
    """The value after `flag` in an argv, or `None` when the flag is absent."""
    argv = list(argv)
    return argv[argv.index(flag) + 1] if flag in argv else None


def _manager_answer() -> dict:
    return fake_cli.envelope(fake_cli.planner_result(UNIT, GOAL))


def _two_layers(tmp_path: Path, monkeypatch) -> SimpleNamespace:
    """G1's scenario, for the G2 clauses G1 does not assert: two separately built live layers on one
    root and one task, with the stand-in keying its session store by `$PWD` (`cwd_sessions`). The
    first opens the task and mints the manager's session; the second restores those handles."""
    root, binaries = seeded_live_root(
        tmp_path, monkeypatch, [_manager_answer()] * 3, cwd_sessions=True
    )
    first = build_live_layer(root=root)
    handles = first.sessions.open_task(TASK)
    first.port(Tier.MANAGER, request_for(Tier.MANAGER))
    minted = first.calls()[0]
    second = build_live_layer(root=root)
    second.sessions.restore(TASK, handles)
    second.port(Tier.MANAGER, request_for(Tier.MANAGER))
    return SimpleNamespace(root=root, binaries=binaries, first=minted, second=second.calls()[0])


def test_G2_the_second_layer_resumes_the_first_ones_session_without_the_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    """Row G2: the second invocation's argv carries `--resume` with the first's session id and no
    `--session-id`, and its facts' `error` carries no `resumed_as_new` — read off the facts and off
    the argv the stand-in recorded, over exactly two invocations, so nothing was re-sent."""
    run = _two_layers(tmp_path, monkeypatch)
    recorded = fake_cli.argv_of(run.binaries, 2)
    print(f"    [G2] minted {run.first.session_handle} · second: "
          f"{SESSION_RESUME_FLAG} {_flag_value(recorded, SESSION_RESUME_FLAG)} · "
          f"error={run.second.error!r} · invocations={fake_cli.invocations(run.binaries)}")

    assert fake_cli.invocations(run.binaries) == 2, "no fallback re-send"
    for argv in (run.second.argv, recorded):
        assert _flag_value(argv, SESSION_RESUME_FLAG) == run.first.session_handle
        assert SESSION_MINT_FLAG not in argv
    assert RESUMED_AS_NEW not in run.second.error, run.second.error


def test_G2_both_invocations_ran_in_the_tasks_one_seat_directory(
    tmp_path: Path, monkeypatch
) -> None:
    """Row G2: both invocations ran in `<root>/state/<task>/<dirname>/`, compared resolved from the
    stand-in's recorded `$PWD` and from `SeatCallFacts.cwd`; the directory exists and is empty."""
    run = _two_layers(tmp_path, monkeypatch)
    expected = _seat_directory(run.root)
    recorded = [_ran_in(run.binaries, 1), _ran_in(run.binaries, 2)]
    on_facts = [Path(run.first.cwd).resolve(), Path(run.second.cwd).resolve()]
    print(f"    [G2] expected {expected} · $PWD {recorded} · facts {on_facts}")

    assert recorded == [expected, expected]
    assert on_facts == [expected, expected]
    assert expected.is_dir()
    assert list(expected.iterdir()) == []


def test_G2_a_session_minted_in_a_child_interpreter_resumes_in_the_parent(
    tmp_path: Path, monkeypatch
) -> None:
    """Row G2's new-process clause: the first call runs in a child interpreter, which reports its
    handles and its cwd by JSON and exits. The directory still exists after it exits, and the
    parent's second layer restores those handles and resumes without the fallback."""
    root, binaries = seeded_live_root(
        tmp_path, monkeypatch, [_manager_answer()] * 3, cwd_sessions=True
    )
    request = request_for(Tier.MANAGER)
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(request.model_dump(mode="json")), encoding="utf-8")
    destination = tmp_path / "child.json"
    child = subprocess.run(
        [sys.executable, str(SEAT_CWD_CHILD), str(root), TASK, str(request_file), str(destination)],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert child.returncode == 0, f"the child interpreter failed:\n{child.stderr}"
    reported = json.loads(destination.read_text(encoding="utf-8"))
    print(f"    [G2] child JSON: {json.dumps(reported, sort_keys=True)}")

    directory = Path(reported["cwd"]).resolve()
    assert reported["pid"] != os.getpid(), "the first call really ran in another interpreter"
    assert reported["session_flags"] == [[SESSION_MINT_FLAG, reported["session_handle"]]]
    assert directory == _seat_directory(root) == _ran_in(binaries, 1)
    assert directory.is_dir(), "the directory outlived the interpreter that made it"
    assert list(directory.iterdir()) == []

    parent = build_live_layer(root=root)
    parent.sessions.restore(TASK, reported["handles"])
    parent.port(Tier.MANAGER, request)
    facts = parent.calls()[0]
    print(f"    [G2] parent: {SESSION_RESUME_FLAG} {_flag_value(facts.argv, SESSION_RESUME_FLAG)} · "
          f"error={facts.error!r} · cwd={facts.cwd}")

    assert RESUMED_AS_NEW not in facts.error, facts.error
    assert _flag_value(facts.argv, SESSION_RESUME_FLAG) == reported["session_handle"]
    assert SESSION_MINT_FLAG not in facts.argv
    assert fake_cli.invocations(binaries) == 2, "one call per process, nothing re-sent"
    assert Path(facts.cwd).resolve() == directory == _ran_in(binaries, 2)


def test_G2_a_director_call_and_a_manager_call_on_one_task_share_one_directory(
    tmp_path: Path, monkeypatch
) -> None:
    """Row G2: both seats on one task run in the one directory — their sessions are keyed by id."""
    root, binaries = seeded_live_root(
        tmp_path,
        monkeypatch,
        [fake_cli.envelope(fake_cli.director_result()), _manager_answer()],
        cwd_sessions=True,
    )
    layer = build_live_layer(root=root)
    layer.sessions.open_task(TASK)
    layer.port(Tier.DIRECTOR, request_for(Tier.DIRECTOR))
    director = layer.calls()[0]
    layer.port(Tier.MANAGER, request_for(Tier.MANAGER))
    manager = layer.calls()[0]
    expected = _seat_directory(root)
    print(f"    [G2] {director.tier} {director.cwd} · {manager.tier} {manager.cwd}")

    assert (director.tier, manager.tier) == (str(Tier.DIRECTOR), str(Tier.MANAGER))
    assert [_ran_in(binaries, 1), _ran_in(binaries, 2)] == [expected, expected]
    assert [Path(director.cwd).resolve(), Path(manager.cwd).resolve()] == [expected, expected]
    assert expected.is_dir()
    assert list(expected.iterdir()) == []


def test_G2_two_tasks_on_one_root_run_in_two_directories(tmp_path: Path, monkeypatch) -> None:
    """Row G2: the task is read at call time off the seat's own book, so one seat instance on one
    root runs a second task's call in that task's directory, not the first's."""
    root, binaries = seeded_live_root(
        tmp_path, monkeypatch, [_manager_answer()] * 2, cwd_sessions=True
    )
    layer = build_live_layer(root=root)
    on_facts = {}
    for task in (TASK, OTHER_TASK):
        layer.sessions.open_task(task)
        layer.port(Tier.MANAGER, request_for(Tier.MANAGER))
        on_facts[task] = Path(layer.calls()[0].cwd).resolve()
    first, second = _seat_directory(root, TASK), _seat_directory(root, OTHER_TASK)
    print(f"    [G2] {TASK} → {on_facts[TASK]} · {OTHER_TASK} → {on_facts[OTHER_TASK]}")

    assert first != second
    assert [_ran_in(binaries, 1), _ran_in(binaries, 2)] == [first, second]
    assert on_facts == {TASK: first, OTHER_TASK: second}
    for directory in (first, second):
        assert directory.is_dir()
        assert list(directory.iterdir()) == []


@pytest.mark.parametrize("call_type", [CallType.THINK, CallType.ESCALATE])
def test_G3_a_calls_block_runs_in_a_fresh_empty_throwaway_outside_the_brain_root(
    live, call_type
) -> None:
    """Row G3: only the seats move. A `think` and an `escalate` call run in a fresh, empty directory
    per instance, outside the brain root, `protean-seat-cwd-`-prefixed — a member of `audit.py`'s
    `OWN_SCAFFOLD_MARKERS` — even with a task open in the book, which takes no per-task directory."""
    seat, binaries = live([fake_cli.envelope(CALL_ANSWERS[call_type])] * 2)
    seat(call_type, node_call(seat, call_type))
    other = fake_cli.live_seat(seat.config.root)
    other.sessions.open_task(TASK)
    other(call_type, node_call(other, call_type))
    brain = seat.config.root.resolve()
    first, second = _ran_in(binaries, 1), _ran_in(binaries, 2)
    print(f"    [G3] {call_type}: {first} · {second}")

    assert CALLS_CWD_PREFIX in OWN_SCAFFOLD_MARKERS, "audit.py's marker still owns the prefix"
    for cwd in (first, second):
        assert cwd.name.startswith(CALLS_CWD_PREFIX)
        assert brain not in cwd.parents, "a calls: block's cwd is outside the brain root"
        assert cwd.is_dir()
        assert list(cwd.iterdir()) == []
    assert first != second, "one fresh directory per instance"
    assert not _seat_directory(seat.config.root).exists(), "no seat call, no per-task directory"


def test_G3_the_facts_cwd_is_where_a_seat_ran(live) -> None:
    """Row G3: `SeatCallFacts.cwd` equals (resolved) the stand-in's recorded `$PWD` for a seat."""
    seat, binaries = live([fake_cli.envelope(fake_cli.director_result())])
    seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))
    facts = seat.calls()[0]
    print(f"    [G3] seat facts.cwd {facts.cwd}")
    assert Path(facts.cwd).resolve() == _ran_in(binaries, 1)
    assert Path(facts.cwd).resolve() == _seat_directory(seat.config.root)


def test_G3_the_facts_cwd_is_where_a_calls_block_ran(live) -> None:
    """Row G3: `SeatCallFacts.cwd` equals (resolved) the stand-in's recorded `$PWD` for a `calls:`
    block."""
    seat, binaries = live([fake_cli.envelope(CALL_ANSWERS[CallType.THINK])])
    seat(CallType.THINK, node_call(seat, CallType.THINK))
    facts = seat.calls()[0]
    print(f"    [G3] calls: facts.cwd {facts.cwd}")
    assert facts.cwd, "the field is filled"
    assert Path(facts.cwd).resolve() == _ran_in(binaries, 1)


@pytest.mark.parametrize("kind_class", ["dispatch", "delegate"])
def test_G3_the_facts_cwd_is_where_a_spawn_ran(spawning, kind_class) -> None:
    """Row G3: `SeatCallFacts.cwd` equals (resolved) the stand-in's recorded `$PWD` for a spawn — a
    `dispatch` spawn's workspace and an `add_dir: false` delegate's scaffold `cwd`."""
    if kind_class == "dispatch":
        spawn = spawning()
        spawn.seat(CallType.DISPATCH, member_request())
        expected = spawn.workspace.resolve()
    else:
        spawn = spawning("delegate", DELEGATE_KIND)
        spawn.seat(CallType.DELEGATE, delegate_request(spawn.seat))
        expected = (spawn.scaffold / "cwd").resolve()
    facts = spawn.seat.calls()[0]
    recorded = _ran_in(spawn.binaries, facts.session_handle)
    print(f"    [G3] {kind_class} facts.cwd {facts.cwd} · $PWD {recorded}")
    assert Path(facts.cwd).resolve() == recorded == expected


def test_G3_no_seat_argv_carries_add_dir_even_with_a_workspace_handed(
    live, tmp_path: Path
) -> None:
    """Row G3: `--add-dir` never reaches a seat's argv, and a handed workspace does not become a
    seat's cwd — both seats run in the task's directory."""
    workspace = tmp_path / "clone"
    workspace.mkdir()
    seat, binaries = live(
        [fake_cli.envelope(fake_cli.director_result()), _manager_answer()],
        workspace_path=str(workspace),
    )
    seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))
    director = seat.calls()[0]
    seat(Tier.MANAGER, request_for(Tier.MANAGER))
    manager = seat.calls()[0]
    print(f"    [G3] {ADD_DIR_FLAG} on the seats' argv: "
          f"{[ADD_DIR_FLAG in facts.argv for facts in (director, manager)]}")

    for index, facts in ((1, director), (2, manager)):
        assert ADD_DIR_FLAG not in facts.argv
        assert ADD_DIR_FLAG not in fake_cli.argv_of(binaries, index)
        assert Path(facts.cwd).resolve() == _seat_directory(seat.config.root)
        assert Path(facts.cwd).resolve() != workspace.resolve()


def test_G3_a_seats_link_farm_is_still_a_mkdtemp_outside_the_brain_root(
    tmp_path: Path, monkeypatch
) -> None:
    """Row G3 (AUDIT R2-F3): the seats' link farm is still the landed `mkdtemp` one, outside the
    brain root. Proven on a root whose `runtime.bin_links` names one entry, because the fixture seed
    empties the list and builds no farm; the farm is read off the child `PATH` the stand-in
    recorded, the way the spawn case reads a spawn's."""
    root, binaries = seeded_live_root(
        tmp_path, monkeypatch, [fake_cli.envelope(fake_cli.director_result())]
    )
    _with_bin_links(root, ["sh"])
    seat = fake_cli.live_seat(root)
    seat.sessions.open_task(TASK)
    seat(Tier.DIRECTOR, request_for(Tier.DIRECTOR))
    farm = Path(fake_cli.environment_of(binaries)["PATH"].split(os.pathsep)[0]).resolve()
    brain = root.resolve()
    print(f"    [G3] seat farm {farm} · cwd {_ran_in(binaries)}")

    assert farm.name.startswith("protean-seat-bin-"), "the seats' landed `mkdtemp` prefix"
    assert farm.parent == Path(tempfile.gettempdir()).resolve(), "made by `mkdtemp` in the temp root"
    assert brain not in farm.parents, "outside the brain root"
    assert (farm / "sh").is_symlink(), "and it is the farm: one name, linked"
    assert _ran_in(binaries) == _seat_directory(root), "while the seat's cwd is its task's directory"


def test_G3_the_facts_gain_exactly_cwd_and_the_receipt_nothing() -> None:
    """Row G3: `SeatCallFacts` gains one field, `cwd`, defaulting empty; `SeatCallRecord` gains no
    column for it and the seat-call schema stays 3 (§ Scaffold clause 2(b))."""
    fields = dataclasses.fields(SeatCallFacts)
    names = [field.name for field in fields]
    print(f"    [G3] SeatCallFacts' last fields {names[-2:]}")
    assert names[-1] == "cwd" and names.count("cwd") == 1
    assert fields[-1].default == ""
    assert "cwd" not in SeatCallRecord.model_fields
    assert config.SEAT_CALL_SCHEMA_VERSION == 3
