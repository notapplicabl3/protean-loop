"""The five node input models — the read slice each `NODE.md` declares.

`the build specification (not in this mirror)` § Deliverable 2's contract table (`HomeostasisInput` ·
`HippocampusInput` · `ThalamusInput` · `BasalGangliaInput` · `MonitorInput`) and
§ Deliverable 4's `NODE.md` paragraph.

**A node reads nothing else** (folded: S-8, decision 25). Each model is a typed projection the
runtime rebuilds from `BrainState` every tick, and `protean.state.reads` asserts that each
`NODE.md`'s `## Reads` list names exactly the fields declared here — no more, no fewer, drift
refused at startup rather than warned about.

**`weights` is a field on every input model, and that is deliberate.** § Deliverable 4:
"every threshold is a named key in `brain/nodes/anterior_cingulate/weights.yaml`, never a
literal", and decision 25 makes a node a *pure* callable. Those two together leave exactly one
place for a threshold to enter a node: its input model. The runtime loads the folder's
`weights.yaml` and projects it here, so a node module contains no threshold literal and opens
no file — which is also what makes `M11`'s grep over `src/protean/nodes/` provable.

**`MonitorInput` carries the projected `unit_windows` slice**, which is how the six detectors
get history without reading trace (folded: Ruling 16). **`HippocampusInput` carries the last
`candidate_window` records of THIS task's `episodes.jsonl`**, projected by the runtime's
boundary loader; cross-task episodes are build 3's (folded: T-12). It carries **one** further
field in build 2 — `semantic`, the windowed slice of the seeded lexical store — because the
retrieval path was episode-typed end to end and this is the minimum change that opens it
(folded: A1-12, decision 16); the window and the overlap floor sizing it are weights keys
rather than fields, so the read slice grows by exactly one name (folded: S-25).
**`BasalGangliaInput` carries the pending `WorkUnit`, this tick's `AdmittedContext`, and
`constraints`** — the two arms of the catastrophic-only veto predicate and nothing that would
let it choose (folded: T-13).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue

from protean.state.base import ProteanModel
from protean.state.outputs import AdmittedContext, RetrievalSet
from protean.state.primitives import (
    CeilingOverrides,
    Constraint,
    CostCounters,
    GoalItem,
    UnitObservation,
    WorkUnit,
)
from protean.state.records import EpisodeRecord
from protean.state.seats import ExecutorSummary, ThinkResult
from protean.state.semantic import SemanticChunk


class NodeInput(ProteanModel):
    """What every read slice carries. Not itself a contract — never instantiated."""

    task_id: str
    tick: int
    weights: dict[str, JsonValue] = Field(default_factory=dict)


class HomeostasisInput(NodeInput):
    """Cost, the ceilings after any override, the `budget` constraints — and this tick's think.

    **`think_answer` is build A.2.i's one added field** (`the build specification (not in this mirror)`
    § Deliverable 2): the decoded answer to this node's first think of the tick, filled by the
    runtime between the node's calls and its body, on the live and the restore path alike, and
    `None` when the node made no think or its think was refused. **This is S-8's runtime->node
    input model, not contract 1**, on `ThalamusInput.retrieval`'s precedent: `BrainState` and
    `HomeostasisReport` do not move with it, and the body reads nothing of it — a model at this
    node can neither raise the stop nor suppress it.
    """

    cost: CostCounters
    ceiling_overrides: CeilingOverrides
    constraints: list[Constraint] = Field(default_factory=list)
    #: The first think answer of the tick, by `call#`, or `None` — carried, never read by the body.
    think_answer: ThinkResult | None = None


class HippocampusInput(NodeInput):
    """This task's last `candidate_window` episode records, plus the stacks it scores against."""

    goals: list[GoalItem] = Field(default_factory=list)
    units: list[WorkUnit] = Field(default_factory=list)
    candidates: list[EpisodeRecord] = Field(default_factory=list)
    #: The `semantic_window` seeded chunks the boundary loader kept for this tick (build 2, S-25).
    #: One field, not two: the window and the overlap floor are **weights keys**, so `## Reads`
    #: gains exactly this name and the thresholds never become part of the read slice.
    semantic: list[SemanticChunk] = Field(default_factory=list)


