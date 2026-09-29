"""Replay-or-advance: what a resume's first act is, and why.

`the build specification (not in this mirror)` § Deliverable 3 → *Resume's first act depends on how the run
ended* (folded: T-3): "If the journal holds entries for a tick that has no checkpoint, that tick
was interrupted by a crash: restore the last checkpointed state, replay the tick whole, and let
the keyed appends no-op on their surviving orphans. If the last tick is checkpointed with a
`terminal` set, the exit was clean: clear `terminal`, apply the answer or override the terminal
needs, and advance to tick n+1."

**A tick is atomic and the checkpoint's presence is what "completed" means.** So the classifier
is a comparison between the newest checkpoint's tick and the newest journal file's tick, and
nothing else — no marker file, no sixth artifact, no heuristic about how far a tick got.

**The classifier reads `(tick, revision)`** (folded: U-3): an administrative commit — `--extend`,
`--abandon`, `--reseed` — rewrites a tick's checkpoint with an incremented `revision` and no
node run, so "the same tick, a later revision" is a clean state and never a crash.

**Decision 9's "re-runs the interrupted one" names the crash case only.** A clean terminal exit
advances; re-running its last tick would re-raise the interrupt it exited on.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from protean.runtime.journal import has_entries
from protean.runtime.paths import TaskPaths
from protean.state.checkpoint import Checkpoint


class Resumption(StrEnum):
    """The two branches, and there are exactly two."""

    REPLAY = "replay"
    ADVANCE = "advance"


@dataclass(frozen=True, slots=True)
class ResumePlan:
    """Which branch, which tick it runs, and the `(tick, revision)` it was decided from."""

    kind: Resumption
    tick: int
    checkpoint_tick: int
    revision: int

    @property
    def replays(self) -> bool:
        return self.kind is Resumption.REPLAY


def classify(paths: TaskPaths, checkpoint: Checkpoint) -> ResumePlan:
    """Decide replay-or-advance from the checkpoint and the journal files on disk."""
    committed = checkpoint.state.tick
    orphan_ticks = [tick for tick in paths.journal_ticks() if tick > committed]
    crashed = next(
        (tick for tick in orphan_ticks if has_entries(paths.journal(tick))), None
    )
    if crashed is not None:
        return ResumePlan(
            kind=Resumption.REPLAY,
            tick=crashed,
            checkpoint_tick=committed,
            revision=checkpoint.revision,
        )
    return ResumePlan(
        kind=Resumption.ADVANCE,
        tick=committed + 1,
        checkpoint_tick=committed,
        revision=checkpoint.revision,
    )
