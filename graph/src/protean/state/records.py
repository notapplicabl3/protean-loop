"""The three appended artifacts: `TraceRecord`, `EpisodeRecord`, `JournalEntry`.

`the build specification (not in this mirror)` § Deliverable 2's contract table, § Deliverable 3's commit
protocol, § Deliverable 4's prediction→outcome loop.

`TraceRecord` is **binding contract 3** — two record kinds on one append-only file — and
nothing about it is a builder's default. The two rules that make it enforceable are model
validators here rather than checks in the writer:

* a `prediction` record without a `prediction` payload cannot be constructed at all, and
* an `outcome` record without a `ref` cannot either.

`brain/`'s append path adds the second half of § Deliverable 4's enforcement — an `outcome`
whose `ref` names no *committed* prediction raises and writes nothing — because that half
needs the file, which a model cannot see.

**Outcomes are separate appended records, never in-place edits.** The dedupe key
`(task, tick, node, tier, kind, source)` is what lets an interrupt resolution
(`source: operator_answer`) and an ordinary grading (`source: runtime_grade`) land at the same
resume tick without colliding — the `source` component is load-bearing, not decoration.

**`prediction` and `outcome` are per-node typed models, never open dicts** (folded: U-14):
one payload per row of § Deliverable 4's observable table, so "what this node predicted" and
"what it was graded against" are both readable off the type. Each payload declares a `signal`
literal and the unions are discriminated on it, so a malformed payload is refused at the
right member rather than reported against all nine.

**`input_signature` is one uniform typed model** rather than a per-node union. Builder's
default, changed from U-14's reading and recorded in the dispatch ledger: a signature is a
digest over the node's already-typed input model, so a per-node signature type would restate
the input models without adding a field anyone reads. `InputSignature` names the model it
digested, which keeps the per-node information U-14 was protecting.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import Field, JsonValue, model_validator

from protean.state.base import ProteanModel
from protean.state.calls import FiringDecision
from protean.state.enums import (
    Addressee,
    EpisodeKind,
    EventName,
    GoalStatus,
    MismatchClass,
    NodeName,
    Tier,
    TraceKind,
    TraceSource,
    TrapDetector,
    UnitStatus,
)
from protean.state.outputs import (
    AdmittedContext,
    HomeostasisReport,
    MonitorVerdict,
    RetrievalSet,
    SelectionVerdict,
)
from protean.state.primitives import CostCounters
from protean.state.seats import (
    DirectorDirection,
    ExecutorSummary,
    ManagerPlan,
    SeatEnvelope,
)

# --------------------------------------------------------------------------------------
# Prediction payloads — one per row of Deliverable 4's observable table
# --------------------------------------------------------------------------------------


class HomeostasisPrediction(ProteanModel):
    """"The next tick's cost in its own units", graded against the next report's deltas."""

    signal: Literal["homeostasis_cost"] = "homeostasis_cost"
    next_tick_tokens: int
    next_tick_wall_seconds: float


class HippocampusPrediction(ProteanModel):
    """"The episodes it retrieved will be cited by the seat that consumed them"."""

    signal: Literal["hippocampus_citation"] = "hippocampus_citation"
    episode_ids: list[str] = Field(default_factory=list)


class ThalamusPrediction(ProteanModel):
    """"Which admitted items the seat will cite this tick" — the most load-bearing node."""

    signal: Literal["thalamus_citation"] = "thalamus_citation"
    admitted_ids: list[str] = Field(default_factory=list)


class BasalGangliaPrediction(ProteanModel):
    """"The unit it let through will not be abandoned or trap-flagged this tick".

    The older wording — "not reversed or vetoed downstream" — named no observable, because
    nothing downstream of the gate can reverse it; this one is graded off the unit's next
    `UnitObservation`.
    """

    signal: Literal["gate_unit_survives"] = "gate_unit_survives"
    unit_id: str


class MonitorPrediction(ProteanModel):
    """"The next tick's verdict — repeat or clear"."""

    signal: Literal["monitor_next_verdict"] = "monitor_next_verdict"
    next_verdict_match: bool


class DispatchPrediction(ProteanModel):
    """The unit's `expected` (folded: S-5), graded against this tick's `MonitorVerdict`.

    **Renamed with its signal in build A.1** (folded: S-A28): the observable was minted under
    `Tier.EXECUTOR`, a tier A.1 deletes, so it is now minted from the merged dispatch
    observation under the addressee `dispatch`.
    """

    signal: Literal["dispatch_expectations"] = "dispatch_expectations"
    unit_id: str
    expectation_ids: list[str] = Field(default_factory=list)


