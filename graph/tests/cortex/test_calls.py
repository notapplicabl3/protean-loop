"""The three call types as three callers of one port — row G3, and row M3's own check.

`the build specification (not in this mirror)` § Deliverable 2 (the three-type table, C1 `NodeCall`, the
addressee-keyed port, "a call mints no cortex prediction", session-lessness, and every fault on
a think/escalate/delegate being a signal), § Deliverable 5's session-mechanics clause, and
§ Directional decisions 4, 6 and 10.

What this battery pins down, clause by clause:

* think, escalate and delegate each construct a typed `NodeCall` and reach the model through the
  **one** `(addressee, request) -> SeatEnvelope` — three callers, never three ports;
* every one of them decodes through the single `decode_seat_result()`, whose one path carries
  two tables, and each lands on **its own** return model;
* a call mints a fresh `--session-id`, writes no `seat_sessions` entry and carries `ref is None`,
  and `BrainState.seat_sessions` still refuses by name any key outside `config.TIERS`;
* every fault — a cap exceeded, an illegal return, a missing configuration, a call failure —
  returns a **refusal to the calling node**, which proceeds without the answer;
* row **M3**: the scripted layer answers all four call-type addressees beside the two seats, and
  the seams stay optional, read through the `*_of()` accessors rather than by asking the layer
  what kind of layer it is.

**Zero model calls.** Every answer here comes from the scripted transport under
`fixtures/calls/`, and the delegate and dispatch answers are scripted returns with no process
behind them (row G12).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protean import config
from protean.cortex.adapters import ScriptedSeat, SeatDesk, build_envelope
from protean.cortex.calls import (
    REFUSAL_CALL_FAILED,
    REFUSAL_CAP_EXCEEDED,
    REFUSAL_CLASSES,
    REFUSAL_ILLEGAL_RETURN,
    REFUSAL_NO_CONFIGURATION,
    CallConfigurationError,
    CallRefusal,
    NodeCallDesk,
    parse_plan,
)
from protean.cortex.layer import build_layer
from protean.cortex.live.session import LiveSessionBook, call_session
from protean.cortex.scripts import load_script
from protean.mailbox.files import build as build_mailbox
from protean.runtime import engine
from protean.runtime.errors import SeatUnavailable
from protean.runtime.seat import (
    SeatLayer,
    SeatPort,
    calls_of,
    decode_seat_result,
    tick_calls_of,
)
from protean.state.brain_state import BrainState
from protean.state.calls import NodeCall
from protean.state.enums import CallType, NodeName, Tier
from protean.state.seats import (
    DelegateReturn,
    ExecutorSummary,
    ManagerReply,
    SeatEnvelope,
    ThinkResult,
)
from tests.conftest import tagged_show

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The scripted transport every later leg's call fixtures start from.
CALL_SCRIPT = REPO_ROOT / "fixtures" / "calls" / "three_call_types.yaml"

TASK = "task-calls"


show = tagged_show("G3")


# --------------------------------------------------------------------------------------
# The transports this battery drives the port with
# --------------------------------------------------------------------------------------


class RecordingPort:
    """A `SeatPort` that answers from a per-addressee payload map and records what it took."""

    def __init__(self, answers: dict[CallType | Tier, dict]) -> None:
        self.answers = answers
        self.taken: list[tuple[object, object]] = []

    def __call__(self, addressee, request) -> SeatEnvelope:
        self.taken.append((addressee, request))
        return build_envelope(addressee, self.answers[addressee], session_id=call_session())


class FaultyPort:
    """A `SeatPort` that fails the way one named fault fails."""

    def __init__(self, fault: Exception) -> None:
        self.fault = fault
        self.taken: list[object] = []

    def __call__(self, addressee, request) -> SeatEnvelope:
        self.taken.append(addressee)
        raise self.fault


ANSWERS = {
    CallType.THINK: {"answer": "cheap so far", "confidence": 0.6},
    CallType.ESCALATE: {"answer": "keep admitting"},
    CallType.DELEGATE: {"kind": "reviewer", "verdict": "wide enough"},
    CallType.DISPATCH: {"unit_id": "u-calls-1", "narrative": "scripted"},
}


@pytest.fixture()
def desk() -> NodeCallDesk:
    """One tick's desk over a recording transport."""
    return NodeCallDesk(port=RecordingPort(dict(ANSWERS)), task=TASK, tick=3)


# --------------------------------------------------------------------------------------
# Three callers of one port
# --------------------------------------------------------------------------------------


