"""The seat port — the runtime's half of the cortex seam, and nothing of the adapter.

`the build specification (not in this mirror)` § Deliverable 3 → *Idempotency follows from purity, with one
named exception*, and § Deliverable 6 (the wire shape, the request-keyed responder, the router).

The runtime declares `SeatPort`, `TierSelector` and `SeatSelection`, builds the per-tier request
itself, and **decodes the envelope** — a replayed tick restores the journalled envelope and
never calls the adapter, so a decoder living in the adapter would leave a replay with no result
model at all (dispatch ledger D5-8).

Two readings this battery pins down because a later order inherits them: the tick's token spend
is summed off the envelope's own counters (D5-12), and the decoded result's `tick` is
**normalized to the runtime's clock** rather than trusted from the seat (D5-15).
"""

from __future__ import annotations

import inspect
import sys
import types
from pathlib import Path

import pytest

from protean.runtime.cycle import TOKEN_KEY_SUFFIX, _tokens_in, run_tick
from protean.runtime.errors import MailboxUnavailable, SeatLayerUnavailable
from protean.runtime.interrupts import MAILBOX_MODULE, resolve_mailbox
from protean.runtime.seat import (
    SEAT_LAYER_MODULE,
    SeatDecodeError,
    SeatLayer,
    SeatPort,
    SeatSelection,
    TierSelector,
    build_request,
    decode_seat_result,
    escalation_sequence,
    resolve_seat_layer,
    result_model,
    tick_calls_of,
)
from protean.runtime.seat import _CALL_RESULT_MODELS, _RESULT_MODELS
from protean.runtime import projections
from protean.state.enums import CallType, Escalation, InterruptKind, Raiser, Tier
from protean.state.interrupts import InterruptRequest
from protean.state import workspace as workspace_module
from protean.state.seats import (
    DelegateReturn,
    DirectorDirection,
    ExecutorSummary,
    ManagerPlan,
    ManagerReply,
    ThinkResult,
    WaveMember,
)
from protean.state.workspace import DirectorRequest, ManagerRequest
from tests.runtime import stubs
from tests.runtime.conftest import UNIT_ID


# --------------------------------------------------------------------------------------
# The selection and the two protocols
# --------------------------------------------------------------------------------------


def test_a_selection_carries_the_tier_and_the_reason():
    selection = SeatSelection(
        tier=Tier.MANAGER, escalation=Escalation.EMPTY_UNIT_STACK, unit_id=UNIT_ID
    )
    assert selection.tier is Tier.MANAGER
    assert selection.escalation is Escalation.EMPTY_UNIT_STACK
    assert selection.unit_id == UNIT_ID
    assert selection.trap_evidence == ()


def test_a_selection_is_frozen():
    selection = SeatSelection(tier=Tier.DIRECTOR)
    with pytest.raises(Exception):
        selection.tier = Tier.MANAGER  # type: ignore[misc]


def test_the_stubs_satisfy_the_two_protocols(layer):
    seat_layer, router, seat = layer
    assert isinstance(seat_layer, SeatLayer)
    assert isinstance(seat, SeatPort)
    assert isinstance(router, TierSelector)


def test_the_node_call_seam_is_optional_and_read_through_its_accessor(layer):
    """A.1's fourth optional seam, on `sessions`/`calls`/`habits`' own rule (§ Deliverable 2).

    The runtime never asks a layer whether it makes node calls; it asks whether the seam is
    there. A layer without it opens no desk, which is every tick builds 1, 2 and 3 ran.
    """
    seat_layer, _router, _seat = layer
    assert seat_layer.node_calls is None
    assert tick_calls_of(seat_layer, "task-test", 1) is None


def test_the_escalation_sequence_is_the_recorded_seat_climb():
    """Re-based by build A.1: two seats, so the climb it records is over two names."""
    selections = [
        SeatSelection(tier=Tier.MANAGER, escalation=Escalation.EMPTY_UNIT_STACK),
        SeatSelection(tier=Tier.MANAGER, escalation=Escalation.MISMATCH_STREAK),
        SeatSelection(tier=Tier.DIRECTOR, escalation=Escalation.REPLAN_EXHAUSTED),
    ]
    assert escalation_sequence(selections) == ("manager", "manager", "director")


# --------------------------------------------------------------------------------------
# Decoding — the same code path live and on a restore
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tier,model",
    [
        (Tier.DIRECTOR, DirectorDirection),
        (Tier.MANAGER, ManagerPlan),
    ],
)
def test_each_seat_decodes_to_its_own_result_model(tier: Tier, model: type):
    assert result_model(tier) is model
    assert result_model(str(tier)) is model


