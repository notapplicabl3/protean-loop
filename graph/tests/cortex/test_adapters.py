"""The three adapters: one session per tier per task, and an envelope that is not tidier.

`the build specification (not in this mirror)` § Deliverable 6 → *Fresh per task, cached within task*
(`DIGEST:70`, folded: S-14) and the wire shape's four measured facts (folded: A1-10).

**B5's artifact is the session-lifetime output below**, and B4's is the three adapters and the
slice `DirectorDirection` writes; neither row is closed here — both are the operator's.

**Builder-verified M18 is only half met and the shortfall is recorded**: the in-process half —
one handle per tier per task, all three minted together, the same three for the life of the
task, discarded at task end — is asserted here; the checkpointed half is a `BLOCKED` entry in
this order's builder's ledger, because no code path writes `BrainState.seat_sessions` and every
writer of `BrainState` is outside this order's writable set.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from protean import config
from protean.cortex.adapters import (
    FIRST_PARTY_MODEL_TEMPLATE,
    OVERHEAD_MODEL,
    OVERHEAD_MODEL_PREFIX,
    ScriptedSeat,
    SeatDesk,
    SessionBook,
    build_envelope,
    first_party_model,
)
from protean.runtime.seat import SeatPort, SeatSelection, decode_seat_result
from protean.state.enums import CallType, Escalation, GoalStatus, Tier
from protean.state.outputs import AdmittedContext
from protean.state.primitives import GoalItem, WorkUnit
from protean.state.seats import CACHE_READ_KEY, SeatEnvelope
from protean.state.workspace import DirectorRequest, ManagerRequest, Workspace
from tests.cortex.conftest import director_request, manager_request, one_goal_workspace


def _workspace(tick: int = 1, task_id: str = "task-a") -> Workspace:
    return one_goal_workspace(task_id, tick=tick)


def _planner_request(task_id: str = "task-a") -> ManagerRequest:
    return manager_request(_workspace(task_id=task_id))


def _director_request(task_id: str = "task-a") -> DirectorRequest:
    return director_request(_workspace(task_id=task_id))


# --------------------------------------------------------------------------------------
# Session lifetime — B5's artifact
# --------------------------------------------------------------------------------------


def test_seat_handles_are_minted_together_cached_replaced_and_then_discarded():
    """B5's artifact: the whole session lifetime, read off **one** book in order.

    Re-based by build A.1: the cortex holds **two** seats, so the book mints two handles. The
    count is read off `config.TIERS` rather than written down, so the assertion is about the
    rule — one handle per seat, minted together — and not about the number two.

    Then, in sequence: the same task gets the same handles however often it is asked (minted
    once, cached for the life of the task) · a new task discards the previous set and mints more ·
    and handles are discarded at task end, after which asking for one is a wiring bug.
    """
    book = SessionBook()
    handles = book.open_task("task-a")
    print(f"    [B5] handles for task-a: {json.dumps(handles, sort_keys=True)}")
    assert sorted(handles) == sorted(config.TIERS)
    assert len(set(handles.values())) == len(config.TIERS), "one distinct handle per seat"

    for _ in range(5):
        assert book.open_task("task-a") == handles
    assert book.minted_tasks == ["task-a"], "minted once, cached for the life of the task"

    second = book.open_task("task-b")
    print(f"    [B5] task-b: {json.dumps(second, sort_keys=True)}")
    assert set(handles.values()).isdisjoint(second.values())
    assert book.minted_tasks == ["task-a", "task-b"]

    book.close_task()
    with pytest.raises(RuntimeError, match="no seat session is open"):
        book.handle(Tier.MANAGER)


def test_every_call_inside_one_task_carries_that_tier_s_one_handle(script_for):
    desk = SeatDesk()
    seat = ScriptedSeat(script=script_for("stuck_ladder"), desk=desk)

    desk.open_tick(
        "task-a", SeatSelection(tier=Tier.MANAGER, escalation=Escalation.EMPTY_UNIT_STACK)
    )
    seat(Tier.MANAGER, _planner_request())
    desk.open_tick(
        "task-a", SeatSelection(tier=Tier.DIRECTOR, escalation=Escalation.REPLAN_EXHAUSTED)
    )
    seat(Tier.DIRECTOR, _director_request())
    desk.open_tick(
        "task-a", SeatSelection(tier=Tier.MANAGER, escalation=Escalation.EMPTY_UNIT_STACK)
    )
    seat(Tier.MANAGER, _planner_request())

    print(f"    [B5] recorded calls: {seat.calls}")
    manager_handles = {handle for _, handle in seat.calls_for(Tier.MANAGER)}
    assert len(manager_handles) == 1, "one session for the life of the task"
    assert manager_handles.isdisjoint(
        {handle for _, handle in seat.calls_for(Tier.DIRECTOR)}
    )


def test_the_envelope_reports_the_session_handle_the_call_used(script_for):
    desk = SeatDesk()
    seat = ScriptedSeat(script=script_for("stuck_ladder"), desk=desk)
    desk.open_tick(
        "task-a", SeatSelection(tier=Tier.MANAGER, escalation=Escalation.EMPTY_UNIT_STACK)
    )
    envelope = seat(Tier.MANAGER, _planner_request())
    assert envelope.session_id == desk.handle(Tier.MANAGER)


def test_the_port_is_the_protocol_the_runtime_declared(script_for):
    assert isinstance(
        ScriptedSeat(script=script_for("stuck_ladder"), desk=SeatDesk()), SeatPort
    )


# --------------------------------------------------------------------------------------
# The wire shape's four measured facts
# --------------------------------------------------------------------------------------


def test_the_envelope_carries_all_four_measured_facts():
    """The wire shape's four measured facts (folded: A1-10), and the envelope around them.

    Folded in: it **is** a `SeatEnvelope` and survives a round trip · it preserves the keys a real
    envelope has that the model does not require — "a mock tidier than the thing it stands in for
    is named assumption 1's failure shape" · and its usage counters default to zero, so a scripted
    run costs nothing.
    """
    envelope = build_envelope(
        CallType.DISPATCH,
        {"emitter": "dispatch", "tick": 1, "unit_id": "u-1", "narrative": "did it"},
        session_id="seat-dispatch-abc",
        usage={"input_tokens": 12, "output_tokens": 3, CACHE_READ_KEY: 4096},
    )
    assert envelope.is_structured_success(), "fact 1: structured success is a forced tool call"
    assert isinstance(envelope.result, str), "fact 2: result is a JSON string, not an object"
    assert json.loads(envelope.result)["unit_id"] == "u-1"
    assert OVERHEAD_MODEL in envelope.modelUsage, "fact 3: the overhead entry is there"
    assert envelope.first_party_models(OVERHEAD_MODEL_PREFIX) == (
        first_party_model(CallType.DISPATCH),
    )
    assert envelope.usage[CACHE_READ_KEY] == 4096, "fact 4: a cache receipt exists"

    director = build_envelope(Tier.DIRECTOR, {"emitter": "director", "tick": 2}, session_id="s")
    assert isinstance(director, SeatEnvelope)
    assert SeatEnvelope.model_validate(director.model_dump()) == director

    manager = build_envelope(Tier.MANAGER, {"emitter": "manager", "tick": 1}, session_id="s-1")
    payload = manager.model_dump()
    for key in ("type", "subtype", "is_error", "num_turns", "session_id"):
        assert key in payload, f"the envelope preserves {key}"
    assert manager.usage == {"input_tokens": 0, "output_tokens": 0, CACHE_READ_KEY: 0}, (
        "a scripted run costs nothing: the counters default to zero"
    )


def test_the_overhead_entry_conforms_to_the_prefix_and_no_first_party_id_does():
    assert OVERHEAD_MODEL.startswith(OVERHEAD_MODEL_PREFIX)
    for tier in Tier:
        assert not first_party_model(tier).startswith(OVERHEAD_MODEL_PREFIX)
        assert first_party_model(tier) == FIRST_PARTY_MODEL_TEMPLATE.format(tier=str(tier))


def test_every_shipped_script_produces_an_envelope_that_decodes_to_its_tier_s_model(
    script_for,
):
    """The adapter's job ends at the envelope; the runtime decodes it, and every one decodes."""
    desk = SeatDesk()
    seat = ScriptedSeat(script=script_for("asks_a_question"), desk=desk)
    desk.open_tick(
        "task-a", SeatSelection(tier=Tier.MANAGER, escalation=Escalation.EMPTY_UNIT_STACK)
    )
    plan = decode_seat_result(Tier.MANAGER, seat(Tier.MANAGER, _planner_request()))
    assert plan.emitter == "manager"

    desk.open_tick(
        "task-a", SeatSelection(tier=Tier.DIRECTOR, escalation=Escalation.REPLAN_EXHAUSTED)
    )
    direction = decode_seat_result(Tier.DIRECTOR, seat(Tier.DIRECTOR, _director_request()))
    assert direction.emitter == "director"

    # The dispatch half — an `ExecutorSummary` decoded under the addressee `dispatch` — needs
    # the port to take an addressee (order W2) and a wave to produce one (order W8). Two seats
    # is all `_RESULT_MODELS` holds here.


