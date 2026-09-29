"""G5a — Option A made mechanical: the call type × shape table, and the tier-three record.

`the build specification (not in this mirror)` § Deliverable 3 ("The manager is the sole conductor of the
workspace", and where `dispatch_id` lives) and § Deliverable 4 (the legal-return table checked
**before** the decoder and after the one unchanged retry, the two-artifact split, and the member
request that carries no path).

**Nothing here spawns and no kind process exists.** Every return is scripted, and the module
asserts the *shape* of a tier-three call and nothing about how one is created or contained — the
`kinds:` container, the containment floor, the spawn ceiling, the wave-width bound, per-member
port instances and the workspace-path refusal at spawn are all build A.1.i's (§ Out of scope).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from protean import config
from protean.cortex.adapters import ScriptedSeat, SeatDesk
from protean.cortex.calls import CallDesks, NodeCallDesk, REFUSAL_ILLEGAL_RETURN
from protean.cortex.ladder import LadderWeights
from protean.cortex.router import LadderRouter
from protean.cortex.scripts import load_script
from protean.cortex.subagents import (
    KIND_KEY,
    SPAWN_CALL_TYPES,
    MemberFacts,
    member_facts,
    spawn_of,
    spawns_in,
)
from protean.runtime.cycle import WAVE_CALL_NUMBER, run_tick
from protean.runtime.engine import build_context, new_state
from protean.runtime.journal import load as load_journal
from protean.runtime.seat import (
    LEGAL_RETURNS,
    IllegalReturn,
    SeatDecodeError,
    SeatLayer,
    check_legal_return,
    decode_seat_result,
    emitter_of,
    legal_return,
)
from protean.state.calls import (
    SPAWN_JOURNAL_FIELDS,
    SPAWN_LICENSED_DUPLICATES,
    SPAWN_RECEIPT_FIELDS,
    SubagentSpawn,
)
from protean.state.enums import CallType, NodeName, TerminalState, Tier
from protean.state.primitives import UnitObservation
from protean.state.seat_calls import load_seat_calls
from protean.state.seats import (
    DelegateReturn,
    DirectorDirection,
    ExecutorSummary,
    ManagerPlan,
    ManagerReply,
    ThinkResult,
    WaveMember,
)
from tests.conftest import tagged_show
from tests.runtime import stubs

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures" / "calls"

GOAL = "read the ledger and report"

#: The shape the positive control smuggles: a perfectly legal `ExecutorSummary`, on a delegate.
SMUGGLED = {
    "emitter": str(CallType.DISPATCH),
    "unit_id": "u-refusal-1",
    "narrative": "wrote the report myself",
    "observations": [
        {"path": "report.md", "exists": True, "size_bytes": 64, "content_hash": "sha-x"}
    ],
    "exit_code": 0,
    "cited_ids": [],
}


show = tagged_show("W8-subagents")


def layer_for(brain: Path, fixture: str):
    """`build_layer()`'s own shape over one calls fixture."""
    script = load_script(FIXTURES / f"{fixture}.yaml")
    desk = SeatDesk()
    seat = ScriptedSeat(script=script, desk=desk)
    return SeatLayer(
        router=LadderRouter(weights=LadderWeights.load(brain), on_tick=desk.open_tick),
        port=seat,
        sessions=desk.sessions,
        node_calls=CallDesks(port=seat, plan=script.calls),
    )


def hashes_of(directory: Path) -> dict[str, str]:
    """Per-file sha256 over a whole tree — the read-only proof's own shape."""
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


# --------------------------------------------------------------------------------------
# The call type × shape table: all four call types and the two seats
# --------------------------------------------------------------------------------------


def test_the_table_carries_all_four_call_types_and_the_two_seats() -> None:
    """A two-row table would refuse every think and escalate return (§ Deliverable 4)."""
    show("the table", {str(key): value.__name__ for key, value in LEGAL_RETURNS.items()})
    assert LEGAL_RETURNS == {
        Tier.DIRECTOR: DirectorDirection,
        Tier.MANAGER: ManagerPlan,
        CallType.THINK: ThinkResult,
        CallType.ESCALATE: ManagerReply,
        CallType.DELEGATE: DelegateReturn,
        CallType.DISPATCH: ExecutorSummary,
    }
    assert set(LEGAL_RETURNS) == set(
        [Tier(name) for name in config.TIERS] + [CallType(name) for name in config.CALL_TYPES]
    )
    for addressee, model in LEGAL_RETURNS.items():
        assert legal_return(str(addressee)) is model
        assert emitter_of(model) == str(addressee), "the literal is the addressee's own name"


def test_anything_outside_the_table_is_refused_before_it_reaches_the_decoder() -> None:
    with pytest.raises(KeyError):
        legal_return("executor")
    with pytest.raises(KeyError):
        check_legal_return("planner", {"emitter": "planner"})


