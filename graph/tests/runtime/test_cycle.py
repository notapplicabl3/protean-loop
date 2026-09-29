"""M5 — one tick runs every node exactly once, in `config.py`'s order, journalled and committed.

`the build specification (not in this mirror)` § Deliverable 3 → the cycle and the two writes; binding
contract 5. Every assertion below is about the *recorded* behaviour of a real tick, not about
the source: the node call sequence is collected by wrapping the callables the cycle dispatches
to, and the write sequence is the commit's own receipt.

**Re-based by build A.1** (`the build specification (not in this mirror)` § Deliverable 6): contract 5
is rewritten there and "one journal entry per node" becomes **one output entry per node at the
reserved `call# = 0`, plus one entry per model call, numbered from 1**. Every node still runs
exactly once and in the same order; what moved is the journal's cardinality, so the count is
asserted against the tick's own calls rather than against `len(NODE_ORDER)` alone.
"""

from __future__ import annotations


from protean import config
from protean.runtime.commit import COMMIT_ORDER, WRITE_CHECKPOINT
from protean.runtime.cycle import run_tick
from protean.runtime.journal import load
from protean.state.enums import Tier
from protean.state.records import OUTPUT_CALL_NUMBER
from tests.runtime import stubs


def _run_one_tick(context, state, monkeypatch, sink):
    stubs.recorded_nodes(monkeypatch, sink)
    context.layer.port.on_call = sink.append
    state.tick += 1
    return run_tick(context, state)


def test_recorded_call_sequence_equals_the_config_literal(started, monkeypatch):
    """Contract 5 under A.1: the steps are the config tuple; the bodies are those whose cheap
    check fired (§ Deliverable 1 — being on the path no longer means doing work).

    Subsumes two removed tests. `test_each_node_is_called_exactly_once` is entailed by the tuple
    equality below: a sequence equal to the fired nodes in order holds each of them exactly once
    and the declined ones not at all. `test_the_cycle_iterates_the_config_tuple_itself` restated
    this test's `result.order == config.NODE_ORDER` plus a module-identity check strictly weaker
    than `test_the_recorded_order_is_the_config_tuples_own_elements`'s call-time identity proof.
    """
    context, state, _router, _seat = started
    sink: list[str] = []
    result = _run_one_tick(context, state, monkeypatch, sink)
    assert result.order == config.NODE_ORDER, "every node's step, every tick"
    declined = {str(d.node) for d in result.firing if not d.fired}
    assert tuple(sink) == tuple(n for n in config.NODE_ORDER if n not in declined)


def test_one_output_entry_per_node_and_one_entry_per_call(started):
    """A.1's re-base of "six entries, six of six" (§ Deliverable 6).

    A tick that makes one seat call writes seven entries: the six nodes' own output entries at
    `call# = 0`, and the seat call's at `call# = 1`. The output entries are still one per node
    and still in `NODE_ORDER`.
    """
    context, state, _router, _seat = started
    state.tick += 1
    result = run_tick(context, state)
    entries = load(context.paths.journal(state.tick))
    outputs = [entry for entry in entries if not entry.is_call()]
    calls = [entry for entry in entries if entry.is_call()]

    assert [str(entry.node) for entry in outputs] == list(config.NODE_ORDER)
    assert all(entry.call_number == OUTPUT_CALL_NUMBER == 0 for entry in outputs)
    assert [(str(entry.node), entry.call_number) for entry in calls] == [("cortex", 1)]
    assert result.journal_entries == len(entries) == len(config.NODE_ORDER) + 1


def test_the_seat_call_entry_carries_the_request_and_the_envelope(started):
    """§ Deliverable 4's table — the journal's half, and the output entry's split from it."""
    context, state, _router, _seat = started
    state.tick += 1
    run_tick(context, state)
    entries = load(context.paths.journal(state.tick))

    call = next(entry for entry in entries if entry.is_call())
    output = next(
        entry for entry in entries if not entry.is_call() and str(entry.node) == "cortex"
    )
    assert call.tier is Tier.MANAGER, "the addressee it was sent to"
    assert call.payload and call.payload_model == "ManagerRequest", "the request as sent"
    assert call.envelope is not None, "the returned envelope — what a re-invoke needs"
    assert call.output is None, "an output is the node's, and rides its own entry"
    assert output.envelope is None and output.output is not None
    assert output.tier is Tier.MANAGER, "which addressee produced what the node output"


def test_the_seat_is_the_only_node_the_runtime_calls_out_to(started, monkeypatch):
    """Zero model calls: the seat port is invoked, and nothing else leaves the process.

    Also covers the removed `test_resume.py` test of the same claim (the stub seat is the only
    thing that leaves the process): identical setup, the same `len(seat.calls) == 1` assertion,
    plus an `isinstance(seat, stubs.StubSeat)` tautology on the fixture's own stub.
    """
    context, state, _router, seat = started
    sink: list[str] = []
    _run_one_tick(context, state, monkeypatch, sink)
    assert len(seat.calls) == 1