class ManagerPrediction(ProteanModel):
    """Its `mismatch_class`, any `trap_dismissed`, and that the unit it emits will pass its
    own `expected` within `manager_horizon` ticks — graded where the horizon closes.

    **Renamed with its signal in build A.1** (folded: S-A28, folded: S-A60): the horizon was
    minted under `Tier.PLANNER` and its threshold is a cortex weights key, and both names move.
    """

    signal: Literal["manager_horizon"] = "manager_horizon"
    unit_id: str
    mismatch_class: MismatchClass | None = None
    trap_dismissed: list[TrapDetector] = Field(default_factory=list)
    horizon_ticks: int


class DirectorPrediction(ProteanModel):
    """"The redirect will restore goal-stack progress within `progress_window`".

    Also minted **synthetically by the runtime** at a `stuck` raise, `source: runtime`, so
    the operator's `operator_answer` outcome has a `ref` (folded: T-7). This is the Misleading detector's
    own input.
    """

    signal: Literal["director_progress"] = "director_progress"
    goal_id: str
    progress_window_ticks: int
    synthetic_stuck: bool = False


class FiringPrediction(ProteanModel):
    """"Nothing for this node arrives in the tick it is skipping" — C3, as the trace records it.

    **Build A.1's ninth signal** (§ Deliverable 1, decision 18, folded: A1-11, folded: S-A18). A
    node that declines its cheap check does no work at its step, so it mints no ordinary
    prediction (folded: D15-5) and this is the tick's record for that folder: the check that ran,
    the value it read and the threshold it read it against — `FiringDecision`'s own three facts,
    carried onto the trace so the learner can see a check that is muting its node.

    **`fired` is carried rather than recomputed**, exactly as on `FiringDecision`: the gate's
    check is structural and has no threshold to recompute it from. A check **fires** at `>=` its
    threshold, so raising the threshold makes the node skip more (folded: S-A91).
    """

    signal: Literal["firing_check"] = "firing_check"
    #: The check that ran, named — one per outer node, beside its body.
    check: str
    #: The `weights.yaml` key the threshold was read from. `""` for the gate's structural check.
    key: str = ""
    value: float
    threshold: float | None = None
    fired: bool


PredictionPayload = Annotated[
    HomeostasisPrediction
    | HippocampusPrediction
    | ThalamusPrediction
    | BasalGangliaPrediction
    | MonitorPrediction
    | DispatchPrediction
    | ManagerPrediction
    | DirectorPrediction
    | FiringPrediction,
    Field(discriminator="signal"),
]

# --------------------------------------------------------------------------------------
# Outcome payloads — the runtime derives every one of them, mechanically
# --------------------------------------------------------------------------------------


class HomeostasisOutcome(ProteanModel):
    signal: Literal["homeostasis_cost"] = "homeostasis_cost"
    observed_tokens: int
    observed_wall_seconds: float
    matched: bool


class HippocampusOutcome(ProteanModel):
    signal: Literal["hippocampus_citation"] = "hippocampus_citation"
    cited_episode_ids: list[str] = Field(default_factory=list)
    matched: bool


class ThalamusOutcome(ProteanModel):
    signal: Literal["thalamus_citation"] = "thalamus_citation"
    cited_admitted_ids: list[str] = Field(default_factory=list)
    matched: bool


class BasalGangliaOutcome(ProteanModel):
    signal: Literal["gate_unit_survives"] = "gate_unit_survives"
    abandoned: bool
    trap_flagged: bool
    matched: bool


class MonitorOutcome(ProteanModel):
    signal: Literal["monitor_next_verdict"] = "monitor_next_verdict"
    observed_match: bool
    matched: bool


class DispatchOutcome(ProteanModel):
    signal: Literal["dispatch_expectations"] = "dispatch_expectations"
    verdict_match: bool
    failed_predicate_ids: list[str] = Field(default_factory=list)
    matched: bool


class ManagerOutcome(ProteanModel):
    signal: Literal["manager_horizon"] = "manager_horizon"
    passed_within_horizon: bool
    matched: bool


class DirectorOutcome(ProteanModel):
    signal: Literal["director_progress"] = "director_progress"
    progress_observed: bool
    matched: bool