class ThalamusInput(NodeInput):
    """What the hippocampus retrieved, and the stacks the admission is judged relevant to.

    **`retrieval` is optional in build A.1** (`the build specification (not in this mirror)`
    § Deliverable 1, folded: S-A92). `projections.thalamus_input()` hands the slot on only when
    its own `tick` stamp is the current tick, so a hippocampus that declined this tick reaches
    this consumer as `None` rather than as last tick's answer wearing this tick's authority — and
    a stamp-tested `None` on a required field would be a validation error rather than a "nothing
    for me". **This is S-8's runtime->node input model, not contract 1**: `BrainState` does not
    move with it, and contract 1's single amendment stays the `LatestOutputs` slot renames.
    """

    retrieval: RetrievalSet | None = None
    goals: list[GoalItem] = Field(default_factory=list)
    units: list[WorkUnit] = Field(default_factory=list)


class BasalGangliaInput(NodeInput):
    """The pending unit, this tick's admitted context, and the constraints the veto reads.

    **`admitted` is optional in build A.1**, for the same reason `ThalamusInput.retrieval` is and
    through the same one mechanism: `projections.basal_ganglia_input()` stamp-tests the slot. The
    gate still **always runs when a unit is pending**, on its **defined empty input** — a pending
    unit with no admitted context this tick — because neither arm of the catastrophic-only veto
    reads this field (§ Deliverable 1, folded: S-A92).
    """

    pending_unit: WorkUnit | None = None
    admitted: AdmittedContext | None = None
    constraints: list[Constraint] = Field(default_factory=list)
    workspace_root: str


#: What a dispatch wave's merge reports about itself (`the build specification (not in this mirror)`
#: § Deliverable 3, "Where `partial` and `conflicted` live"). `complete` — every member
#: returned and none disagreed; `partial` — a member never returned a legal result; `conflicted`
#: — two members disagreed about one path or one predicate id. They live here because the field
#: below is their only carrier: both nearer ones are closed (S-A14, and contract 2's amendments
#: are already enumerated).
WAVE_COMPLETE = "complete"
WAVE_PARTIAL = "partial"
WAVE_CONFLICTED = "conflicted"
WAVE_STATUSES: tuple[str, ...] = (WAVE_COMPLETE, WAVE_PARTIAL, WAVE_CONFLICTED)


class MonitorInput(NodeInput):
    """The projected `unit_windows` slice — the detectors' only input — and this tick's summary.

    **`wave_status` is build A.1's one added field** (§ Deliverable 3, folded: S-A34): the tick's
    dispatch wave merged `complete`, `partial` or `conflicted`, and it is **optional** because a
    wave-less tick — a director tick, a vetoed tick, every tick build 1, 2 and 3 ran — has no
    wave to report on. `brain/nodes/anterior_cingulate/NODE.md`'s `## Reads` list carries the
    matching line, which row M4 checks against this field list.
    """

    goals: list[GoalItem] = Field(default_factory=list)
    units: list[WorkUnit] = Field(default_factory=list)
    unit_windows: dict[str, list[UnitObservation]] = Field(default_factory=dict)
    trap_dismissals: dict[str, dict[str, int]] = Field(default_factory=dict)
    executor_summary: ExecutorSummary | None = None
    vetoed_unit_id: str | None = None
    #: `complete` · `partial` · `conflicted`, or `None` on a tick that assembled no wave.
    wave_status: Literal["complete", "partial", "conflicted"] | None = None
    #: Build A.2.i's think-answer carrier (`the build specification (not in this mirror)` § Deliverable 2):
    #: this node's first think answer of the tick, by `call#`, filled by the runtime before the
    #: body on the live and restore paths, `None` when there was none or it was refused. S-8's
    #: runtime->node field, not contract 1; the verdict stays mechanical and reads nothing of it.
    think_answer: ThinkResult | None = None