def test_the_positive_control_is_refused_by_the_table_and_earns_no_retry() -> None:
    """An `ExecutorSummary`-shaped return arriving on a **delegate** (§ Deliverable 4).

    A shape-only check would pass it: it *is* a legal `ExecutorSummary`. The refusal is
    `IllegalReturn` and deliberately **not** a `SeatDecodeError`, because build 2's one retry
    catches the latter — "a legal shape addressed to the wrong call type is not a decode failure
    and earns no retry".
    """
    with pytest.raises(IllegalReturn) as refused:
        check_legal_return(CallType.DELEGATE, SMUGGLED)
    show("refusal", str(refused.value))
    assert not isinstance(refused.value, SeatDecodeError), "so the retry never fires"
    assert str(CallType.DELEGATE) in str(refused.value)
    assert str(CallType.DISPATCH) in str(refused.value)


def test_a_legal_think_and_a_legal_escalate_both_pass_the_same_table() -> None:
    check_legal_return(CallType.THINK, {"emitter": "think", "answer": "yes"})
    check_legal_return(CallType.ESCALATE, {"emitter": "escalate", "answer": "later"})
    check_legal_return(CallType.DISPATCH, SMUGGLED)


def test_a_return_that_names_no_shape_reaches_the_decoder_where_build_2_left_it() -> None:
    """A live seat is handed a narrowed schema and answers without the literal; the runtime
    fills it in `decode_seat_result()`, so the table lets a nameless payload through to the
    shape check and its one retry — which is the path build 2 landed and A.1 does not touch."""
    check_legal_return(CallType.THINK, {"answer": "no emitter here"})
    decoded = decode_seat_result(
        CallType.THINK, stubs.envelope({"answer": "no emitter here"}), 4
    )
    assert isinstance(decoded, ThinkResult) and decoded.tick == 4


def test_the_delegate_return_has_no_observation_field_at_all() -> None:
    """Option A's refusal is **structural** in the model (folded: S-A84)."""
    show("DelegateReturn fields", sorted(DelegateReturn.model_fields))
    assert "observations" not in DelegateReturn.model_fields
    assert "unit_id" not in DelegateReturn.model_fields


# --------------------------------------------------------------------------------------
# G5a's fixture: a delegate that returns a workspace-changing payload
# --------------------------------------------------------------------------------------


@pytest.fixture()
def refused(brain: Path, workspace: Path):
    """One pass of `option_a_refusal` on a **fixture** brain root, hashed before and after."""
    layer = layer_for(brain, "option_a_refusal")
    context = build_context(brain, "task-optiona", layer, workspace_path=str(workspace))
    state = new_state("task-optiona", GOAL, context)
    before = hashes_of(workspace)
    state.tick += 1
    result = run_tick(context, state)
    return context, state, result, before, hashes_of(workspace)


def test_the_delegate_s_workspace_changing_payload_is_refused_by_name(refused) -> None:
    context, _state, _result, _before, _after = refused
    entries = load_journal(context.paths.journal(1))
    delegate = next(
        entry for entry in entries if entry.tier is CallType.DELEGATE and entry.is_call()
    )
    show("the delegate's journalled entry", delegate.model_dump(mode="json")["tier"])
    assert delegate.envelope is None, "a refused call journals no restorable result"
    assert delegate.payload["kind"] == "writer"


def test_the_refused_payload_contributes_nothing_to_committed_state(refused) -> None:
    context, state, result, _before, _after = refused
    committed = json.loads(context.paths.checkpoint.read_text(encoding="utf-8"))
    show("latest slots", sorted(k for k, v in committed["state"]["latest"].items() if v))
    assert state.latest.dispatch is None, "no observation reached the dispatch slot"
    assert committed["state"]["path_baselines"] == {}, "and no path baseline moved"
    assert "sha-report-smuggled" not in json.dumps(committed)
    # **And the boundary still commits**: a refusal does not abort the tick (folded: S-A12).
    assert result.receipt is not None
    assert committed["state"]["tick"] == 1


def test_the_workspace_the_payload_claimed_to_have_changed_is_byte_identical(refused) -> None:
    """The hash clause, read against the tree the refused payload claimed to have written.

    G5a asks for "a brain-root hash left unchanged". The brain root *must* change on the pass —
    the same row requires the boundary to commit, and a commit writes the checkpoint, the
    journal, the traces and the episodes — so what the hash can hold still is the tree the
    refusal was about: the task's **workspace**, which the payload named a file in. The brain
    root's own change is asserted beside it, as the commit it is.
    """
    context, _state, _result, before, after = refused
    show("workspace files", sorted(after))
    assert after == before, "the refused payload wrote nothing"
    assert "report.md" not in {Path(name).name for name in after}
    assert context.paths.checkpoint.is_file(), "while the boundary committed"


def test_the_two_legal_calls_on_the_same_pass_are_answered(refused) -> None:
    context, _state, _result, _before, _after = refused
    entries = [
        entry for entry in load_journal(context.paths.journal(1)) if entry.is_call()
    ]
    answered = {str(entry.tier): entry.envelope is not None for entry in entries}
    show("answered by addressee", answered)
    assert answered[str(CallType.THINK)] is True
    assert answered[str(CallType.ESCALATE)] is True
    assert answered[str(CallType.DELEGATE)] is False