def test_the_journal_count_holds_on_every_tick_shape(started):
    """Four ticks, asserted inside the loop — so the one-tick and two-tick shapes the removed
    `[1]`/`[2]` parametrize arms covered are executed and checked on the way to the fourth."""
    context, state, _router, _seat = started
    for _ in range(4):
        state.tick += 1
        result = run_tick(context, state)
        entries = load(context.paths.journal(state.tick))
        outputs = [entry for entry in entries if not entry.is_call()]
        assert len(outputs) == len(config.NODE_ORDER), "every node every tick"
        assert result.journal_entries == len(entries)


def test_the_recorded_order_is_the_config_tuples_own_elements(started, monkeypatch):
    """Identity, not equality — the loop reads `config.NODE_ORDER` at call time.

    This is the surviving identity proof: the removed `test_the_cycle_iterates_the_config_tuple_itself`
    asserted only that `cycle.config.NODE_ORDER is config.NODE_ORDER`, which a cycle caching the
    order at import would still pass.

    The literal is replaced with a tuple of equal-but-distinct string objects. A cycle that
    restated the order, or cached it at import, records the *original* objects: it still passes
    an `==` assertion and fails this one. `result.order` is what the loop appended as it went.
    """
    context, state, _router, _seat = started
    rebuilt = tuple("".join(list(name)) for name in config.NODE_ORDER)
    assert rebuilt == config.NODE_ORDER
    assert all(new is not old for new, old in zip(rebuilt, config.NODE_ORDER))
    monkeypatch.setattr(config, "NODE_ORDER", rebuilt)

    state.tick += 1
    result = run_tick(context, state)

    assert result.order == rebuilt
    assert all(recorded is expected for recorded, expected in zip(result.order, rebuilt)), (
        "the cycle restated the order instead of iterating the literal"
    )


def test_the_journalled_order_follows_the_config_literal_too(started, monkeypatch):
    """The same identity swap, read back off `journal-<tick>.jsonl` rather than off memory."""
    context, state, _router, _seat = started
    rebuilt = tuple("".join(list(name)) for name in config.NODE_ORDER)
    monkeypatch.setattr(config, "NODE_ORDER", rebuilt)

    state.tick += 1
    run_tick(context, state)

    entries = load(context.paths.journal(state.tick))
    outputs = [entry for entry in entries if not entry.is_call()]
    assert [str(entry.node) for entry in outputs] == list(rebuilt)


def test_three_ticks_leave_three_journals_and_one_checkpoint_holding_the_last_tick(started):
    """What three ticks leave **on disk**, read off the directory rather than off the receipt.

    One loop, three readings: the checkpoint on disk is *this* tick's at every step and carries
    the schema version the writer stamps; a journal file exists per tick; and there is exactly
    one checkpoint file with no temp surviving beside it.
    """
    context, state, _router, _seat = started
    for expected in (1, 2, 3):
        state.tick += 1
        run_tick(context, state)
        payload = stubs.committed_state(context.paths)
        assert payload["state"]["tick"] == expected
        assert payload["schema_version"] == config.CHECKPOINT_SCHEMA_VERSION

    assert context.paths.journal_ticks() == [1, 2, 3]

    checkpoints = sorted(
        entry.name for entry in context.paths.state_dir.iterdir() if "checkpoint" in entry.name
    )
    assert checkpoints == ["checkpoint.json"]
    assert not context.paths.checkpoint_temp.exists()


def test_the_checkpoint_is_written_once_after_every_appended_artifact(started):
    """Every non-checkpoint write of the commit precedes it, on every tick shape.

    The last-index claim is the strong form and it entails the two that were asserted beside
    it: that the checkpoint is written **exactly once** per tick, and that it is the receipt's
    last kind. The contractual order is checked on every tick of the loop, and `COMMIT_ORDER`
    itself ends where the receipt does.
    """
    context, state, _router, _seat = started
    for _ in range(3):
        state.tick += 1
        result = run_tick(context, state)
        receipt = result.receipt
        kinds = receipt.kinds()
        assert kinds.index(WRITE_CHECKPOINT) == len(kinds) - 1
        assert receipt.count(WRITE_CHECKPOINT) == 1
        assert kinds[-1] == WRITE_CHECKPOINT
        assert receipt.checkpoint_is_last()
        assert receipt.order_is_contractual(), kinds
    assert COMMIT_ORDER[-1] == WRITE_CHECKPOINT
