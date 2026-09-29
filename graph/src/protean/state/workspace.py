"""The compressed workspace, the `latest` slots, and the two per-seat requests.

`the build specification (not in this mirror)` § Deliverable 2's contract table (`Workspace`,
`DirectorRequest` · `PlannerRequest`) and § Deliverable 6's seat behaviour. The request models
are **binding contract 2**'s request half.

**Build A.1 amends this module in two of that contract's three named ways**
(`the build specification (not in this mirror)` § Scaffold clause item 2). `PlannerRequest` becomes
`ManagerRequest`, literal and all, payload unchanged; and `ExecutorRequest` is **retired whole**
— its required `workspace_path` is the field a manager could have put any directory in, and
`WaveMember` on `ManagerPlan` replaces it with no path field at all. **Contract 1's single
amendment lands here too**: `LatestOutputs.planner` becomes `.manager` and `.executor` becomes
`.dispatch`, the second holding the tick's **merged** summary rather than one seat's return.
Both change what a committed checkpoint *means*, which is why `BRAIN_STATE_SCHEMA_VERSION` and
`CHECKPOINT_SCHEMA_VERSION` move to 2 and old checkpoints are refused, never migrated.

**The workspace is rebuilt each tick, never accumulated** (folded: S-9). It is a projection:
the goal stack here is a copy, and `BrainState.goals` is authoritative. A workspace that
accumulated would make "the director reads only the compressed workspace" a growing surface
rather than a bounded one.

**One `Workspace` for both seats; the per-seat request model is the filter** (folded: T-11).
There are no per-seat projections — the director's request carries the whole workspace and
nothing else, and the manager's adds the escalation that fired and the trap evidence for the
unit. That asymmetry is § Deliverable 2's table read literally, and it is what *director →
manager → subagents* looks like in types: the director never orchestrates workers, and a
dispatch member is not a seat request at all.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from protean.state.base import ProteanModel
from protean.state.enums import Escalation, MismatchClass
from protean.state.interrupts import ResolvedInterrupt
from protean.state.outputs import (
    AdmittedContext,
    HomeostasisReport,
    MonitorVerdict,
    RetrievalSet,
    SelectionVerdict,
)
from protean.state.primitives import (
    Constraint,
    GoalItem,
    Modulators,
    TrapScalar,
)
from protean.state.seats import DirectorDirection, ExecutorSummary, ManagerPlan


class LatestOutputs(ProteanModel):
    """One typed, tick-stamped slot per node and per **addressee**, optional until it first fires.

    Every input model and the `Workspace` are projected from here, so a node output survives
    the boundary without a second copy. The tick stamp lives on each output model itself.

    **The slots follow the seats** (folded: S-A27). `planner` became `manager` and `executor`
    became `dispatch`, the second holding the tick's **merged** `ExecutorSummary` rather than
    one seat's return: a wave may hold several members and their returns merge into one observed
    state before the monitor grades. The slots are typed **per node** rather than on
    `NodeOutputPayload`, which is why contract 1 is untouched by that union gaining a member.
    """

    homeostasis: HomeostasisReport | None = None
    hippocampus: RetrievalSet | None = None
    thalamus: AdmittedContext | None = None
    basal_ganglia: SelectionVerdict | None = None
    anterior_cingulate: MonitorVerdict | None = None
    director: DirectorDirection | None = None
    manager: ManagerPlan | None = None
    dispatch: ExecutorSummary | None = None


class Workspace(ProteanModel):
    """Runtime → every seat. Rebuilt each tick, never accumulated (folded: S-9)."""

    task_id: str
    tick: int
    goals: list[GoalItem] = Field(default_factory=list)
    latest: LatestOutputs = Field(default_factory=LatestOutputs)
    admitted: AdmittedContext | None = None
    last_mismatch_class: MismatchClass | None = None
    resolved_interrupts: list[ResolvedInterrupt] = Field(default_factory=list)
    modulators: Modulators = Field(default_factory=Modulators)
    constraints: list[Constraint] = Field(default_factory=list)


class DirectorRequest(ProteanModel):
    """Runtime → director: `Workspace` only (§ Deliverable 2, folded: S-11)."""

    tier: Literal["director"] = "director"
    workspace: Workspace


class ManagerRequest(ProteanModel):
    """Runtime → manager: workspace, the escalation that fired, the unit's trap evidence.

    Build 1's `PlannerRequest` renamed, literal and all, the payload unchanged (folded: S-A27).

    **`escalation` is optional, and `None` is a reason rather than its absence** — contract 2's
    fourth amendment (§ Scaffold clause item 2, contract 2 (d), folded: D3-4). Rung 1 of the
    ladder is always the manager and every escalated arm still names the rung it fired on; but
    A.1 moves the **non-escalated acting tick** from the deleted executor seat to the
    manager — the router's fall-through — and that tick carries no escalation at all. `None`
    means "assemble the pending unit's wave"; the request still carries the workspace and the
    unit, so a manager call with no reason to exist is still unexpressible.
    """

    tier: Literal["manager"] = "manager"
    workspace: Workspace
    escalation: Escalation | None = None
    unit_id: str | None = None
    trap_evidence: list[TrapScalar] = Field(default_factory=list)