def test_the_three_types_are_three_callers_of_the_one_port(desk: NodeCallDesk) -> None:
    """Decision 10: one `(addressee, request) -> SeatEnvelope`, never three ports."""
    assert isinstance(desk.port, SeatPort)
    desk.think(NodeName.HOMEOSTASIS, "is this tick near the ceiling?")
    desk.escalate(NodeName.THALAMUS, "the admitted set looks thin")
    desk.delegate(NodeName.HIPPOCAMPUS, "reviewer", "anything contradicting the unit?")

    addressed = [str(addressee) for addressee, _request in desk.port.taken]
    show("addressees the one port took", addressed)
    assert addressed == ["think", "escalate", "delegate"]
    assert all(isinstance(request, NodeCall) for _a, request in desk.port.taken)


def test_each_call_type_decodes_to_its_own_return_model_off_the_one_path(
    desk: NodeCallDesk,
) -> None:
    """G3: two tables, one `decode_seat_result()` path, one return model per call type."""
    answers = (
        desk.think(NodeName.HOMEOSTASIS, "q"),
        desk.escalate(NodeName.THALAMUS, "c"),
        desk.delegate(NodeName.HIPPOCAMPUS, "reviewer", "q"),
    )
    show("returns", [type(item).__name__ for item in answers])
    assert isinstance(answers[0], ThinkResult)
    assert isinstance(answers[1], ManagerReply)
    assert isinstance(answers[2], DelegateReturn)
    assert [str(item.emitter) for item in answers] == ["think", "escalate", "delegate"]
    assert all(item.tick == 3 for item in answers), "the runtime's clock, not the seat's"


def test_a_dispatch_envelope_decodes_to_an_executor_summary_emitting_dispatch() -> None:
    """G3's last decode row: the executor seat died and this model lived (decision 16)."""
    envelope = build_envelope(CallType.DISPATCH, ANSWERS[CallType.DISPATCH], session_id="s")
    decoded = decode_seat_result(CallType.DISPATCH, envelope, 3)
    show("ExecutorSummary.emitter", ExecutorSummary.model_fields["emitter"].default)
    assert isinstance(decoded, ExecutorSummary)
    assert str(decoded.emitter) == "dispatch"


def test_a_call_carries_its_typed_payload_and_names_the_model_it_came_from(
    desk: NodeCallDesk,
) -> None:
    """C1's payload, as ruled: the request dumped, with the model it was dumped from beside it."""
    desk.think(NodeName.HOMEOSTASIS, "is this tick near the ceiling?", context="the counters")
    call = desk.records[0].call
    show("payload", f"{call.payload_model} {call.payload}")
    assert call.payload_model == "ThinkPayload"
    assert call.payload == {"question": "is this tick near the ceiling?", "context": "the counters"}
    assert call.type is CallType.THINK and call.addressee is CallType.THINK
    assert call.node is NodeName.HOMEOSTASIS and call.tick == 3


def test_the_call_number_is_per_node_within_the_tick_and_starts_at_one(
    desk: NodeCallDesk,
) -> None:
    """The journal key is `(task, tick, node, call#)` and `call# = 0` is the output entry's."""
    desk.think(NodeName.HOMEOSTASIS, "one")
    desk.think(NodeName.HOMEOSTASIS, "two")
    desk.escalate(NodeName.THALAMUS, "one")
    numbers = {
        str(record.call.node): [item.call.call_number for item in desk.calls_for(record.call.node)]
        for record in desk.records
    }
    show("call# per node", numbers)
    assert numbers["homeostasis"] == [1, 2]
    assert numbers["thalamus"] == [1]


def test_a_call_carries_no_ref_because_it_mints_no_cortex_prediction(
    desk: NodeCallDesk,
) -> None:
    """folded: S-A9 — the cortex trace keeps one prediction per seat per tick."""
    desk.think(NodeName.HOMEOSTASIS, "q")
    desk.escalate(NodeName.THALAMUS, "c")
    desk.delegate(NodeName.HIPPOCAMPUS, "reviewer", "q")
    show("refs", [record.ref for record in desk.records])
    assert [record.ref for record in desk.records] == [None, None, None]


# --------------------------------------------------------------------------------------
# Every fault is a signal, not a stop
# --------------------------------------------------------------------------------------


def test_the_refusal_classes_are_the_four_the_deliverable_names() -> None:
    assert REFUSAL_CLASSES == (
        REFUSAL_CAP_EXCEEDED,
        REFUSAL_ILLEGAL_RETURN,
        REFUSAL_NO_CONFIGURATION,
        REFUSAL_CALL_FAILED,
    )


