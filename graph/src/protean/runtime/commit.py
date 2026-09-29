"""The boundary commit: one step, one order, the checkpoint last.

`the build specification (not in this mirror)` § Deliverable 3 → *at the tick boundary — one commit, one
checkpoint*. In a single step, **in this order** (folded: T-5):

1. this tick's `prediction` `TraceRecord`s, one per node folder that ran (the cortex folder's
   keyed by tier);
2. this tick's `SeatCallRecord`s, one per **journalled call** of the committing pass — restored or
   live (build 2's S2 as build A.1 amends it, folded: S-A8);
3. the **previous** tick's `outcome` records, derived mechanically;
4. the tick's `EpisodeRecord`s;
5. any mailbox file a node requested, as the commit's **last append**;
6. and LAST the `Checkpoint`, written to a temp file and renamed into place.

**The seat-call stage sits immediately after the predictions and nowhere else** (build 2,
`the build specification (not in this mirror)` § Deliverable 2). Its `ref` names a cortex-trace prediction,
so appending it there makes "the `ref` names a *committed* prediction" true at the moment of the
append rather than only once the commit finishes; and it stays above the mailbox stage, because
§ Deliverable 3 gives the mailbox file the commit's last append and that is what
`tests/mailbox/test_lifecycle.py` reads off the receipt. A replayed tick makes no port call, so
this stage is empty and the file is byte-unchanged.

**The order is the contract, so the commit reports it.** `CommitReceipt.writes` is the sequence
of writes this commit actually performed, which is how "the checkpoint is the last write" is
proven rather than asserted — and how a caller counts "exactly one checkpoint per tick".

**The checkpoint's presence is the definition of "tick completed".** There is no marker file and
no sixth artifact; the temp-then-rename is what stops a crash from leaving a half-written one.

**Every appended artifact is append-only and keyed**, so a replayed tick's re-appends no-op on
their surviving orphans and the surviving record stays authoritative. The two *raising* refusals
of the trace path are a different thing and are enforced in `protean.brain.trace`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from protean import config
from protean.brain.episodes import append_episode
from protean.brain.trace import append_trace
from protean.runtime.interrupts import MailboxPort
from protean.runtime.paths import TaskPaths
from protean.state.brain_state import BrainState
from protean.state.checkpoint import Checkpoint, sealed
from protean.state.interrupts import Interrupt
from protean.state.records import EpisodeRecord, TraceRecord
from protean.state.seat_calls import SeatCallRecord, append_seat_call

#: The write kinds a receipt records, in the order the commit performs them.
WRITE_PREDICTION = "trace.prediction"
WRITE_SEAT_CALL = "seat_call"
WRITE_OUTCOME = "trace.outcome"
WRITE_EPISODE = "episode"
WRITE_MAILBOX = "mailbox.write"
WRITE_MAILBOX_DELETE = "mailbox.delete"
WRITE_CHECKPOINT = "checkpoint"

#: The commit's stages, in their contractual order. `CommitReceipt.order_is_contractual()`
#: checks a receipt against this rather than against a hand-written expectation in a test.
COMMIT_ORDER: tuple[str, ...] = (
    WRITE_PREDICTION,
    WRITE_SEAT_CALL,
    WRITE_OUTCOME,
    WRITE_EPISODE,
    WRITE_MAILBOX_DELETE,
    WRITE_MAILBOX,
    WRITE_CHECKPOINT,
)


@dataclass(frozen=True, slots=True)
class WriteRecord:
    """One write this commit performed."""

    kind: str
    path: Path
    key: str = ""


@dataclass(slots=True)
class CommitReceipt:
    """What the commit wrote, in order — the evidence the boundary rule is honoured."""

    writes: list[WriteRecord] = field(default_factory=list)
    checkpoint: Checkpoint | None = None

    def kinds(self) -> tuple[str, ...]:
        return tuple(write.kind for write in self.writes)

    def count(self, kind: str) -> int:
        return sum(1 for write in self.writes if write.kind == kind)

    def checkpoint_is_last(self) -> bool:
        """The checkpoint is the commit's last write, and there is exactly one of it."""
        kinds = self.kinds()
        return bool(kinds) and kinds[-1] == WRITE_CHECKPOINT and self.count(WRITE_CHECKPOINT) == 1

    def order_is_contractual(self) -> bool:
        """Every write appears in `COMMIT_ORDER`'s order, with repeats allowed inside a stage."""
        positions = [COMMIT_ORDER.index(write.kind) for write in self.writes]
        return positions == sorted(positions)