def test_an_escalate_that_changes_the_workspace_does_so_through_a_manager_dispatch(
    brain: Path, workspace: Path
) -> None:
    """The other half of Option A: the door a node uses instead (§ Deliverable 3)."""
    layer = layer_for(brain, "escalate_proposes")
    context = build_context(brain, "task-through", layer, workspace_path=str(workspace))
    state = new_state("task-through", GOAL, context)
    for _ in range(2):
        state.tick += 1
        run_tick(context, state)

    members = [
        entry
        for entry in load_journal(context.paths.journal(2))
        if entry.tier is CallType.DISPATCH and entry.is_call()
    ]
    show("the wave's key", [(str(m.node), m.call_number, m.member_number) for m in members])
    assert [(m.call_number, m.member_number) for m in members] == [(WAVE_CALL_NUMBER, 1)]
    assert state.latest.dispatch.observations[0].path == "patched.md"
    # The reply that proposed it authorized nothing: it is a `ManagerReply` and carries no
    # observation field at all.
    assert "observations" not in ManagerReply.model_fields


# --------------------------------------------------------------------------------------
# `dispatch_id` lives on the receipt and nowhere else
# --------------------------------------------------------------------------------------


def test_dispatch_id_is_on_the_receipt_and_never_on_the_unit_observation() -> None:
    show("UnitObservation fields", sorted(UnitObservation.model_fields))
    assert "dispatch_id" not in UnitObservation.model_fields
    assert UnitObservation.model_config.get("extra") == "forbid"
    assert "dispatch_id" in SPAWN_RECEIPT_FIELDS
    assert "dispatch_id" not in SPAWN_JOURNAL_FIELDS


def test_a_committed_change_joins_to_its_call_by_the_tick_s_node_and_call_keys(
    brain: Path, workspace: Path
) -> None:
    """The join Option A rests on: `(node, call#)`, which the journal already carries."""
    layer = layer_for(brain, "escalate_proposes")
    context = build_context(brain, "task-join", layer, workspace_path=str(workspace))
    state = new_state("task-join", GOAL, context)
    for _ in range(2):
        state.tick += 1
        run_tick(context, state)

    receipts = [
        line for line in load_seat_calls(context.paths.seat_calls) if line.dispatch_id
    ]
    show("receipt keys", [(str(r.node), r.call_number, r.member_number) for r in receipts])
    assert receipts, "the wave wrote its receipts"
    for receipt in receipts:
        assert (receipt.node, receipt.call_number) == (NodeName.CORTEX, WAVE_CALL_NUMBER)
        journalled = [
            entry
            for entry in load_journal(context.paths.journal(receipt.tick))
            if entry.node is receipt.node and entry.call_number == receipt.call_number
        ]
        assert journalled, "every receipt joins to a journal entry under the same key"


# --------------------------------------------------------------------------------------
# C2 `SubagentSpawn` — the two halves, and row M3's spawn half
# --------------------------------------------------------------------------------------


def test_the_record_splits_without_overlap_but_for_the_one_licensed_duplicate() -> None:
    spawn = SubagentSpawn(
        task="task-s", tick=2, node=NodeName.CORTEX, call_number=2, member_number=1,
        kind="writer", payload={"kind": "writer"}, argv=["claude"], outcome="ok",
        dispatch_id="task-s-t2-c2",
    )
    journal, receipt = spawn.journal_half(), spawn.receipt_half()
    show("journal half", sorted(journal))
    show("receipt half", sorted(receipt))
    assert set(journal) & set(receipt) - {"task", "tick", "node", "call_number", "member_number"} == set(
        SPAWN_LICENSED_DUPLICATES
    )
    assert spawn.key() == ("task-s", 2, str(NodeName.CORTEX), 2, 1)


def test_a_layer_without_the_delegate_seam_writes_no_subagent_spawn(
    brain: Path, workspace: Path
) -> None:
    """Row M3's spawn half, as the row states it."""
    empty = NodeCallDesk(port=lambda addressee, request: None, task="task-m3", tick=1)
    assert empty.spawns() == ()
    assert spawns_in([], task="task-m3") == ()

    layer = layer_for(brain, "option_a_refusal")
    desk = layer.node_calls("task-m3", 1)
    desk.run(NodeName.THALAMUS)
    spawned = desk.spawns()
    show("spawns after one delegate", [(s.kind, s.outcome) for s in spawned])
    assert [spawn.addressee for spawn in spawned] == [CallType.DELEGATE]
    assert all(spawn.addressee in SPAWN_CALL_TYPES for spawn in spawned)
    assert spawned[0].kind == "writer", "the kind is read off the payload it was sent with"
    assert spawned[0].outcome == "unavailable", "the illegal return was refused"


def test_the_member_request_is_the_wave_member_and_carries_no_path() -> None:
    member = WaveMember(kind="writer", unit_id="u-1", admitted_ref="admitted")
    facts = member_facts(member)
    show("member facts", facts)
    assert facts == MemberFacts(kind="writer", unit_id="u-1", admitted_ref="admitted")
    assert "workspace_path" not in WaveMember.model_fields
    assert sorted(WaveMember.model_fields) == ["admitted_ref", "kind", "unit_id"]
    assert KIND_KEY in WaveMember.model_fields
