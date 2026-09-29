"""The five deterministic node output models — measure, fetch, veto; never choose.

`the build specification (not in this mirror)` § Deliverable 2's contract table (`HomeostasisReport`,
`RetrievalSet`, `AdmittedContext`, `SelectionVerdict`, `MonitorVerdict`) and § Deliverable 4's
trap-detector table.

**"No deterministic node's output model contains a branch instruction"** (§ Deliverable 2) is
a property of this file and it is checkable by reading it: every field below is a measurement,
a retrieved set, an admitted subset, a veto, or a scalar. The two exceptions are the two
contractual inhibitions the doctrine allows — `SelectionVerdict.decision` and
`HomeostasisReport.stop` — and both are named as such rather than dressed as advice.

**Every output carries `tick` and an optional `interrupt`.** The tick stamp is what makes
`LatestOutputs` "one typed, tick-stamped slot per node" without a wrapper type; the interrupt
slot is § Deliverable 5's raise path — a node *requests* an interrupt as ordinary output and
never writes the mailbox itself.

**`emitter` is a discriminator, not decoration.** `JournalEntry.output` and `LatestOutputs`
hold these models side by side, and two of them (`DirectorDirection`, `ManagerPlan`) have no
required field beyond `tick`; without a literal tag a journal line would be ambiguous on
reload, which would make the seat-envelope restore of § Deliverable 3 unsound.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from protean.state.base import ProteanModel
from protean.state.enums import SelectionDecision
from protean.state.interrupts import InterruptRequest
from protean.state.primitives import TrapScalar


class NodeOutput(ProteanModel):
    """The shape every node output shares. Not itself a contract — never instantiated."""

    tick: int
    interrupt: InterruptRequest | None = None


class HomeostasisReport(NodeOutput):
    """Homeostasis → state: the read-out of `BrainState.cost` (folded: U-13).

    Cumulative per task (folded: S-13). `stop` is homeostasis's contractual stop — one of the
    build's only two inhibitions — and it commits `stopped` at the boundary, never mid-node.
    """

    emitter: Literal["homeostasis"] = "homeostasis"
    tokens: int
    wall_seconds: float
    error_rate: float
    ticks: int
    ceilings: dict[str, float] = Field(default_factory=dict)
    stop: bool = False
    stop_reason: str | None = None


class RetrievedEpisode(ProteanModel):
    """One candidate, with a stable `episode_id` the thalamus and the grader both key on.

    **One list, two kinds** (build 2, folded: S-2, A1-12). `episode_id` is the retrieval key, and
    a seeded semantic chunk rides the same list under its own `semantic:<sha>` id — the prefix is
    what makes the kind readable to the thalamus without a second list or a discriminator field.
    `text` is the chunk's body and is `None` for an episode, whose body is `episodes.jsonl`'s to
    hold; it exists because under the inherited pipeline only an *id* ever reached a seat, and a
    store of the policy home text that arrives as an id is a store the seat cannot read.
    """

    episode_id: str
    score: float
    #: The chunk's text, carried to `AdmittedItem.summary` by the thalamus. `None` for an episode.
    text: str | None = None


class RetrievalSet(NodeOutput):
    """Hippocampus → thalamus: candidate episodes with retrieval scores."""

    emitter: Literal["hippocampus"] = "hippocampus"
    candidates: list[RetrievedEpisode] = Field(default_factory=list)


class AdmittedItem(ProteanModel):
    """An admitted item and its stable `admitted_id` — the thalamus's prediction grades on it."""

    admitted_id: str
    episode_id: str | None = None
    summary: str
    score: float


class ExcludedItem(ProteanModel):
    """What was kept out and why. The exclusion is visible, which is what makes it a signal."""

    episode_id: str
    reason: str


class AdmittedContext(NodeOutput):
    """Thalamus → state, basal ganglia, seat (folded: S-9).

    The admitted subset **plus what was excluded and why** — a *signal*, with the exclusion
    visible, rather than a silent filter.
    """

    emitter: Literal["thalamus"] = "thalamus"
    admitted: list[AdmittedItem] = Field(default_factory=list)
    excluded: list[ExcludedItem] = Field(default_factory=list)


class SelectionVerdict(NodeOutput):
    """Basal ganglia → runtime. A `no_go` is **contractual inhibition** (`DIGEST:51`).

    A.1 inhibits the pending unit's dispatch wave and delegates; the runtime also skips the
    selected seat, as documented in `brain/nodes/basal_ganglia/NODE.md`. The veto predicate is catastrophic-only (folded: T-13): `no_go` iff an
    `Expectation` argument path lies outside the task workspace root as narrowed by any
    `path_scope` constraint, or the unit carries `irreversible: true` with no
    `allow_irreversible` constraint naming it. Nothing else vetoes.
    """

    emitter: Literal["basal_ganglia"] = "basal_ganglia"
    decision: SelectionDecision
    unit_id: str | None = None
    veto_reason: str | None = None


class MonitorVerdict(NodeOutput):
    """Anterior cingulate → state, router. Mechanical, never a judgment (folded: S-7).

    `traps` carries the six scalars, each with the weights key that scored it — the evidence
    body of a `stuck` interrupt is assembled from exactly these (folded: Ruling 16). A signal
    past its threshold is **not** a stop: it feeds the ladder, and only the ladder's last rung
    ends the task.
    """

    emitter: Literal["anterior_cingulate"] = "anterior_cingulate"
    unit_id: str | None = None
    match: bool
    failed_predicate_ids: list[str] = Field(default_factory=list)
    passed_predicate_ids: list[str] = Field(default_factory=list)
    streak: int = 0
    traps: list[TrapScalar] = Field(default_factory=list)