def write_checkpoint(paths: TaskPaths, checkpoint: Checkpoint) -> Path:
    """Temp file, then rename — so a checkpoint on disk is always whole."""
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        checkpoint.model_dump(mode="json"), separators=(",", ":"), ensure_ascii=False
    )
    paths.checkpoint_temp.write_text(body, encoding="utf-8")
    paths.checkpoint_temp.replace(paths.checkpoint)
    return paths.checkpoint


def build_checkpoint(
    state: BrainState,
    *,
    seed_hashes: Mapping[str, str],
    extensions: Mapping[str, int] | None = None,
    revision: int = 0,
) -> Checkpoint:
    """The sealed envelope: state, the extension manifest, the seed hashes, the integrity hash."""
    return sealed(
        Checkpoint(
            schema_version=config.CHECKPOINT_SCHEMA_VERSION,
            revision=revision,
            state=state,
            extensions=dict(extensions or {}),
            seed_hashes=dict(seed_hashes),
        )
    )


def commit(
    paths: TaskPaths,
    state: BrainState,
    *,
    predictions: Sequence[TraceRecord] = (),
    seat_calls: Sequence[SeatCallRecord] = (),
    outcomes: Sequence[TraceRecord] = (),
    episodes: Sequence[EpisodeRecord] = (),
    mailbox_writes: Sequence[Interrupt] = (),
    mailbox_deletes: Sequence[str] = (),
    mailbox: MailboxPort | None = None,
    seed_hashes: Mapping[str, str],
    extensions: Mapping[str, int] | None = None,
    revision: int = 0,
) -> CommitReceipt:
    """Perform the boundary commit and return the receipt of what it wrote, in order."""
    receipt = CommitReceipt()

    for record in predictions:
        path = paths.trace(str(record.node))
        if append_trace(path, record) is not None:
            receipt.writes.append(
                WriteRecord(WRITE_PREDICTION, path, record.prediction_key())
            )

    for call in seat_calls:
        # One line per journalled call of the committing pass, keyed
        # `(task, tick, node, call#, member#, outcome)`. A torn tick committed nothing, so its
        # calls have no record yet and a replayed commit writes them; the keyed append makes a
        # re-commit of the same tick a silent no-op, which is what keeps `seat_calls.jsonl` a
        # count of real model calls rather than an estimate (folded: S-18, folded: S-A8).
        if append_seat_call(paths.seat_calls, call) is not None:
            receipt.writes.append(
                WriteRecord(WRITE_SEAT_CALL, paths.seat_calls, str(call.dedupe_key()))
            )

    for record in outcomes:
        path = paths.trace(str(record.node))
        if append_trace(path, record) is not None:
            receipt.writes.append(WriteRecord(WRITE_OUTCOME, path, str(record.ref)))

    for record in episodes:
        if append_episode(paths.episodes, record) is not None:
            receipt.writes.append(
                WriteRecord(WRITE_EPISODE, paths.episodes, record.episode_id)
            )

    if mailbox is not None:
        for identifier in mailbox_deletes:
            mailbox.delete(identifier)
            receipt.writes.append(
                WriteRecord(WRITE_MAILBOX_DELETE, paths.state_dir, identifier)
            )
        for interrupt in mailbox_writes:
            written = mailbox.write(interrupt)
            receipt.writes.append(WriteRecord(WRITE_MAILBOX, written, interrupt.id))

    checkpoint = build_checkpoint(
        state, seed_hashes=seed_hashes, extensions=extensions, revision=revision
    )
    receipt.writes.append(
        WriteRecord(WRITE_CHECKPOINT, write_checkpoint(paths, checkpoint), str(state.tick))
    )
    receipt.checkpoint = checkpoint
    return receipt