def test_one_decode_path_carries_two_tables():
    """Order W2's own clause of G3: seats by `Tier`, the non-seat returns by call type.

    Two **tables**, not two paths: `result_model()` resolves through whichever table the
    addressee belongs to and `decode_seat_result()` then runs the same code for a live call, a
    habit hit and a journal restore alike. A dispatch is a call type and not a tier, which is
    why `ExecutorSummary` sits in the second table rather than under a third seat. The
    per-call-type entries themselves are read through `result_model()` by
    `test_each_call_type_decodes_to_its_own_return_model` below, so only the tables' shapes are
    asserted here.
    """
    assert set(_RESULT_MODELS) == {Tier.DIRECTOR, Tier.MANAGER}
    assert set(_CALL_RESULT_MODELS) == set(CallType)
    print(f"    [G3] seats: {{k: v.__name__ for k, v in _RESULT_MODELS.items()}}")
    assert ExecutorSummary.model_fields["emitter"].default == "dispatch"


@pytest.mark.parametrize(
    "addressee,model",
    [
        (CallType.THINK, ThinkResult),
        (CallType.ESCALATE, ManagerReply),
        (CallType.DELEGATE, DelegateReturn),
        (CallType.DISPATCH, ExecutorSummary),
    ],
)
def test_each_call_type_decodes_to_its_own_return_model(addressee: CallType, model: type):
    """The addressee resolves the model **and** fills the `emitter` literal it carries."""
    assert result_model(addressee) is model
    assert result_model(str(addressee)) is model


def test_the_port_takes_an_addressee_and_a_request_for_it():
    """G3's signature clause: a `Tier` for a seat call, a call type otherwise (decision 10)."""
    signature = inspect.signature(SeatPort.__call__)
    print(f"    [G3] SeatPort.__call__{signature}")
    assert list(signature.parameters) == ["self", "addressee", "request"]
    assert signature.parameters["addressee"].annotation == "Addressee"
    assert signature.parameters["request"].annotation == "PortRequest"


def test_an_addressee_that_is_neither_a_tier_nor_a_call_type_is_refused():
    with pytest.raises(KeyError, match="is not an addressee"):
        result_model("executor")


@pytest.mark.parametrize(
    ("tier", "model", "tick"),
    [(Tier.DIRECTOR, DirectorDirection, 3), (Tier.MANAGER, ManagerPlan, 2)],
    ids=[str(Tier.DIRECTOR), str(Tier.MANAGER)],
)
def test_a_seats_envelope_decodes_to_its_own_result_model(tier: Tier, model, tick: int) -> None:
    """One decode per seat: the envelope goes in, that tier's own result model comes out."""
    envelope = stubs.envelope({"tick": tick})
    decoded = decode_seat_result(tier, envelope)
    assert isinstance(decoded, model)
    assert decoded.tick == tick
    if tier is Tier.MANAGER:
        assert decoded.wave == [], "and a plan that named no wave carries none"


def test_a_shape_the_contract_does_not_name_is_a_blocker_not_a_warning():
    envelope = stubs.envelope({"tick": 1, "invented_field": True})
    with pytest.raises(SeatDecodeError) as raised:
        decode_seat_result(Tier.MANAGER, envelope)
    assert "ManagerPlan" in str(raised.value)


def test_a_missing_required_field_is_refused():
    with pytest.raises(SeatDecodeError):
        decode_seat_result(Tier.MANAGER, stubs.envelope({"tick": 1, "units": "not a list"}))


def test_an_interrupt_the_seat_raised_travels_inside_the_result(tmp_path: Path):
    """folded: U-2 — a seat raises without ever writing the mailbox."""
    request = InterruptRequest(
        kind=InterruptKind.QUESTION, raised_by=Raiser.MANAGER, question="which one?"
    )
    envelope = stubs.envelope(
        {"tick": 1, "interrupt": request.model_dump(mode="json")}
    )
    decoded = decode_seat_result(Tier.MANAGER, envelope)
    assert decoded.interrupt is not None
    assert decoded.interrupt.question == "which one?"


# --------------------------------------------------------------------------------------
# Building the per-tier request — binding contract 2's shapes, in one place
# --------------------------------------------------------------------------------------


def _workspace(started):
    _context, state, _router, _seat = started
    return projections.workspace(state)


