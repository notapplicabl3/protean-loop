"""Replay-or-advance: what a resume's first act is, and why.

`the build specification (not in this mirror)` § Deliverable 3 → *Resume's first act depends on how the run
ended* (folded: T-3): "If the journal holds entries for a tick that has no checkpoint, that tick
was interrupted by a crash: restore the last checkpointed state, replay the tick whole, and let
the keyed appends no-op on their surviving orphans. If the last tick is checkpointed with a
`terminal` set, the exit was clean: clear `terminal` … and advance to tick n+1."

Builder-verified row M6. **A tick is atomic and the checkpoint's presence is what "completed"
means**, so every assertion below is a comparison between what is on disk and what a second run
did to it — never between two in-memory objects the same process built.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protean import config
from protean.brain.jsonl import read_lines
from protean.runtime import cycle as cycle_module
from protean.runtime.commit import build_checkpoint
from protean.runtime.cycle import SEAT_CALL_NUMBER, run_tick
from protean.runtime.engine import build_context, load_task, new_state, resume
from protean.runtime.journal import has_entries, journaled_envelope, load
from protean.runtime.paths import BrainPaths
from protean.runtime.resume import Resumption, classify
from protean.state.enums import CallType, NodeName, Tier
from tests.runtime import stubs
from tests.runtime.conftest import UNIT_ID


def _trace_counts(brain: Path) -> dict[str, int]:
    return {
        node: len(read_lines(config.node_dir(node, brain) / "trace.jsonl"))
        for node in config.NODE_ORDER
    }


# --------------------------------------------------------------------------------------
# The classifier
# --------------------------------------------------------------------------------------


def test_a_clean_checkpoint_advances_to_the_next_tick(started):
    context, state, _router, _seat = started
    state.tick += 1
    result = run_tick(context, state)

    plan = classify(context.paths, result.receipt.checkpoint)
    assert plan.kind is Resumption.ADVANCE
    assert plan.tick == 2
    assert plan.checkpoint_tick == 1
    assert plan.replays is False


def test_a_journal_with_no_checkpoint_replays_that_tick(started):
    context, state, _router, _seat = started
    state.tick += 1
    result = run_tick(context, state)

    orphan = context.paths.journal(2)
    orphan.write_text(
        context.paths.journal(1).read_text(encoding="utf-8"), encoding="utf-8"
    )
    plan = classify(context.paths, result.receipt.checkpoint)
    assert plan.kind is Resumption.REPLAY
    assert plan.tick == 2
    assert plan.replays is True


def test_an_empty_orphan_journal_is_not_a_crash(started):
    """A file with no entries means the tick never reached its first node."""
    context, state, _router, _seat = started
    state.tick += 1
    result = run_tick(context, state)

    context.paths.journal(2).write_text("", encoding="utf-8")
    assert has_entries(context.paths.journal(2)) is False
    assert classify(context.paths, result.receipt.checkpoint).kind is Resumption.ADVANCE


def test_the_classifier_carries_the_revision_it_decided_from(started):
    """An administrative commit is the same tick at a later revision, never a crash."""
    context, state, _router, _seat = started
    state.tick += 1
    run_tick(context, state)

    checkpoint = build_checkpoint(state, seed_hashes=context.seed_hashes, revision=3)
    plan = classify(context.paths, checkpoint)
    assert plan.revision == 3
    assert plan.kind is Resumption.ADVANCE


# --------------------------------------------------------------------------------------
# Replaying a completed tick changes nothing
# --------------------------------------------------------------------------------------


def _tear_the_commit(monkeypatch):
    """Kill the process *inside* the boundary commit, after every append and before the rename.

    This is the only shape the replay branch ever sees: a completed tick has a checkpoint, and a
    checkpointed tick advances. So "the keyed appends no-op on their surviving orphans" is a
    claim about a torn commit, and a torn commit is what this produces.
    """
    from protean.runtime import commit as commit_module

    def _die(paths, checkpoint):
        raise RuntimeError("killed inside the commit, before the checkpoint")

    monkeypatch.setattr(commit_module, "write_checkpoint", _die)


def test_a_torn_commit_no_ops_its_orphans_keeps_them_authoritative_and_truncates_the_journal(
    brain: Path, workspace: Path, layer, mailbox, monkeypatch
):
    """Row T-3 and row M6, before and after **one** torn commit and **one** resume.

    The three claims were three drives of the same tear, and each is a reading of the same pair
    of states:

    * **the appends no-op on their surviving orphans** — the torn commit did land its appends,
      the checkpoint stayed at tick 1, and the replay duplicates not one trace record and not
      one episode record: every append no-ops, and the checkpoint is the last thing written;
    * **the surviving orphan stays authoritative** — the record on disk is the first attempt's,
      byte for byte, and the replay adds nothing beside it; and
    * **the journal is truncated on replay, never appended to** — it is the one artifact a
      replay replaces, and it is never a resume point. **Re-based by build A.1**: the journal is
      one entry per node **plus one per call** (§ Deliverable 6), so a tick that made the seat
      call writes six output entries and one call entry. The truncate rule is unchanged and is
      what this asserts: the replay's journal replaces the torn pass's rather than appending.
    """
    seat_layer, _router, _seat = layer
    context = build_context(
        brain, "task-torn", seat_layer, mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-torn", "write out.txt", context)
    state.tick += 1
    run_tick(context, state)

    _tear_the_commit(monkeypatch)
    state.tick += 1
    with pytest.raises(RuntimeError):
        run_tick(context, state)

    orphans = _trace_counts(brain)
    orphan_episodes = read_lines(context.paths.episodes)
    cortex_trace = config.node_dir(config.CORTEX_NODE, brain) / "trace.jsonl"
    orphan_bytes = cortex_trace.read_bytes()
    torn = len(load(context.paths.journal(2)))
    assert orphans[config.CORTEX_NODE] > 0, "the torn commit did land its appends"
    assert stubs.committed_state(context.paths)["state"]["tick"] == 1
    assert torn == len(config.NODE_ORDER) + 1

    monkeypatch.undo()
    outcome = resume(
        brain, seat_layer, mailbox=mailbox, workspace_path=str(workspace), max_ticks=1
    )
    replayed = outcome.ticks[0]

    assert replayed.tick == 2
    assert _trace_counts(brain) == orphans, "not one duplicated trace record"
    assert read_lines(context.paths.episodes) == orphan_episodes, "nor an episode record"
    assert replayed.receipt.count("trace.prediction") == 0, "every append no-opped"
    assert replayed.receipt.count("episode") == 0
    assert replayed.receipt.checkpoint_is_last()
    assert stubs.committed_state(context.paths)["state"]["tick"] == 2

    assert cortex_trace.read_bytes() == orphan_bytes, "the first attempt's record is the record"

    entries = load(context.paths.journal(2))
    assert len(entries) == torn, "replaced, never appended to"
    outputs = [entry for entry in entries if not entry.is_call()]
    assert [str(entry.node) for entry in outputs] == list(config.NODE_ORDER)


# --------------------------------------------------------------------------------------
# A crash mid-tick, and the seat envelope's restore
# --------------------------------------------------------------------------------------


def _crash_in_the_last_node(monkeypatch):
    """Kill the tick in the node that runs *after* the seat, so its envelope is journalled."""

    def _explode(payload):
        raise RuntimeError("killed mid-tick")

    monkeypatch.setattr(
        cycle_module,
        "NODES",
        {**cycle_module.NODES, "anterior_cingulate": _explode},
    )


def test_a_kill_mid_tick_leaves_its_journal_and_the_replay_restores_the_envelope(
    brain: Path, workspace: Path, layer, mailbox, monkeypatch
):
    """Row M6's crash pair, off **one** crashed tick: what it left, and what the replay did.

    * the crashed tick **committed nothing** — the journal has entries, the checkpoint is still
      tick 1, and both ticks' journals are on disk; and
    * the replay **restores the journalled envelope** instead of re-invoking the seat: the
      envelope was there to restore, the seat was not asked twice, and the boundary commits.
    """
    seat_layer, _router, seat = layer
    context = build_context(
        brain, "task-crash", seat_layer, mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-crash", "write out.txt", context)
    state.tick += 1
    run_tick(context, state)

    _crash_in_the_last_node(monkeypatch)
    state.tick += 1
    with pytest.raises(RuntimeError):
        run_tick(context, state)

    assert has_entries(context.paths.journal(2))
    assert stubs.committed_state(context.paths)["state"]["tick"] == 1, "committed nothing"
    assert context.paths.journal_ticks() == [1, 2]

    assert (
        journaled_envelope(context.paths.journal(2), NodeName.CORTEX, SEAT_CALL_NUMBER)
        is not None
    )
    calls_before = len(seat.calls)
    monkeypatch.undo()

    outcome = resume(
        brain, seat_layer, mailbox=mailbox, workspace_path=str(workspace), max_ticks=1
    )
    assert outcome.ticks[0].tick == 2
    assert outcome.ticks[0].seat_restored is True
    assert len(seat.calls) == calls_before, "the seat was not asked twice"

    assert stubs.committed_state(context.paths)["state"]["tick"] == 2


def test_a_crash_before_the_seat_call_re_invokes_it(brain: Path, workspace: Path, layer, mailbox):
    """A crash *inside* the call leaves no entry: the re-run invokes, and the act re-observes."""
    seat_layer, _router, seat = layer
    context = build_context(
        brain, "task-crash3", seat_layer, mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-crash3", "write out.txt", context)
    state.tick += 1
    run_tick(context, state)

    context.paths.journal(2).write_text(
        context.paths.journal(1).read_text(encoding="utf-8").splitlines()[0] + "\n",
        encoding="utf-8",
    )
    assert journaled_envelope(context.paths.journal(2), NodeName.CORTEX, SEAT_CALL_NUMBER) is None

    calls_before = len(seat.calls)
    outcome = resume(
        brain, seat_layer, mailbox=mailbox, workspace_path=str(workspace), max_ticks=1
    )
    assert outcome.ticks[0].seat_restored is False
    assert len(seat.calls) == calls_before + 1


def test_a_clean_terminal_exit_clears_the_terminal_and_advances(
    brain: Path, workspace: Path, layer, mailbox
):
    seat_layer, _router, _seat = layer
    context = build_context(
        brain, "task-adv", seat_layer, mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-adv", "write out.txt", context)
    for _ in range(2):
        state.tick += 1
        run_tick(context, state)

    checkpoint = load_task(BrainPaths(root=brain).task("task-adv"))
    assert classify(BrainPaths(root=brain).task("task-adv"), checkpoint).tick == 3

    outcome = resume(
        brain, seat_layer, mailbox=mailbox, workspace_path=str(workspace), max_ticks=1
    )
    assert outcome.ticks[0].tick == 3


def test_a_resume_re_reads_the_committed_state_and_not_the_processs_memory(
    brain: Path, workspace: Path, layer, mailbox
):
    """The unit stack survives the process: a resumed tick sees the same unit id."""
    seat_layer, _router, _seat = layer
    context = build_context(
        brain, "task-mem", seat_layer, mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-mem", "write out.txt", context)
    state.tick += 1
    run_tick(context, state)
    assert [unit.id for unit in state.units] == [UNIT_ID]

    outcome = resume(
        brain, seat_layer, mailbox=mailbox, workspace_path=str(workspace), max_ticks=1
    )
    payload = stubs.committed_state(BrainPaths(root=brain).task("task-mem"))
    assert [unit["id"] for unit in payload["state"]["units"]] == [UNIT_ID]
    assert outcome.task_id == "task-mem"


def test_a_root_with_no_task_has_no_resume(brain: Path, layer, mailbox):
    from protean.runtime.errors import NoTask

    seat_layer, _router, _seat = layer
    with pytest.raises(NoTask):
        resume(brain, seat_layer, mailbox=mailbox)
