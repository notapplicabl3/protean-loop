"""`HabitHit` — the seventh persisted artifact, one line per **habit-answered** tick.

`the build specification (not in this mirror)` § Deliverable 4 (seam contract P3), § Directional decisions
13 and 14, § Resolutions A1-2, S-1, S-5, S-18, D16-7.

**It exists because `seat_calls.jsonl` may not be widened.** Build 2's seam contract S2 fixes
that file at one line per **live** invocation and its row W3 is landed and probat-verified;
a habit-answered tick makes no invocation, so a line there would falsify a verified check
(§ Directional decisions 14). The habit gets its own file instead, in the same shape and beside
it — `brain/state/<task_id>/habit_hits.jsonl`, task-keyed like the checkpoints — so the two are
counted the same way.

**"Calls drop" is then an identity, not an estimate** (folded: S-1). Per tier:
`ticks at which the seat step invoked a model or matched a procedure == distinct (tick, tier)
keys in seat_calls.jsonl + habit_hits.jsonl lines`. A decode retry's second `seat_calls` line
collapses to its tick (S-8) and a vetoed or skipped seat step counts on neither side — which is
why the key here is `(task, tick, tier)` and carries no fourth component: a tick answers from at
most one procedure per tier, so there is no retry shape to keep apart.

**The runtime composes it at the tick boundary**, from the layer's third optional seam plus
`task`, `tick` and `ref` — exactly the split `SeatCallRecord.from_facts()` makes, and for the
same reason (folded: S-18): the matcher does not know the tick it answered and the cortex
prediction it belongs to is minted after it. A layer without the seam matches nothing and this
file never appears.

**`ref` is the join, and it is what makes a habit un-learnable.** It names the cortex-trace
prediction the habit-answered tick still recorded, so `protean sleep` grades the habit by the
`matched` flag of that prediction's outcome (`protean.sleep.habits.read_habit_hits`, ledger
`D16-7`) and withdraws a procedure that stops working. A hit with no `ref` would be a habit
nothing could question.

**The writer and the loader live here** rather than under `protean.brain/`, on
`protean.state.seat_calls`'s own precedent — order W7's writable set names this module and not
that package. Both go through `protean.brain.jsonl.append_keyed`, so the append-only and
keyed-idempotent rules are the same physical ones every other appended artifact gets.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import Field, JsonValue

from protean import config
from protean.brain.jsonl import append_keyed, read_lines
from protean.state.base import ProteanModel
from protean.state.enums import Tier
from protean.state.errors import SchemaVersionMismatch

if TYPE_CHECKING:  # pragma: no cover - the annotation only, so `state` imports no `runtime`
    from protean.runtime.seat import HabitFacts

#: The artifact name the refusal quotes, so a captured `SchemaVersionMismatch` names the file.
ARTIFACT = "habit_hits"


class HabitHit(ProteanModel):
    """One habit-answered tick, as `brain/state/<task_id>/habit_hits.jsonl` holds it.

    The eight fields § Deliverable 4 names and no more. The four the withdrawal reader joins on
    — `procedure_id`, `task`, `tick`, `ref` — are required by that reader (ledger `D16-7`); the
    other four are what makes the line readable on its own: which tier answered, which condition
    matched, and which model the answer stood in for.
    """

    schema_version: int
    task: str
    tick: int
    tier: Tier
    #: The `prediction_key()` of the cortex-trace prediction this tick still recorded — the join
    #: `protean.sleep.habits` grades the habit through. Required, not optional as
    #: `SeatCallRecord.ref` is: a refused *call* mints no tier-keyed record, but a habit-answered
    #: tick always decodes to a result and always mints one.
    ref: str
    #: The compiled habit that answered. Precedence across procedure files is lexical by this
    #: id, first match, at most one per tick (folded: D16-2).
    procedure_id: str
    #: The condition that matched, as the keys it actually bound — a compiled condition binds
    #: `goal_digest` and never `unit_id`, so this is normally the one key.
    matched_condition: dict[str, JsonValue] = Field(default_factory=dict)
    #: The model id `brain/seats.yaml` names for this tier — what the habit stood in for.
    #: Empty on a root that configures no live seat: no model was avoided there.
    avoided_model: str = ""

    @classmethod
    def from_facts(
        cls,
        facts: "HabitFacts",
        *,
        task: str,
        tick: int,
        ref: str,
        schema_version: int | None = None,
    ) -> "HabitHit":
        """Compose the line at the boundary: the seam's facts plus the runtime's three.

        `task`, `tick` and `ref` are passed rather than read off the facts for
        `SeatCallRecord.from_facts()`'s reason unchanged — the matcher does not know them, which
        is why the write is at the boundary (folded: S-18).
        """
        return cls(
            schema_version=(
                config.HABIT_HIT_SCHEMA_VERSION if schema_version is None else schema_version
            ),
            task=task,
            tick=tick,
            tier=Tier(facts.tier),
            ref=ref,
            procedure_id=facts.procedure_id,
            matched_condition=dict(facts.matched_condition),
            avoided_model=facts.avoided_model,
        )

    def dedupe_key(self) -> tuple[str, int, str]:
        """`(task, tick, tier)` — a collision is a silent no-op on replay.

        Three components where `SeatCallRecord`'s has four: `outcome` is there to keep a decode
        retry's two lines apart, and a tick takes at most one procedure per tier, so there is
        nothing here for a fourth component to separate. A replayed tick consults nothing and
        composes nothing, so this key is never re-offered by an ordinary replay either.
        """
        return (self.task, self.tick, str(self.tier))


def dedupe_key(payload: Mapping[str, Any]) -> Hashable:
    """`(task, tick, tier)` — the same key `HabitHit.dedupe_key()` names."""
    return (
        str(payload.get("task")),
        int(payload.get("tick", -1)),
        str(payload.get("tier")),
    )


def append_habit_hit(path: Path, record: HabitHit) -> HabitHit | None:
    """Append one line unless its key is already committed. `None` means already there."""
    written = append_keyed(path, record.model_dump(mode="json"), key_fn=dedupe_key)
    return None if written is None else record


def load_habit_hits(path: Path) -> list[HabitHit]:
    """Every line in one task's file, refusing a `schema_version` this code does not write.

    The refusal is `SchemaVersionMismatch`, which quotes both numbers. Build 3 ships no
    migration path, so a version this loader does not recognise is a stop and not a conversion.

    **This is the strict reader.** `protean.sleep.habits.read_habit_hits()` is deliberately the
    tolerant one — withdrawal joins on four fields and skips a line it cannot read, so a sleep
    run never dies on one malformed hit (ledger `D16-7`). Both read the same eight fields.
    """
    records: list[HabitHit] = []
    for line in read_lines(path):
        found = int(line.get("schema_version", -1))
        if found != config.HABIT_HIT_SCHEMA_VERSION:
            raise SchemaVersionMismatch(
                artifact=ARTIFACT,
                found=found,
                expected=config.HABIT_HIT_SCHEMA_VERSION,
            )
        records.append(HabitHit.model_validate(line))
    return records