class FiringOutcome(ProteanModel):
    """The skip, graded at the next boundary against whether anything for that node arrived.

    § Deliverable 1: the runtime "grades it at the next boundary against whether anything for
    that node arrived in the tick it skipped". `work_arrived` is that observable and `matched`
    is its negation — a decline is right exactly when nothing for the node turned up.
    """

    signal: Literal["firing_check"] = "firing_check"
    work_arrived: bool
    matched: bool


class OperatorAnswerOutcome(ProteanModel):
    """The one outcome no code derives: The operator's answer, copied to trace on resolution.

    `source: operator_answer`, keyed to the **resume** tick, `ref` to the raise-tick prediction.
    `matched` is optional because an answer is not a grade — the operator's answers are the top
    reinforcement signal, not a verdict on the node that asked.
    """

    signal: Literal["operator_answer"] = "operator_answer"
    question: str
    answer: str
    matched: bool | None = None


OutcomePayload = Annotated[
    HomeostasisOutcome
    | HippocampusOutcome
    | ThalamusOutcome
    | BasalGangliaOutcome
    | MonitorOutcome
    | DispatchOutcome
    | ManagerOutcome
    | DirectorOutcome
    | FiringOutcome
    | OperatorAnswerOutcome,
    Field(discriminator="signal"),
]

#: The six node outputs, the seat results — **and C3 `FiringDecision`** (folded: S-A93). A
#: skipped node's `call# = 0` entry carries its decision as that entry's `output` and is
#: unconstructible until the union names it, which is why § Scaffold clause item 2 enumerates
#: this one member addition rather than leaving it to read as a breach of its own closure.
#: `LatestOutputs` types its slots **per node** rather than on this union, so contract 1 does
#: not move with it. **The check that produces one is order W6's**; the union member is here.
NodeOutputPayload = Annotated[
    HomeostasisReport
    | RetrievalSet
    | AdmittedContext
    | SelectionVerdict
    | MonitorVerdict
    | DirectorDirection
    | ManagerPlan
    | ExecutorSummary
    | FiringDecision,
    Field(discriminator="emitter"),
]

# --------------------------------------------------------------------------------------
# The records themselves
# --------------------------------------------------------------------------------------

#: The suffix `prediction_key()` adds for a **firing** prediction and for nothing else
#: (contract 3's fifth amendment). Spelled once and imported by `protean.brain.trace`, which
#: carries the second implementation of the key: the two suffix on the same condition, the
#: record's `source == firing`, and G15 asserts they agree byte for byte.
FIRING_KEY_SUFFIX: Final[str] = ":firing"


class InputSignature(ProteanModel):
    """A digest over the node's typed input model, naming the model it digested.

    **`tier` is the addressee in build A.1** (§ Scaffold clause item 2, contract 3's third
    amendment, folded: S-A61): a `dispatch` signature has a legal place to sit under the cortex
    folder, which it would not have under a tier set that no longer names the executor.
    """

    node: NodeName
    tier: Addressee | None = None
    model: str
    digest: str