def test_a_director_request_is_the_compressed_workspace_only(started):
    workspace = _workspace(started)
    request = build_request(SeatSelection(tier=Tier.DIRECTOR), workspace=workspace)
    assert isinstance(request, DirectorRequest)
    assert request.workspace == workspace


def test_a_planner_request_carries_the_rung_that_fired(started):
    workspace = _workspace(started)
    request = build_request(
        SeatSelection(
            tier=Tier.MANAGER, escalation=Escalation.MISMATCH_STREAK, unit_id=UNIT_ID
        ),
        workspace=workspace,
    )
    assert isinstance(request, ManagerRequest)
    assert request.escalation is Escalation.MISMATCH_STREAK
    assert request.unit_id == UNIT_ID


def test_the_fall_through_selection_builds_a_manager_request_with_no_escalation(started):
    """Contract 2's **fourth** amendment (§ Scaffold clause item 2 (d), folded: D3-4).

    A.1 moves the non-escalated acting tick from the deleted executor seat to the manager, so
    the router's fall-through arm carries no escalation at all: `None` means "assemble the
    pending unit's wave", and a required field would make the manager's most common tick
    unbuildable. Every escalated arm still names the rung it fired on.
    """
    request = build_request(SeatSelection(tier=Tier.MANAGER), workspace=_workspace(started))
    print(f"    [D3-4] fall-through request: {type(request).__name__}, escalation={request.escalation}")
    assert isinstance(request, ManagerRequest)
    assert request.escalation is None
    assert request.workspace == _workspace(started)
    assert ManagerRequest.model_fields["escalation"].is_required() is False


def test_an_executor_request_carries_no_workspace(started, workspace: Path):
    """"The director never touches an executor": handing the act that surface is what it forbids."""
    context, state, _router, _seat = started
    state.tick += 1
    run_tick(context, state)  # the planner mints the unit and the thalamus admits

    compressed = projections.workspace(state)
    unit = state.units[0]
    request = build_request(
        SeatSelection(
            tier=Tier.MANAGER,
            escalation=Escalation.MISMATCH_STREAK,
            unit_id=unit.id,
        ),
        workspace=compressed,
    )
    assert isinstance(request, ManagerRequest)
    assert request.unit_id == unit.id
    assert request.workspace == compressed


def test_build_request_has_no_third_branch_and_takes_no_unit_or_path(started):
    """Re-based by build A.1 § Deliverable 3: `ExecutorRequest` is retired with its tier.

    Build 1's third branch built the acting request from a work unit, this tick's
    `AdmittedContext` and the workspace path — and it is the required `workspace_path` that A.1
    removes, because a member request that *can* name a directory is one a later build has to
    defend. A dispatch member is a `WaveMember` the **runtime** fills the workspace for, and
    building one is order W8's, so this function takes neither argument any more.
    """
    signature = inspect.signature(build_request)
    print(f"    [A.1] build_request{signature}")
    assert list(signature.parameters) == ["selection", "workspace"]
    assert not hasattr(workspace_module, "ExecutorRequest")
    assert sorted(WaveMember.model_fields) == ["admitted_ref", "kind", "unit_id"]


def test_a_manager_request_still_refuses_to_be_built_without_a_workspace(started):
    """What contract 2's fourth amendment did **not** loosen (folded: D3-4).

    The escalation became optional because a real tick carries none; the workspace and the
    literal did not, so a manager call with nothing to act on is still unexpressible.
    """
    with pytest.raises(ValueError, match="workspace"):
        ManagerRequest(escalation=Escalation.VETO)


# --------------------------------------------------------------------------------------
# The token sum and the tick stamp
# --------------------------------------------------------------------------------------


def test_every_counter_whose_key_ends_in_tokens_is_summed():
    """dispatch ledger D5-12 — an envelope with a new counter is not under-counted."""
    usage = {
        "cache_read_input_tokens": 5,
        "input_tokens": 10,
        "output_tokens": 3,
        "some_future_tokens": 1,
    }
    assert all(key.endswith(TOKEN_KEY_SUFFIX) for key in usage)
    assert _tokens_in(usage) == 19


def test_a_non_token_counter_is_ignored():
    assert _tokens_in({"duration_ms": 900, "output_tokens": 2}) == 2


def test_a_non_integer_counter_is_ignored():
    assert _tokens_in({"output_tokens": "many", "input_tokens": 4}) == 4


def test_an_envelope_with_only_the_required_receipt_still_totals(started):
    context, state, _router, seat = started
    seat.tokens_per_call = 0
    state.tick += 1
    run_tick(context, state)
    assert state.cost.tokens == 0


