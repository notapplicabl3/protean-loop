"""The small shared contracts: goals, work units, expectations, observations, counters.

`the build specification (not in this mirror)` § Deliverable 2 — the `BrainState` table's per-group models
and the contract table's rows `Constraint`, `WorkUnit`, `Expectation`,
`WorkspaceObservation` and `UnitObservation`.

**These are the models more than one layer holds.** A goal item is authoritative in state and
projected into the workspace; a work unit is minted inside a `ManagerPlan`, stored on state,
and handed to the gate and dispatch workers; a `UnitObservation` is composed by the runtime and
read by the six detectors. Putting them below the node and seat contracts is what keeps the
import graph inside `protean.state` a DAG — nothing here imports a node output or a seat
result.

**Two invariants live in this file rather than in prose.** A `WorkUnit`'s `id` is minted by
the manager and *kept across a re-plan* — `revision` increments instead — because a unit that
took a fresh id on every re-plan would reset its trap windows and make the ladder's upper
rungs unreachable (folded: Ruling 16). And `UnitObservation.change_bytes` is **runtime-derived**
against the unit's committed `path_baselines`, never seat-reported (folded: T-9): the field
exists here, the derivation is the runtime's, and no seat can write it.
"""

from __future__ import annotations

from pydantic import Field, JsonValue, model_validator

from protean.state.base import ProteanModel
from protean.state.enums import (
    ConstraintKind,
    ExpectationKind,
    GoalStatus,
    MismatchClass,
    TrapDetector,
    UnitStatus,
)


class Constraint(ProteanModel):
    """Director → state; read by the gate and homeostasis (folded: T-14).

    Typed, never free text. `path_scope` and `allow_irreversible` are read by the veto
    predicate, `budget` by homeostasis; seats read them as data and weigh them.
    """

    kind: ConstraintKind
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    set_at_tick: int


class Expectation(ProteanModel):
    """Manager → monitor. The monitor's build-1 comparator (folded: A1-14, folded: S-7).

    One deterministic predicate over an `ExecutorSummary`, evaluated mechanically. Build 2's
    oracle emits the same type as a second source, which is the whole point of typing it
    here rather than letting the monitor judge.
    """

    id: str
    kind: ExpectationKind
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class WorkUnit(ProteanModel):
    """Inside `ManagerPlan`, and stored on `BrainState.units`.

    `id` is minted by the manager and survives a re-plan; `revision` increments instead
    (decision 28). `irreversible` is the manager's declaration the gate reads — the gate does
    not infer it (folded: T-13).
    """

    id: str
    revision: int = 0
    goal_id: str
    status: UnitStatus = UnitStatus.PENDING
    intent: str
    irreversible: bool = False
    constraints: list[Constraint] = Field(default_factory=list)
    expected: list[Expectation] = Field(default_factory=list)


class GoalItem(ProteanModel):
    """The goal stack's element. Authoritative in state; the workspace's copy is a projection.

    `no_progress_ticks` is **derived** as `tick − last_progress_tick` and never stored
    (folded: T-10) — a stored copy is a second source of truth that a resume can desynchronize.
    `replan_count` and `redirect_count` are the ladder's rungs 2 and 3, counted here because a
    resume that forgot how far it had climbed would restart the climb.
    """

    id: str
    text: str
    status: GoalStatus = GoalStatus.OPEN
    opened_at_tick: int
    last_progress_tick: int
    replan_count: int = 0
    redirect_count: int = 0

    def no_progress_ticks(self, tick: int) -> int:
        """Derived, never stored (folded: T-10)."""
        return tick - self.last_progress_tick


class PathBaseline(ProteanModel):
    """The committed per-path baseline `change_bytes` is derived against (folded: T-9).

    A path absent from the newest `ExecutorSummary` keeps its baseline and counts `0` change,
    so a unit that stopped touching a file does not read as a large delta.
    """

    size_bytes: int
    content_hash: str
    tick: int


class UnitObservation(ProteanModel):
    """The per-tick row the six detectors read — **state only**, inside `unit_windows`.

    Composed at the boundary, and only for a unit that produced an `ExecutorSummary` this
    tick **or was vetoed**. A.1 merges a complete manager dispatch wave into that summary;
    partial or conflicted waves append nothing, as do ticks with neither a summary nor a veto.
    It is never an appended artifact and carries no key of its own (folded: U-7).
    """

    tick: int
    unit_revision: int
    failed_predicate_ids: list[str] = Field(default_factory=list)
    passed_predicate_ids: list[str] = Field(default_factory=list)
    change_bytes: dict[str, int] = Field(default_factory=dict)
    change_bytes_total: int = 0
    paths_new: list[str] = Field(default_factory=list)
    abandoned: bool = False
    vetoed: bool = False
    uncited_ratio: float = 0.0
    redirect_by: str | None = None
    mismatch_class: MismatchClass | None = None


class WorkspaceObservation(ProteanModel):
    """Inside `ExecutorSummary`: one per path the unit touched (folded: A1-15, folded: S-4).

    Path, existence, size and content hash — enough for state to derive from the *observation*
    rather than from the invocation, which is what makes a re-run after a crash inside the
    seat call safe.
    """

    path: str
    exists: bool
    size_bytes: int
    content_hash: str


class CostCounters(ProteanModel):
    """Cumulative per task, written by the runtime at the boundary (folded: U-13, S-13).

    Sourced from `SeatEnvelope.usage`, the runtime's own clock and its error tally — never
    self-reported by a node. `HomeostasisReport` is its read-out.
    """

    tokens: int = 0
    wall_seconds: float = 0.0
    errors: int = 0
    ticks: int = 0


class CeilingOverrides(ProteanModel):
    """What `resume --extend <ticks|minutes>` writes (folded: S-13).

    Without it a resumed `stopped` task re-crosses the ceiling on its first node and exits
    `stopped` again — the override is the only thing that moves the ceiling, and it is
    committed state so a second process sees it.
    """

    extra_ticks: int = 0
    extra_seconds: float = 0.0
    set_at_tick: int | None = None


class Modulators(ProteanModel):
    """The §2.3 (d) state channel — the director's only nudge surface (`DIGEST:64`)."""

    reward_error: float = 0.0
    arousal: float = 0.0
    confidence: float = 0.0


class ProjectExtension(ProteanModel):
    """A namespaced sub-model registered at task start, each with its own version.

    **Adaptation is data** (folded: A1-2): a project extends state by registering here, never
    by adding a core field, and a version mismatch on resume is refused like any other. No
    node writes outside the slice its contract declares.
    """

    name: str
    version: int
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class TrapScalar(ProteanModel):
    """One of the six trap measures, with the weights key that scored it (folded: Ruling 16).

    Carrying the key on the scalar is what makes the evidence body of a `stuck` interrupt
    rulable: The operator reads which signal fired, on which unit, against which threshold.
    """

    detector: TrapDetector
    value: float
    threshold: float
    weight_key: str
    fired: bool
    unit_id: str

    @model_validator(mode="after")
    def _fired_agrees_with_the_measure(self) -> "TrapScalar":
        """A scalar that claimed to fire while sitting under its threshold would make the
        ladder unauditable — the detector and the evidence must be the same number."""
        if self.fired != (self.value >= self.threshold):
            raise ValueError(
                f"{self.detector}: fired={self.fired} disagrees with "
                f"value={self.value} against threshold={self.threshold}"
            )
        return self
