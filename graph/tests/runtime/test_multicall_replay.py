"""G7 — the journal and the replay hold a multi-call tick, and a torn one replays clean.

`the build specification (not in this mirror)` § Deliverable 6 (the key, the reserved `call# = 0`, what a
call entry carries, "written once, at return", the replay condition and the crash-mid-tick
case), § Deliverable 4's journal/receipt table, § Named assumptions 2.

**The fixture is the whole evidence.** No run has ever torn a tick with several calls in flight,
because until A.1 there was only ever one (folded: A1-3): the crash-mid-tick case is *defined*
from build 1's own replay semantics and proved here, and nowhere else. The tear is injected at
the port — the process dies inside call 3 — rather than simulated by deleting a file, so what is
replayed is a journal a real tear would have left: entries for the calls that returned, nothing
for the one the crash was inside, and no checkpoint.

**Zero model calls.** Every answer is `fixtures/calls/*.yaml` through order W2's scripted
transport, and a replay makes none by construction. The receipt for that claim is the recording
shim's log at zero bytes across this module, captured from the command line rather than asserted
about code that was read.

**The wave is not here.** One `call#` per wave, `member#`-ordered buffered writes and the torn
**wave** are order W8's; what this battery pins is the key's shape and the per-call replay the
wave will sit inside.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protean import config
from protean.runtime.cycle import SEAT_CALL_NUMBER, run_tick
from protean.runtime.journal import load as load_journal
from protean.state.enums import CallType, NodeName, Tier
from protean.state.records import OUTPUT_CALL_NUMBER
from protean.state.seat_calls import SeatCallRecord, load_seat_calls
from tests.runtime import stubs
from tests.runtime.conftest import REPO_ROOT, call_entries_of

#: The tick's three calls, in the order the tick makes them — the node steps before the cortex's.
THE_THREE_CALLS = (
    (str(NodeName.HOMEOSTASIS), 1, str(CallType.THINK)),
    (str(NodeName.HIPPOCAMPUS), 1, str(CallType.DELEGATE)),
    (str(NodeName.CORTEX), SEAT_CALL_NUMBER, str(Tier.MANAGER)),
)

GOAL = "write the note the goal asks for"


def run_first_tick(
    brain: Path, workspace: Path, fixture: str, *, crash_on: int | None = None, task: str = "task-m"
):
    """Open a task on a **fixture** brain root and run tick 1, live."""
    context, state, port, _seat = stubs.open_task(
        brain, workspace, fixture, task, goal=GOAL, crash_on=crash_on
    )
    state.tick += 1
    result = None
    if crash_on is None:
        result = run_tick(context, state)
    else:
        with pytest.raises(stubs.TornTick):
            run_tick(context, state)
    return context, state, port, result


def replay_first_tick(brain: Path, workspace: Path, fixture: str, *, task: str = "task-m"):
    """The resumed pass: a fresh state at the last boundary, and `replay=True`.

    Tick 1's boundary is the task's opening state, so the replay starts where a resume would —
    the checkpoint is what "tick completed" means and the torn pass wrote none.
    """
    context, state, port, _seat = stubs.open_task(brain, workspace, fixture, task, goal=GOAL)
    state.tick += 1
    return context, state, port, run_tick(context, state, replay=True)


def calls_in(context) -> list[tuple[str, int, str]]:
    """`(node, call#, addressee)` for every **call** entry of tick 1, in key order."""
    return [
        (str(entry.node), entry.call_number, str(entry.tier))
        for entry in call_entries_of(context, 1)
    ]


@pytest.fixture(scope="module")
def untorn(tmp_path_factory):
    """One **untorn** first tick of `torn_tick.yaml`, read by every consumer that only reads it.

    The key's six claims — one entry per call, the node's own output at the reserved zero, what
    a call entry carries, the receipt's one line per call, its absent request column and where a
    `ref` may point — are six readings of *one* pass, and not one of them writes into the root
    or makes a further call. A test that tears the pass, replays it or compares two roots drives
    its own.
    """
    base = tmp_path_factory.mktemp("untorn")
    brain = stubs.seed_brain(REPO_ROOT / "brain", base / "brain")
    workspace = base / "workspace"
    workspace.mkdir()
    return run_first_tick(brain, workspace, "torn_tick.yaml")


# --------------------------------------------------------------------------------------
# The key: one entry per call, the node's own output at the reserved 0, calls from 1
# --------------------------------------------------------------------------------------


def test_every_call_of_the_tick_is_journalled_under_its_own_key(untorn) -> None:
    context, _state, port, result = untorn

    assert port.addressees == ["think", "delegate", "manager"], "three calls, in tick order"
    assert calls_in(context) == list(THE_THREE_CALLS)
    assert result.journal_entries == len(config.NODE_ORDER) + len(THE_THREE_CALLS)


def test_the_nodes_own_output_entry_is_the_reserved_zero_and_calls_number_from_one(untorn) -> None:
    """§ Deliverable 6 (folded: A1-9, folded: S-A76) — the reservation, on disk."""
    context, _state, _port, _result = untorn
    entries = load_journal(context.paths.journal(1))

    outputs = [entry for entry in entries if not entry.is_call()]
    assert [str(entry.node) for entry in outputs] == list(config.NODE_ORDER)
    assert {entry.call_number for entry in outputs} == {OUTPUT_CALL_NUMBER}
    assert min(entry.call_number for entry in entries if entry.is_call()) == 1
    assert all(entry.member_number is None for entry in entries), "no wave here — that is W8's"


def test_a_call_entry_carries_what_a_re_invoke_needs_and_nothing_more(untorn) -> None:
    """§ Deliverable 4's table: the addressee, the payload, the kind, the block ref, the envelope."""
    context, _state, _port, _result = untorn
    entries = {
        (str(entry.node), entry.call_number): entry
        for entry in load_journal(context.paths.journal(1))
    }

    think = entries[(str(NodeName.HOMEOSTASIS), 1)]
    assert think.tier is CallType.THINK
    assert think.payload["question"] == "is this tick's spend near the ceiling?"
    assert think.payload_model == "ThinkPayload"
    assert think.envelope is not None and think.output is None

    delegate = entries[(str(NodeName.HIPPOCAMPUS), 1)]
    assert delegate.kind == "reviewer", "the kind — the one licensed duplicate"
    assert delegate.block_ref == "", "A.1 fixes the field; A.1.i fills it"

    seat = entries[(str(NodeName.CORTEX), SEAT_CALL_NUMBER)]
    assert seat.tier is Tier.MANAGER and seat.payload_model == "ManagerRequest"
    assert entries[(str(NodeName.CORTEX), OUTPUT_CALL_NUMBER)].output is not None


