"""The boundary write: one `SeatCallRecord` per journalled call, restored or live.

Build A.1 § Deliverable 6 replaces build 2's "per live invocation, and a replay writes none": a
replayed *committed* tick still appends nothing because the widened key makes it a no-op.

`the build specification (not in this mirror)` § Deliverable 2 and § Deliverable 1's decode half
(folded: S-8, folded: S-18, folded: S-19). DoD row **W3**'s boundary half; builder row **K3**'s
`ref` join and line count.

**Driven from `SeatCallFacts` fixtures, never from a live call.** `RecordingSeat` below answers
from the same request-keyed responders build 1's stubs use and reports its invocations through
the `calls()` seam exactly as `protean.cortex.live.invoke.LiveSeat` does — including the two
behaviours the boundary depends on: the list is cleared at the top of **every** port call, and a
tick that makes no port call leaves the previous tick's facts in place. The second is why the
runtime guards the write on "was the port called this tick" rather than on the seam being empty.

Every assertion is on disk: the file's own lines, the cortex folder's `trace.jsonl`, and the
file's sha256 across a replay.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from protean import config
from protean.brain.jsonl import read_lines
from protean.runtime.commit import WRITE_SEAT_CALL
from protean.runtime.cycle import run_tick
from protean.runtime.engine import build_context, new_state
from protean.runtime.errors import SeatUnavailable
from protean.runtime.seat import SeatLayer
from protean.state.enums import CallType, NodeName, Tier
from protean.state.records import TraceRecord
from protean.state.seat_calls import load_seat_calls, spend_tokens
from tests.runtime import stubs
from tests.runtime.conftest import UNIT_ID

ARGV = ("--output-format", "json", "--tools", "")


def _boundary_facts(seat, tier: str, index: int, outcome: str) -> dict:
    """The fields this order's own line assertions are recomputed against.

    `stubs.RecordingSeat` carries the shared skeleton; `plan` maps a tier to the outcome
    sequence one port call emits — `("ok",)` is the ordinary call, `("decode_retry", "ok")` is
    the one retry S-8 allows, and `("unavailable",)` is the invocation of a call that refused —
    and the per-outcome error text and the dispatch seat's permission mode are what this module
    reads back off the line.
    """
    return {
        "effort": "high",
        "permission_mode": None if tier != str(CallType.DISPATCH) else "auto",
        "model_usage": {f"model-{tier}": {"inputTokens": seat.tokens_per_call}},
        "num_turns": 2 + index,
        "error": "" if outcome != "unavailable" else "exit 1: refused",
    }


def _recording_seat(responder, **options) -> stubs.RecordingSeat:
    """This module's reading of the shared recording port (`tests/runtime/stubs.py`)."""
    return stubs.RecordingSeat(
        responder=responder, argv=ARGV, extra=_boundary_facts, mirror_usage=True, **options
    )


@pytest.fixture()
def recording(plan_then_execute):
    """The router/port pair of build 1's `layer` fixture, with the `calls()` seam attached."""
    planner, executor = plan_then_execute
    seat = _recording_seat(
        stubs.request_keyed(
            {
                str(Tier.MANAGER): planner,
                str(CallType.DISPATCH): executor,
                str(Tier.DIRECTOR): lambda request: {"tick": request.workspace.tick},
            }
        )
    )
    router = stubs.StubRouter(rule=stubs.manager_then_dispatch(UNIT_ID))
    return SeatLayer(router=router, port=seat, calls=seat.calls), router, seat