def test_an_illegal_return_is_a_refusal_to_the_calling_node() -> None:
    """A shape the contract does not name: refused, and the tick carries on."""
    desk = NodeCallDesk(
        port=RecordingPort({CallType.THINK: {"invented_field": True}}), task=TASK, tick=1
    )
    answer = desk.think(NodeName.HOMEOSTASIS, "q")
    show("illegal return", f"{answer.reason}: {answer.detail[:60]}")
    assert isinstance(answer, CallRefusal)
    assert answer.reason == REFUSAL_ILLEGAL_RETURN
    assert desk.records[0].refused and desk.records[0].result is None


def test_a_missing_configuration_is_a_refusal_to_the_calling_node() -> None:
    """A layer with no answer for this addressee: the node proceeds without one."""
    desk = NodeCallDesk(
        port=FaultyPort(CallConfigurationError("no think block")), task=TASK, tick=1
    )
    answer = desk.think(NodeName.HOMEOSTASIS, "q")
    assert isinstance(answer, CallRefusal) and answer.reason == REFUSAL_NO_CONFIGURATION


def test_a_call_failure_never_reaches_seat_unavailable() -> None:
    """The classes that end the task are a seat call's and a dispatch member's (order W8)."""
    desk = NodeCallDesk(
        port=FaultyPort(SeatUnavailable(tier="think", reason="the CLI exited non-zero")),
        task=TASK,
        tick=1,
    )
    answer = desk.delegate(NodeName.HIPPOCAMPUS, "reviewer", "q")
    show("call failure", answer.reason)
    assert isinstance(answer, CallRefusal) and answer.reason == REFUSAL_CALL_FAILED


def test_a_cap_exceeded_refuses_under_its_own_class(desk: NodeCallDesk) -> None:
    """Row G10's cap is order W3's to enforce; the class it refuses under is closed here."""
    call = desk.build_call(NodeName.HOMEOSTASIS, CallType.THINK, _think_payload())
    refusal = desk.refuse(call, REFUSAL_CAP_EXCEEDED, detail="max_call_usd")
    assert refusal.reason == REFUSAL_CAP_EXCEEDED
    assert desk.records[-1].refused
    with pytest.raises(ValueError, match="refusal carries one of"):
        CallRefusal(call=call, reason="invented")


def test_a_refused_call_does_not_stop_the_next_one() -> None:
    """"which proceeds without the answer" — the node keeps its place in the tick."""
    port = RecordingPort({**ANSWERS, CallType.THINK: {"invented_field": True}})
    desk = NodeCallDesk(port=port, task=TASK, tick=1)
    first = desk.think(NodeName.HOMEOSTASIS, "q")
    second = desk.escalate(NodeName.HOMEOSTASIS, "c")
    assert isinstance(first, CallRefusal) and isinstance(second, ManagerReply)
    assert [record.call.call_number for record in desk.calls_for(NodeName.HOMEOSTASIS)] == [1, 2]


def _think_payload():
    from protean.cortex.calls import ThinkPayload

    return ThinkPayload(question="q")


# --------------------------------------------------------------------------------------
# Session-lessness, from both sides
# --------------------------------------------------------------------------------------


def test_a_non_seat_call_mints_a_fresh_session_per_invocation() -> None:
    """§ Deliverable 5's clause: mint-resume-discard for the two seats, **none** for the rest."""
    seat = ScriptedSeat(script=load_script(CALL_SCRIPT), desk=SeatDesk())
    call = NodeCall(
        type=CallType.THINK,
        node=NodeName.HOMEOSTASIS,
        tick=1,
        call_number=1,
        addressee=CallType.THINK,
    )
    first = seat(CallType.THINK, call)
    second = seat(CallType.THINK, call)
    show("two think handles", [first.session_id, second.session_id])
    assert first.session_id != second.session_id, "fresh per invocation"
    assert seat.desk.sessions.handles == {}, "nothing was written to the book"


def test_the_session_book_refuses_a_call_type_by_name() -> None:
    """The book is keyed by tier; a call type cannot acquire a handle in it."""
    book = LiveSessionBook()
    book.open_task(TASK)
    assert sorted(book.handles) == sorted(config.TIERS)
    with pytest.raises(ValueError):
        book.handle(CallType.THINK)