# --------------------------------------------------------------------------------------
# The receipt: one line per journalled call, and `request` is not one of its columns
# --------------------------------------------------------------------------------------


def test_the_receipt_holds_one_line_per_journalled_call(untorn) -> None:
    """§ Deliverable 6's boundary rule, on a live pass: restored or live, one line each."""
    context, _state, _port, _result = untorn
    written = load_seat_calls(context.paths.seat_calls)

    assert [(str(line.node), line.call_number, str(line.tier)) for line in written] == list(
        THE_THREE_CALLS
    )
    assert [line.outcome for line in written] == ["ok", "ok", "ok"]
    assert [line.dedupe_key() for line in written] == [
        ("task-m", 1, node, call_number, None, "ok")
        for node, call_number, _ in THE_THREE_CALLS
    ], "keyed on the journal's own key plus the outcome"


def test_the_receipt_has_no_request_column_at_all(untorn) -> None:
    """folded: S-A73 — the payload has one home, and a fact with two homes has two versions."""
    context, _state, _port, _result = untorn
    raw = [
        json.loads(line)
        for line in context.paths.seat_calls.read_text(encoding="utf-8").splitlines()
    ]

    assert raw, "the file has to have lines for their columns to prove anything"
    assert all("request" not in payload for payload in raw)
    assert "request" not in SeatCallRecord.model_fields
    journalled = {
        (str(entry.node), entry.call_number): entry
        for entry in load_journal(context.paths.journal(1))
    }
    assert journalled[(str(NodeName.HOMEOSTASIS), 1)].payload, "and the journal does carry it"