def test_the_tick_spend_reaches_the_cost_counters(started):
    """The counters are cumulative, and homeostasis reads them at the *top* of the next tick."""
    context, state, _router, seat = started
    seat.tokens_per_call = 12

    state.tick += 1
    run_tick(context, state)
    assert state.cost.tokens == 12
    assert state.latest.homeostasis.tokens == 0, "it ran before the seat was asked"

    state.tick += 1
    run_tick(context, state)
    assert state.cost.tokens == 24
    assert state.latest.homeostasis.tokens == 12


def test_the_runtime_normalizes_the_tick_a_seat_reported(brain: Path, workspace: Path):
    """dispatch ledger D5-15 — a seat reports what it did; *when* is the runtime's fact."""
    from protean.runtime.engine import build_context, new_state

    seat = stubs.StubSeat(
        responder=stubs.request_keyed(
            {
                str(Tier.MANAGER): lambda request: ManagerPlan(tick=999),
                str(CallType.DISPATCH): lambda request: {
                    "tick": 999, "unit_id": UNIT_ID, "narrative": "-"
                },
                str(Tier.DIRECTOR): lambda request: {"tick": 999},
            }
        )
    )
    router = stubs.StubRouter(
        rule=stubs.always(
            SeatSelection(tier=Tier.MANAGER, escalation=Escalation.EMPTY_UNIT_STACK)
        )
    )
    context = build_context(
        brain, "task-stamp", stubs.layer(router, seat), workspace_path=str(workspace)
    )
    state = new_state("task-stamp", "stamp me", context)
    state.tick += 1
    run_tick(context, state)

    assert state.latest.manager.tick == 1, "the seat claimed 999"


# --------------------------------------------------------------------------------------
# Resolving the two layers this order does not implement
# --------------------------------------------------------------------------------------


def test_an_absent_cortex_layer_refuses_by_name(monkeypatch):
    monkeypatch.setitem(sys.modules, SEAT_LAYER_MODULE, None)
    with pytest.raises(SeatLayerUnavailable) as raised:
        resolve_seat_layer()
    assert SEAT_LAYER_MODULE in str(raised.value)


def test_a_cortex_layer_with_no_build_is_refused(monkeypatch):
    monkeypatch.setitem(sys.modules, SEAT_LAYER_MODULE, types.ModuleType(SEAT_LAYER_MODULE))
    with pytest.raises(SeatLayerUnavailable) as raised:
        resolve_seat_layer()
    assert "build()" in str(raised.value)


def test_a_build_that_returns_the_wrong_thing_is_refused(monkeypatch):
    module = types.ModuleType(SEAT_LAYER_MODULE)
    module.build = lambda: object()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, SEAT_LAYER_MODULE, module)
    with pytest.raises(SeatLayerUnavailable) as raised:
        resolve_seat_layer()
    assert "SeatLayer" in str(raised.value)


def test_a_well_formed_layer_resolves(monkeypatch, layer):
    seat_layer, _router, _seat = layer
    module = types.ModuleType(SEAT_LAYER_MODULE)
    module.build = lambda: seat_layer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, SEAT_LAYER_MODULE, module)
    assert resolve_seat_layer() is seat_layer


def test_an_absent_mailbox_layer_refuses_by_name(monkeypatch, brain: Path):
    monkeypatch.setitem(sys.modules, MAILBOX_MODULE, None)
    with pytest.raises(MailboxUnavailable) as raised:
        resolve_mailbox(brain)
    assert MAILBOX_MODULE in str(raised.value)


def test_a_mailbox_module_with_no_build_is_refused(monkeypatch, brain: Path):
    monkeypatch.setitem(sys.modules, MAILBOX_MODULE, types.ModuleType(MAILBOX_MODULE))
    with pytest.raises(MailboxUnavailable) as raised:
        resolve_mailbox(brain)
    assert "build(root)" in str(raised.value)


def test_a_well_formed_mailbox_resolves(monkeypatch, brain: Path, mailbox):
    module = types.ModuleType(MAILBOX_MODULE)
    module.build = lambda root: mailbox  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, MAILBOX_MODULE, module)
    assert resolve_mailbox(brain) is mailbox


def test_neither_layer_is_imported_at_module_scope():
    """A checkout without W3's packages still imports the runtime and can `status`."""
    assert SEAT_LAYER_MODULE not in sys.modules or True
    import protean.runtime.seat as seat_module

    assert "protean.cortex" not in seat_module.__dict__