class TraceRecord(ProteanModel):
    """Two kinds on one append-only file, per node folder (binding contract 3).

    **`tier` becomes the addressee in build A.1** (§ Scaffold clause item 2, contract 3's third
    amendment, folded: S-A61), so a `dispatch` record sits under the cortex folder legally
    rather than under a tier the build deleted. The two renamed signal literals —
    `dispatch_expectations` and `manager_horizon` — are the second amendment; the `firing_check`
    union members, the widened per-kind source validator and `prediction_key()`'s `:firing`
    suffix are amendments (a), (d) and (e), landed by **order W7**.
    """

    schema_version: int
    task: str
    tick: int
    node: NodeName
    tier: Addressee | None = None
    kind: TraceKind
    source: TraceSource
    input_signature: InputSignature | None = None
    prediction: PredictionPayload | None = None
    outcome: OutcomePayload | None = None
    ref: str | None = None
    scored_at_tick: int | None = None

    @model_validator(mode="after")
    def _the_two_kinds_are_not_interchangeable(self) -> "TraceRecord":
        if (self.tier is not None) != (self.node is NodeName.CORTEX):
            raise ValueError(
                f"tier is the cortex folder's key and only the cortex folder's: "
                f"node={self.node}, tier={self.tier}"
            )
        if self.kind is TraceKind.PREDICTION:
            if self.source not in (TraceSource.NODE, TraceSource.RUNTIME, TraceSource.FIRING):
                raise ValueError(
                    f"a prediction's source is node|runtime|firing, not {self.source} "
                    f"(runtime only for the synthetic stuck prediction, firing for a skip)"
                )
            if self.prediction is None:
                raise ValueError(
                    "a prediction-kind record with no prediction is refused — "
                    "a node that records no prediction cannot learn"
                )
            if self.outcome is not None or self.ref is not None:
                raise ValueError("a prediction-kind record carries no outcome and no ref")
        else:
            if self.source not in (
                TraceSource.RUNTIME_GRADE,
                TraceSource.OPERATOR_ANSWER,
                TraceSource.FIRING_GRADE,
            ):
                raise ValueError(
                    f"an outcome's source is runtime_grade|operator_answer|firing_grade, "
                    f"not {self.source}"
                )
            if self.outcome is None:
                raise ValueError("an outcome-kind record with no outcome is refused")
            if self.ref is None:
                raise ValueError(
                    "an outcome-kind record with no ref names no prediction to grade"
                )
            if self.prediction is not None:
                raise ValueError("an outcome-kind record carries no prediction")
        return self

    def dedupe_key(self) -> tuple[str, int, str, str | None, str, str]:
        """`(task, tick, node, tier, kind, source)` — a collision is a silent no-op on replay."""
        return (
            self.task,
            self.tick,
            str(self.node),
            str(self.tier) if self.tier is not None else None,
            str(self.kind),
            str(self.source),
        )

    def prediction_key(self) -> str:
        """The key an outcome's `ref` names. Only meaningful on a `prediction` record.

        **A firing prediction takes a `:firing` suffix and nothing else does** (§ Scaffold clause
        item 2, contract 3's fifth amendment, folded: S-A83). The dedupe key separates the two
        trace *lines* a node writes when it records both a firing prediction and its own; this
        key is what an outcome's `ref` names, and without the suffix one of homeostasis's two
        predictions could never be graded. **Every existing `ref` stays byte-identical** — the
        suffix is keyed on the record's `source == firing`, which no prediction carried before
        A.1. `protean.brain.trace.prediction_key()` is the second implementation of this key and
        suffixes on the same condition; a suffix here alone would make every firing grade a
        `TraceAppendRefused` (folded: S-A89).
        """
        tier = str(self.tier) if self.tier is not None else "-"
        suffix = FIRING_KEY_SUFFIX if self.source is TraceSource.FIRING else ""
        return f"{self.task}:{self.tick}:{self.node}:{tier}:prediction{suffix}"


class GoalSnapshot(ProteanModel):
    """A goal id and its status, as of one tick."""

    id: str
    status: GoalStatus


class UnitSnapshot(ProteanModel):
    """A unit id and its status, as of one tick."""

    id: str
    status: UnitStatus


class EpisodeRecord(ProteanModel):
    """One FILE per task holding many records: `brain/episodes/<task_id>/episodes.jsonl`.

    `tick` records are composed by the hippocampus and written by the runtime at the boundary;
    `event` records are runtime-authored — task start, lock reclamation, interrupt resolution,
    terminal, abandoned, reseeded, and a losing terminal condition. Dedupe key
    `(task, tick, kind, event_name)`.
    """

    schema_version: int
    episode_id: str
    task: str
    tick: int
    kind: EpisodeKind
    event_name: EventName | None = None
    goals: list[GoalSnapshot] = Field(default_factory=list)
    units: list[UnitSnapshot] = Field(default_factory=list)
    verdict: MonitorVerdict | None = None
    cost: CostCounters = Field(default_factory=CostCounters)
    detail: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _event_records_are_named(self) -> "EpisodeRecord":
        if self.kind is EpisodeKind.EVENT and self.event_name is None:
            raise ValueError("an event record carries an event_name; it is half its dedupe key")
        if self.kind is EpisodeKind.TICK and self.event_name is not None:
            raise ValueError("a tick record carries no event_name")
        return self

    def dedupe_key(self) -> tuple[str, int, str, str | None]:
        """`(task, tick, kind, event_name)` (folded: T-5)."""
        return (
            self.task,
            self.tick,
            str(self.kind),
            str(self.event_name) if self.event_name is not None else None,
        )