def test_the_three_calls_ref_only_where_a_cortex_prediction_exists(untorn) -> None:
    """folded: S-A9 — think, escalate and delegate mint no cortex prediction, so `ref` is None."""
    context, _state, _port, _result = untorn
    written = {str(line.node): line for line in load_seat_calls(context.paths.seat_calls)}

    assert written[str(NodeName.HOMEOSTASIS)].ref is None
    assert written[str(NodeName.HIPPOCAMPUS)].ref is None
    assert written[str(NodeName.CORTEX)].ref, "the seat call joins to its own prediction"


# --------------------------------------------------------------------------------------
# The torn tick: calls 1–2 restore, only call 3 is re-invoked
# --------------------------------------------------------------------------------------


def test_a_tick_torn_after_call_two_of_three_leaves_two_entries_and_no_checkpoint(
    brain, workspace
) -> None:
    """The tear itself, before anything is claimed about the replay."""
    context, _state, port, _result = run_first_tick(
        brain, workspace, "torn_tick.yaml", crash_on=3
    )

    assert port.addressees == ["think", "delegate", "manager"], "it died inside call 3"
    assert calls_in(context) == list(THE_THREE_CALLS[:2]), "the crash left call 3 no entry"
    assert not context.paths.checkpoint.exists(), "a torn tick committed nothing"
    assert not context.paths.seat_calls.exists(), "so its calls have no receipt yet"


def test_the_replay_restores_calls_one_and_two_and_re_invokes_only_call_three(
    brain, workspace
) -> None:
    """Row G7's clause, and the whole of decision 11's "calls no model for those"."""
    run_first_tick(brain, workspace, "torn_tick.yaml", crash_on=3)
    context, _state, port, result = replay_first_tick(brain, workspace, "torn_tick.yaml")

    assert port.addressees == ["manager"], "one call on the replayed pass, and it is call 3"
    assert calls_in(context) == list(THE_THREE_CALLS), "all three are journalled again"
    assert result.seat_restored is False, "call 3 had no entry to restore"
    assert result.committed_terminal is None and context.paths.checkpoint.exists()


def test_the_replayed_boundary_writes_one_receipt_per_journalled_call_restored_or_live(
    brain, workspace
) -> None:
    """folded: S-A8 — a torn tick committed nothing, so each real invocation appears once."""
    run_first_tick(brain, workspace, "torn_tick.yaml", crash_on=3)
    context, _state, _port, _result = replay_first_tick(brain, workspace, "torn_tick.yaml")
    written = load_seat_calls(context.paths.seat_calls)

    assert [(str(line.node), line.call_number, str(line.tier)) for line in written] == list(
        THE_THREE_CALLS
    )
    restored = written[0]
    assert restored.argv == [] and restored.usage == {}, "a restored call made no invocation"
    assert restored.outcome == "ok", "its entry carried a restorable result"


def test_a_second_replay_of_a_committed_tick_restores_everything_and_calls_nothing(
    brain, workspace
) -> None:
    """The restore is keyed on the journal, so a committed tick replays with no call at all."""
    run_first_tick(brain, workspace, "torn_tick.yaml")
    context, _state, port, result = replay_first_tick(brain, workspace, "torn_tick.yaml")

    assert port.addressees == [], "every call of the tick carried a restorable result"
    assert calls_in(context) == list(THE_THREE_CALLS)
    assert result.seat_restored is True
    assert len(load_seat_calls(context.paths.seat_calls)) == len(THE_THREE_CALLS), (
        "and the keyed append makes the re-write a no-op rather than a second set of lines"
    )


# --------------------------------------------------------------------------------------
# Refused, then succeeded: re-invoked in place, and the calls after it still restore
# --------------------------------------------------------------------------------------


def test_a_refused_call_is_journalled_with_no_result_to_restore(brain, workspace) -> None:
    """§ Deliverable 2's "journalled and counted", and § Deliverable 6's restore condition."""
    context, _state, port, _result = run_first_tick(
        brain, workspace, "refused_then_succeeded.yaml", crash_on=3
    )
    entries = {
        (str(entry.node), entry.call_number): entry
        for entry in load_journal(context.paths.journal(1))
        if entry.is_call()
    }

    assert port.addressees == ["think", "delegate", "manager"]
    refused = entries[(str(NodeName.HOMEOSTASIS), 1)]
    assert refused.envelope is None, "an entry recording a refusal carries no result"
    assert refused.is_restorable() is False
    assert refused.payload, "and still carries what a re-invoke needs"
    assert entries[(str(NodeName.HIPPOCAMPUS), 1)].is_restorable() is True


