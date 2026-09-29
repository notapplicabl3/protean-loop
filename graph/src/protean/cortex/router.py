"""The seat router: one **seat** per tick over two tiers, chosen from workspace signals alone.

**Route R14** (`the build specification (not in this mirror)` § Deliverable R, § Deliverable 3,
folded: S-A33). **The arm → seat mapping, in one sentence:** the two arms that already select
the director — redirects spent, replans spent — keep selecting it, and every other arm, the
fall-through included, selects the **manager**. Only the fall-through moved, from the deleted
executor seat to the manager; no arm changed its condition. On a director tick no dispatch wave
is assembled at all.

**Tier three is not a seat and is never routed to.** A subagent is *dispatched* by the manager,
not *selected* by this router: it has no member in `Tier`, no block in `brain/seats.yaml` and no
session handle, and the wave that carries it rides the manager's own result.

`the build specification (not in this mirror)` § Deliverable 6 → *The seat router* (folded: A1-13): "One
router selects the tier from workspace signals only — the monitor's verdict streak, its trap
signals (folded: Ruling 16), the manager's mismatch classification, an empty work-unit stack.
**Its thresholds are data, and each has exactly one owner**."

**It answers on every tick, including one whose seat call the runtime skips.** § Deliverable 3's
two skip conditions — the gate's veto and a mid-tick terminal — skip the *call*, never the
routing; selecting a seat is a pure function of workspace signals, calls nothing and changes no
state, and rung 1 of the ladder is always the manager, so there is always a seat to name.

**The order of the rules is the ladder read downwards.** A resolved `stuck` answer outranks
everything, because it is the one signal that says the climb just restarted; then an empty unit
stack, which is the only state in which no other seat has anything to do; then rung 3, rung 2
and rung 1; and the manager is what is left when nothing has escalated.

**The router is also where the task opens.** `protean.runtime.seat.SeatPort` is
`(tier, request) -> SeatEnvelope` and carries no task id — so the one place in this package that
always sees `Workspace.task_id` is here, and the session book learns the current task from it.
The runtime calls the router before the port on every tick, which is what makes that ordering
sound.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from protean.cortex.ladder import (
    LadderWeights,
    answered_this_tick,
    leading_goal,
    passed_unit,
    redirects_are_spent,
    replans_are_spent,
    streak_is_spent,
    traps_for_unit,
    unit_stack_is_empty,
    vetoed_unit,
    fired_traps,
)
from protean.runtime.seat import SeatSelection
from protean.state.enums import Escalation, InterruptKind, Tier
from protean.state.workspace import Workspace


@dataclass(slots=True)
class LadderRouter:
    """`protean.runtime.seat.TierSelector` over the three rungs. Records what it chose."""

    weights: LadderWeights
    on_tick: Callable[[str, SeatSelection], None] | None = None
    selections: list[SeatSelection] = field(default_factory=list)

    def __call__(self, workspace: Workspace) -> SeatSelection:
        selection = self.select(workspace)
        self.selections.append(selection)
        if self.on_tick is not None:
            self.on_tick(workspace.task_id, selection)
        return selection

    def select(self, workspace: Workspace) -> SeatSelection:
        """Which seat this tick belongs to, and the reason. Pure; reads only the workspace."""
        goal = leading_goal(workspace)
        verdict = workspace.latest.anterior_cingulate

        # A `stuck` answer has just landed in committed state. The exhausted rung was the
        # director's, so the escalation that names it is the one the answer resolves; the
        # manager takes it, because rung 1 is always the manager and an answer is a monitor
        # escalation of the loudest kind.
        if answered_this_tick(workspace, str(InterruptKind.STUCK)):
            return SeatSelection(
                tier=Tier.MANAGER, escalation=Escalation.REDIRECT_EXHAUSTED
            )

        # Nothing to act on: the manager is the only seat with work. Two shapes reach here —
        # no plan has been made yet, and the last unit came back passing — and the selection
        # tells them apart by naming the unit in the second, which is what lets one script
        # answer the opening call and the closing one differently without counting calls.
        if unit_stack_is_empty(workspace):
            return SeatSelection(
                tier=Tier.MANAGER, escalation=Escalation.EMPTY_UNIT_STACK
            )
        passed = passed_unit(workspace)
        if passed is not None:
            return SeatSelection(
                tier=Tier.MANAGER,
                escalation=Escalation.EMPTY_UNIT_STACK,
                unit_id=passed,
            )

        # Rung 3's routing half — the redirects are spent and the runtime has not yet found the
        # progress window closed. The tick stays with the director rather than falling back to
        # the act, so the ladder never un-climbs itself.
        if redirects_are_spent(goal, self.weights):
            return SeatSelection(
                tier=Tier.DIRECTOR, escalation=Escalation.REDIRECT_EXHAUSTED
            )

        # Rung 2 — the same goal item re-planned `k_replan` times with no predicate progress.
        if replans_are_spent(goal, self.weights):
            return SeatSelection(
                tier=Tier.DIRECTOR, escalation=Escalation.REPLAN_EXHAUSTED
            )

        # Rung 1, the veto arm (decision 29): the vetoed unit goes to the manager on the next
        # tick, rung 1 directly, where it is re-planned, abandoned, or granted a constraint.
        vetoed = vetoed_unit(workspace)
        if vetoed is not None:
            return SeatSelection(
                tier=Tier.MANAGER, escalation=Escalation.VETO, unit_id=vetoed
            )

        # Rung 1, the trap arm: a signal past its threshold hands the unit to a judgment seat,
        # which may dismiss it. A signal is never a stop (Ruling 16 (a)). The unit id comes off
        # the scalar rather than off the verdict, because a scalar names the unit it measured
        # even on a tick the monitor graded nothing.
        traps = fired_traps(verdict)
        if traps:
            unit_id = traps[0].unit_id
            return SeatSelection(
                tier=Tier.MANAGER,
                escalation=Escalation.TRAP_SIGNAL,
                unit_id=unit_id,
                trap_evidence=traps_for_unit(verdict, unit_id),
            )

        # Rung 1, the streak arm: consecutive mismatches past the monitor's own threshold.
        if streak_is_spent(workspace, self.weights) and verdict is not None:
            return SeatSelection(
                tier=Tier.MANAGER,
                escalation=Escalation.MISMATCH_STREAK,
                unit_id=verdict.unit_id,
            )

        # Nothing escalated: the tick's work. **This is the one arm that moved** — from the
        # deleted executor seat to the manager (§ Deliverable 3, folded: S-A33); every other
        # arm keeps its condition. The manager assembles the tick's single dispatch wave at its
        # own step; the unit is still the runtime's to pick, since it holds the unit stack and
        # the workspace does not, so the selection names the seat and leaves it.
        #
        # **This arm carries no escalation, and `ManagerRequest.escalation` is required** — see
        # the builder's ledger entry D3-4 for `plans/deltas/buildA1-graph-reframe-dispatch-3.md`.
        # The fix is a contract-2 amendment § Scaffold clause item 2 does not enumerate, so it
        # is not made here.
        return SeatSelection(tier=Tier.MANAGER)