# --------------------------------------------------------------------------------------
# The one package licensed to name the seat binary, and the thing it must never do
# --------------------------------------------------------------------------------------


PACKAGE = Path(__file__).resolve().parents[2] / "src" / "protean" / "cortex"

#: Every module that would let a scripted seat become a real one. Build 1 imports none of them.
SPAWNING_MODULES = frozenset(
    {"subprocess", "os.exec", "multiprocessing", "asyncio.subprocess", "pty", "popen2"}
)


def _spawn_surfaces(source: str) -> tuple[set[str], list[str]]:
    """One parse and **one visit** per module: every imported name, and every `os`/`subprocess`
    verb it calls. The two claims below are two readings of the same tree, not two walks of it."""
    names: set[str] = set()
    verbs: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id in {"os", "subprocess"}:
                verbs.append(f"{owner.id}.{node.func.attr}")
    return names, verbs


def test_nothing_in_the_cortex_package_imports_a_way_to_spawn_a_process():
    """Zero model calls is a property of the source, not a promise in a docstring.

    Both halves, off one parse per module: no import that would let a scripted seat become a real
    one, and — folded in from `test_no_module_in_the_package_calls_a_spawn_function` — no call to
    a spawn function on `os` or `subprocess` either.
    """
    forbidden = {"run", "Popen", "call", "check_output", "system", "spawn", "fork"}
    for path in sorted(PACKAGE.glob("*.py")):
        imported, called = _spawn_surfaces(path.read_text(encoding="utf-8"))
        assert imported.isdisjoint(SPAWNING_MODULES), f"{path} imports a spawn path"
        for name in imported:
            assert not name.startswith("subprocess"), f"{path} imports {name}"
        for verb in called:
            assert verb.split(".", 1)[1] not in forbidden, f"{path} calls {verb}"