def test_the_refused_call_is_re_invoked_in_place_and_the_later_calls_still_restore(
    brain, workspace
) -> None:
    """Row G7's second fixture. The tail is **not** made afresh — only the refusal is."""
    run_first_tick(brain, workspace, "refused_then_succeeded.yaml", crash_on=3)
    context, _state, port, _result = replay_first_tick(brain, workspace, "torn_tick.yaml")

    assert port.addressees == ["think", "manager"], (
        "the refused call re-invoked in place and the seat call made; the delegate restored"
    )
    assert calls_in(context) == list(THE_THREE_CALLS)
    entries = {
        (str(entry.node), entry.call_number): entry
        for entry in load_journal(context.paths.journal(1))
        if entry.is_call()
    }
    assert entries[(str(NodeName.HOMEOSTASIS), 1)].envelope is not None, "then succeeded"
    written = {str(line.node): line for line in load_seat_calls(context.paths.seat_calls)}
    assert written[str(NodeName.HIPPOCAMPUS)].argv == [], "the restored one has no adapter facts"
    assert written[str(NodeName.HOMEOSTASIS)].outcome == "ok"


# --------------------------------------------------------------------------------------
# Byte identity: a torn-then-replayed run and an untorn one commit the same four artifacts
# --------------------------------------------------------------------------------------


def artifacts(context) -> dict[str, str]:
    """The four the claim names, as text, keyed by the name the diff reports."""
    found = {
        "journal-1.jsonl": context.paths.journal(1).read_text(encoding="utf-8"),
        "checkpoint.json": context.paths.checkpoint.read_text(encoding="utf-8"),
        "seat_calls.jsonl": context.paths.seat_calls.read_text(encoding="utf-8"),
    }
    for node in config.NODE_ORDER:
        path = context.paths.trace(node)
        found[f"trace/{node}.jsonl"] = path.read_text(encoding="utf-8") if path.exists() else ""
    return found


def test_the_committed_records_are_byte_identical_to_an_untorn_run(
    tmp_path: Path, one_reading_per_source
) -> None:
    """Row G7's last clause, across journal, checkpoint, trace and `seat_calls.jsonl`.

    The one stated exception does not arise here: a decode-retry's failed first attempt exists
    only on a live pass, and no call in this fixture is retried.
    """
    untorn_root = stubs.seed_brain(REPO_ROOT / "brain", tmp_path / "untorn")
    torn_root = stubs.seed_brain(REPO_ROOT / "brain", tmp_path / "torn")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    untorn, _state, _port, _result = run_first_tick(untorn_root, workspace, "torn_tick.yaml")
    run_first_tick(torn_root, workspace, "torn_tick.yaml", crash_on=3)
    replayed, _state, _port, _result = replay_first_tick(torn_root, workspace, "torn_tick.yaml")

    left, right = artifacts(untorn), artifacts(replayed)
    differing = [name for name in left if left[name] != right[name]]
    assert differing == [], f"the replayed pass committed different bytes: {differing}"
    assert left["journal-1.jsonl"].strip(), "a comparison of two empty files proves nothing"
    assert len(left["seat_calls.jsonl"].splitlines()) == len(THE_THREE_CALLS)


def test_the_comparison_would_notice_a_difference(tmp_path: Path, one_reading_per_source) -> None:
    """The control: the same two roots, one of them running a fixture that answers differently."""
    left_root = stubs.seed_brain(REPO_ROOT / "brain", tmp_path / "left")
    right_root = stubs.seed_brain(REPO_ROOT / "brain", tmp_path / "right")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    left, _s, _p, _r = run_first_tick(left_root, workspace, "torn_tick.yaml")
    right, _s, _p, _r = run_first_tick(right_root, workspace, "refused_then_succeeded.yaml")

    differing = [name for name in artifacts(left) if artifacts(left)[name] != artifacts(right)[name]]
    assert "journal-1.jsonl" in differing, "the comparison has to be able to fail"