def test_seat_sessions_still_refuses_any_key_outside_config_tiers() -> None:
    """Contract 1's validator, unwidened: the key set shrank with `TIERS` and by nothing else."""
    state = BrainState(task_id=TASK, seat_sessions={tier: f"s-{tier}" for tier in config.TIERS})
    assert sorted(state.seat_sessions) == sorted(config.TIERS)
    with pytest.raises(ValueError, match="seat_sessions is keyed by tier"):
        BrainState(task_id=TASK, seat_sessions={**state.seat_sessions, "think": "s-think"})


# --------------------------------------------------------------------------------------
# Row M3 — the scripted layer answers all four addressees, and the seams stay optional
# --------------------------------------------------------------------------------------


def test_the_scripted_layer_answers_all_four_call_type_addressees() -> None:
    """M3, first half. The delegate and dispatch answers have no process behind them."""
    seat = ScriptedSeat(script=load_script(CALL_SCRIPT), desk=SeatDesk())
    decoded = {}
    for call_type in CallType:
        call = NodeCall(
            type=call_type,
            node=NodeName.HIPPOCAMPUS,
            tick=2,
            call_number=1,
            addressee=call_type,
        )
        decoded[str(call_type)] = type(decode_seat_result(call_type, seat(call_type, call), 2)).__name__
    show("four addressees", decoded)
    assert decoded == {
        "think": "ThinkResult",
        "escalate": "ManagerReply",
        "delegate": "DelegateReturn",
        "dispatch": "ExecutorSummary",
    }


def test_the_seams_stay_optional_and_are_read_through_the_accessors() -> None:
    """M3, second half — the `*_of()` pattern: ask whether the seam is there, never what the
    layer is. A layer with no delegate answer writes no `SubagentSpawn`, exactly as a layer
    with no `calls` seam writes no `SeatCallRecord`."""
    bare = SeatLayer(router=lambda workspace: None, port=RecordingPort({}))
    assert bare.node_calls is None and bare.calls is None
    assert tick_calls_of(bare, TASK, 1) is None, "no seam, no desk, no call"
    assert calls_of(bare) == (), "no seam, no receipt"


def test_a_dispatch_is_not_an_outer_nodes_call_to_make() -> None:
    """Three possibilities per outer node and no fourth: `dispatch` is the manager's wave."""
    with pytest.raises(CallConfigurationError, match="dispatch"):
        parse_plan([{"node": "thalamus", "type": "dispatch", "payload": {}}])


def test_a_plan_naming_a_field_no_payload_carries_is_refused_at_load() -> None:
    with pytest.raises(ValueError):
        parse_plan([{"node": "thalamus", "type": "think", "payload": {"invented": 1}}])


# --------------------------------------------------------------------------------------
# The dry run: a scripted transport answering all three on a fixture brain root
# --------------------------------------------------------------------------------------


def test_a_dry_run_answers_all_three_call_types_and_commits_two_seat_sessions(
    brain: Path, workspace: Path
) -> None:
    """G3, end to end on a **fixture** brain root, one tick, zero model calls.

    The three calls are made at three different nodes' steps, each decodes to its own return
    model off the one path, each carries `ref is None`; the committed checkpoint holds the two
    tier keys and nothing else; and the cortex's own prediction is the tick's **only** one, which
    is what "a call mints no cortex prediction" means on disk.
    """
    layer = build_layer(root=brain, script=load_script(CALL_SCRIPT))
    outcome = engine.start(
        brain,
        "write notes.md",
        layer,
        mailbox=build_mailbox(brain),
        workspace_path=str(workspace),
        task_id=TASK,
        max_ticks=1,
    )

    (desk,) = layer.node_calls.opened
    made = [
        (str(record.call.node), str(record.call.type), record.call.call_number, record.ref,
         type(record.result).__name__)
        for record in desk.records
    ]
    show("the tick's calls", made)
    assert made == [
        ("homeostasis", "think", 1, None, "ThinkResult"),
        ("hippocampus", "delegate", 1, None, "DelegateReturn"),
        ("thalamus", "escalate", 1, None, "ManagerReply"),
    ]

    committed = json.loads(
        (brain / "state" / TASK / "checkpoint.json").read_text(encoding="utf-8")
    )["state"]
    show("committed seat_sessions", sorted(committed["seat_sessions"]))
    assert sorted(committed["seat_sessions"]) == sorted(config.TIERS)

    cortex_predictions = [
        write.key
        for tick in outcome.ticks
        for write in tick.receipt.writes
        if write.kind == "trace.prediction" and ":cortex:" in write.key
    ]
    show("cortex predictions this tick", cortex_predictions)
    assert cortex_predictions == [f"{TASK}:1:cortex:manager:prediction"]