#: The reserved `call#` of a node's **own output entry** (`the build specification (not in this mirror)`
#: § Deliverable 6, folded: A1-9, folded: S-A76). Every node still writes one entry carrying its
#: `output` and that entry takes this key; **model calls number from 1**. Without the
#: reservation a skipped node's decision entry and its first call entry would contend for 1.
OUTPUT_CALL_NUMBER: Final[int] = 0


class JournalEntry(ProteanModel):
    """Runtime → `journal-<tick>.jsonl`, keyed `(task, tick, node, call#[, member#])`.

    Crash forensics, observability, **and the seat-envelope store** — a re-run restores the
    journaled envelope rather than re-invoking the call (folded: S-4), which is what makes the
    journal a loaded artifact and therefore a versioned contract. It is never a resume point:
    the checkpoint's presence is the definition of "tick completed".

    **One entry per call, and the key generalizes rather than the model**
    (`the build specification (not in this mirror)` § Deliverable 6, folded: A1-2). Build 1's rule is
    unchanged in meaning and only its cardinality moves: the seat's single exception becomes the
    rule. A tick holds the node's own output entry at `OUTPUT_CALL_NUMBER` plus one entry per
    model call, numbered from 1 per node — a dispatch wave taking one `call#` and its members a
    `member#` sub-key beneath it (**the wave itself is order W8's**; the key's shape is here so
    they have somewhere to sit).

    **A call entry is written once, at return** (folded: S-A50), so a call that never returned
    leaves no entry to reconcile and a replay re-invokes it in place. What it carries is
    § Deliverable 4's table — the **addressee**, the **request payload**, the **kind** and the
    **block reference**, beside the returned **envelope** — "what a re-invoke needs, and nothing
    more"; the argv, the effective caps and the usage live on the receipt, so no fact has two
    homes. An entry whose `envelope` is `None` is a call that returned a **refusal**: journalled
    and counted (§ Deliverable 2), with no result to restore.

    **`tier` is the addressee, and it is optional** (§ Deliverable 6): a think call has no tier,
    and a node's own output entry has no addressee at all — `SeatCallRecord.tier` has the same
    hole for the same reason, so both columns moved together. The landed
    `_the_envelope_rides_the_seat_entry` validator enforced the two halves of the old one-call
    shape together — `tier` set exactly when the node is the cortex, and only the cortex entry
    carrying an envelope — and is **removed whole**, because every node's entry may now carry
    both.
    """

    schema_version: int
    task: str
    tick: int
    node: NodeName
    #: The key's fourth component. `OUTPUT_CALL_NUMBER` is the node's own output entry.
    call_number: int = Field(default=OUTPUT_CALL_NUMBER, ge=0)
    #: The wave member's sub-key beneath the wave's one `call#`. `None` outside a wave, which is
    #: every call A.1 makes — the wave is order W8's.
    member_number: int | None = None
    #: The **addressee** this entry's call was sent to: a `Tier` for a seat call, a call type for
    #: everything else. `None` on a node's own output entry.
    tier: Addressee | None = None
    #: The request as sent, dumped to JSON, with the model it came from named beside it — C1
    #: `NodeCall`'s own shape (folded: D3-2). The journal holds it in full; the receipt does not.
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    payload_model: str = ""
    #: The subagent kind that answered, for a call that names one. The one field § Deliverable 4
    #: licenses to appear on both artifacts, because a receipt read alone must say what ran.
    kind: str = ""
    #: The containment block this call resolved. **A.1 fixes the field and A.1.i fills it.**
    block_ref: str = ""
    output: NodeOutputPayload | None = None
    envelope: SeatEnvelope | None = None

    def dedupe_key(self) -> tuple[str, int, str, int, int | None]:
        """`(task, tick, node, call#, member#)` — overwritten on replay, never appended twice.

        The same key C2 `SubagentSpawn.key()` names, so the two artifacts one tier-three call is
        split across sit under one key rather than two that have to be joined.
        """
        return (self.task, self.tick, str(self.node), self.call_number, self.member_number)

    def is_call(self) -> bool:
        """Whether this entry records a **call** rather than the node's own output."""
        return self.call_number != OUTPUT_CALL_NUMBER

    def is_restorable(self) -> bool:
        """Whether a replay restores this call instead of re-invoking it (§ Deliverable 6).

        The condition is **a restorable result being present**, never an entry existing: an entry
        recording a refusal or a timeout carries no envelope, so that call is re-invoked in place
        while the journalled calls after it still restore.
        """
        return self.is_call() and self.envelope is not None