@pytest.fixture()
def opened(brain: Path, workspace: Path, recording, mailbox):
    """A task opened at tick 0 against a layer that reports its invocations."""
    layer, router, seat = recording
    context = build_context(
        brain, "task-calls", layer, mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-calls", "write out.txt", context)
    return context, state, router, seat


def lines(context) -> list[dict]:
    return read_lines(context.paths.seat_calls)


def committed_prediction_keys(context) -> set[str]:
    """Every prediction key on the cortex folder's own trace file, read back off disk."""
    keys: set[str] = set()
    for payload in read_lines(context.paths.trace(config.CORTEX_NODE)):
        record = TraceRecord.model_validate(payload)
        if record.prediction is not None:
            keys.add(record.prediction_key())
    return keys


# --------------------------------------------------------------------------------------
# One line per live invocation
# --------------------------------------------------------------------------------------


def test_one_line_per_seat_call_fact_the_port_returned(opened) -> None:
    context, state, _router, seat = opened
    for _ in range(3):
        state.tick += 1
        run_tick(context, state)

    assert len(seat.invocations) == 3
    assert len(lines(context)) == len(seat.invocations), "the line count is the call count"


def test_the_file_lands_under_the_tasks_own_state_directory(opened) -> None:
    context, state, _router, _seat = opened
    state.tick += 1
    run_tick(context, state)
    assert context.paths.seat_calls == context.paths.state_dir / "seat_calls.jsonl"
    assert context.paths.seat_calls.exists()


def test_the_receipt_records_the_seat_call_stage(opened) -> None:
    context, state, _router, _seat = opened
    state.tick += 1
    result = run_tick(context, state)
    assert result.receipt.count(WRITE_SEAT_CALL) == 1
    assert result.receipt.order_is_contractual(), result.receipt.kinds()
    assert result.receipt.checkpoint_is_last()
    kinds = result.receipt.kinds()
    assert kinds.index(WRITE_SEAT_CALL) == kinds.count("trace.prediction"), (
        f"immediately after the predictions: {kinds}"
    )


def test_the_line_reads_back_field_by_field_against_the_facts(opened) -> None:
    context, state, _router, seat = opened
    state.tick += 1
    run_tick(context, state)

    written = load_seat_calls(context.paths.seat_calls)[0]
    facts = seat.invocations[0]

    assert written.schema_version == config.SEAT_CALL_SCHEMA_VERSION
    assert (written.task, written.tick) == ("task-calls", 1)
    assert str(written.tier) == facts.tier
    assert (str(written.node), written.call_number, written.member_number) == ("cortex", 1, None)
    assert "request" not in type(written).model_fields, "the payload's one home is the journal"
    assert written.argv == list(ARGV)
    assert written.session_handle == facts.session_handle
    assert (written.model, written.effort) == (facts.model, facts.effort)
    assert written.permission_mode == facts.permission_mode
    assert written.cli_version == facts.cli_version
    assert written.usage == dict(facts.usage)
    assert written.model_usage == dict(facts.model_usage)
    assert written.wall_seconds == facts.wall_seconds
    assert written.outcome == facts.outcome
    assert written.num_turns == facts.num_turns


def test_the_request_on_disk_is_the_journals_and_the_receipt_has_no_column_for_it(opened) -> None:
    """folded: S-A73 — the payload has one home, and a fact with two homes has two versions."""
    context, state, _router, seat = opened
    state.tick += 1
    run_tick(context, state)

    raw = json.loads(context.paths.seat_calls.read_text(encoding="utf-8").splitlines()[0])
    assert "request" not in raw, "removed, not deprecated"
    call = next(
        entry
        for entry in read_lines(context.paths.journal(1))
        if entry["node"] == str(NodeName.CORTEX) and entry["call_number"] == 1
    )
    assert call["payload"] == dict(seat.invocations[0].request)
    assert call["payload"]["workspace"]["tick"] == 1
    assert (raw["node"], raw["call_number"]) == (call["node"], call["call_number"])


# --------------------------------------------------------------------------------------
# The `ref` join to `brain/nodes/cortex/trace.jsonl`
# --------------------------------------------------------------------------------------


def test_the_ref_names_a_prediction_committed_in_the_cortex_trace(opened) -> None:
    context, state, _router, _seat = opened
    for _ in range(2):
        state.tick += 1
        run_tick(context, state)

    committed = committed_prediction_keys(context)
    written = load_seat_calls(context.paths.seat_calls)
    assert written, "there is something to join"
    for call in written:
        assert call.ref in committed, f"{call.ref} names no committed prediction"


def test_the_ref_is_this_calls_own_tier_and_tick(opened) -> None:
    context, state, _router, _seat = opened
    state.tick += 1
    run_tick(context, state)
    call = load_seat_calls(context.paths.seat_calls)[0]
    assert call.ref == f"task-calls:1:{config.CORTEX_NODE}:{call.tier}:prediction"


# --------------------------------------------------------------------------------------
# A retry is its own line (folded: S-8)
# --------------------------------------------------------------------------------------


def test_a_decode_retry_writes_two_lines_and_the_first_is_marked(opened) -> None:
    context, state, _router, seat = opened
    seat.plan = {str(Tier.MANAGER): ("decode_retry", "ok")}
    state.tick += 1
    run_tick(context, state)

    written = load_seat_calls(context.paths.seat_calls)
    assert [call.outcome for call in written] == ["decode_retry", "ok"]
    assert len({call.ref for call in written}) == 1, "both invocations answer one prediction"
    assert len(written) == len(seat.invocations)


# --------------------------------------------------------------------------------------
# A replay writes none, and the file is byte-identical across it
# --------------------------------------------------------------------------------------


def test_a_replayed_tick_appends_none_and_the_file_hash_is_unchanged(opened) -> None:
    context, state, _router, seat = opened
    state.tick += 1
    before_state = state.model_copy(deep=True)
    run_tick(context, state)

    calls_after_live = len(seat.invocations)
    digest = hashlib.sha256(context.paths.seat_calls.read_bytes()).hexdigest()
    print(f"seat_calls.jsonl sha256 after the live tick: {digest}")

    replayed = before_state.model_copy(deep=True)
    result = run_tick(context, replayed, replay=True)

    assert result.seat_restored, "the journalled envelope answered"
    assert len(seat.invocations) == calls_after_live, "no new invocation"
    after = hashlib.sha256(context.paths.seat_calls.read_bytes()).hexdigest()
    print(f"seat_calls.jsonl sha256 after the replay:    {after}")
    assert after == digest
    assert result.receipt.count(WRITE_SEAT_CALL) == 0
    assert len(lines(context)) == calls_after_live


def test_the_replay_would_have_written_had_the_seam_been_read_unguarded(opened) -> None:
    """The seam still holds the live tick's facts on a replay — the guard is the runtime's."""
    context, state, _router, seat = opened
    state.tick += 1
    before_state = state.model_copy(deep=True)
    run_tick(context, state)

    replayed = before_state.model_copy(deep=True)
    run_tick(context, replayed, replay=True)
    assert seat.calls(), "the layer reports the last port call's facts, not this tick's"


def test_a_skipped_seat_writes_no_line(brain: Path, workspace: Path, recording, mailbox) -> None:
    """The gate's veto skips the call, so there is no invocation and no line."""
    layer, _router, seat = recording
    context = build_context(
        brain, "task-skip", layer, mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-skip", "write out.txt", context)
    state.cost.tokens = 10**9  # homeostasis stops, which skips the seat call
    state.tick += 1
    result = run_tick(context, state)

    assert result.seat_skipped
    assert seat.invocations == []
    assert not context.paths.seat_calls.exists()


# --------------------------------------------------------------------------------------
# S-19 at the boundary: the per-iteration spend, and the cache read that is not spend
# --------------------------------------------------------------------------------------


def test_the_tick_spend_is_the_per_iteration_sum_not_the_top_level_aggregate(opened) -> None:
    context, state, _router, seat = opened
    seat.usage = {
        "input_tokens": 4,
        "cache_creation_input_tokens": 6,
        "cache_read_input_tokens": 40940,
        "output_tokens": 10,
        "iterations": [
            {
                "input_tokens": 2,
                "cache_creation_input_tokens": 3,
                "cache_read_input_tokens": 40940,
                "output_tokens": 5,
            },
            {
                "input_tokens": 2,
                "cache_creation_input_tokens": 3,
                "cache_read_input_tokens": 40940,
                "output_tokens": 5,
            },
        ],
    }
    state.tick += 1
    run_tick(context, state)

    assert spend_tokens(seat.usage) == 20
    assert state.cost.tokens == 20, "the per-iteration sum, and the 40940 reads are not in it"


def test_the_cache_read_is_on_the_record_even_though_it_is_not_spend(opened) -> None:
    context, state, _router, seat = opened
    seat.usage = {"cache_read_input_tokens": 22170, "input_tokens": 2, "output_tokens": 5}
    state.tick += 1
    run_tick(context, state)

    written = load_seat_calls(context.paths.seat_calls)[0]
    assert written.cache_reads() == 22170
    assert written.spend_tokens() == 7
    assert state.cost.tokens == 7


# --------------------------------------------------------------------------------------
# Idempotency: a re-committed tick leaves the file where it was
# --------------------------------------------------------------------------------------


def test_re_running_the_same_tick_live_does_not_double_the_lines(opened) -> None:
    context, state, _router, _seat = opened
    state.tick += 1
    snapshot = state.model_copy(deep=True)
    run_tick(context, state)
    digest = hashlib.sha256(context.paths.seat_calls.read_bytes()).hexdigest()

    run_tick(context, snapshot.model_copy(deep=True))
    assert hashlib.sha256(context.paths.seat_calls.read_bytes()).hexdigest() == digest
    assert len(lines(context)) == 1


def test_the_node_folders_are_not_where_this_lands(opened) -> None:
    """S2's file is task state, not a sixth node folder — row W10 diffs `brain/nodes/`."""
    context, state, _router, _seat = opened
    state.tick += 1
    run_tick(context, state)
    assert list(context.paths.state_dir.glob("seat_calls.jsonl"))
    assert not list((context.root / "nodes").rglob("seat_calls.jsonl"))


# --------------------------------------------------------------------------------------
# A refused invocation is still an invocation, and it names no prediction
# --------------------------------------------------------------------------------------


def test_a_refused_call_writes_its_line_with_no_ref(
    brain: Path, workspace: Path, plan_then_execute, mailbox
) -> None:
    """The refusal path journals a null cortex entry and mints no tier-keyed prediction, so the
    line's `ref` is `None` — the case the record's optional `ref` exists for (dispatch ledger)."""
    planner, executor = plan_then_execute
    seat = _recording_seat(
        stubs.request_keyed(
            {str(Tier.MANAGER): planner, str(CallType.DISPATCH): executor}
        ),
        plan={str(Tier.MANAGER): ("unavailable",)},
    )

    def refusing(tier, request):
        seat(tier, request)  # records the invocation's facts, exactly as the live seat does
        raise SeatUnavailable(tier=str(tier), reason="exit", message="Reached maximum budget")

    layer = SeatLayer(
        router=stubs.StubRouter(rule=stubs.manager_then_dispatch(UNIT_ID)),
        port=refusing,
        calls=seat.calls,
    )
    context = build_context(
        brain, "task-refuse", layer, mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-refuse", "write out.txt", context)
    state.tick += 1
    result = run_tick(context, state)

    assert result.seat_refusal == "Reached maximum budget"
    written = load_seat_calls(context.paths.seat_calls)
    assert len(written) == 1, "a refusal is a live invocation and gets its line"
    assert written[0].outcome == "unavailable"
    assert written[0].ref is None, "it names no cortex prediction, because none was minted"
    assert written[0].error == "exit 1: refused"
    refused = next(
        entry
        for entry in read_lines(context.paths.journal(1))
        if entry["node"] == str(NodeName.CORTEX) and entry["call_number"] == 1
    )
    assert refused["payload"], "what the seat was asked survives the refusal — in the journal"
    assert refused["envelope"] is None, "the entry records a refusal: no result to restore"
