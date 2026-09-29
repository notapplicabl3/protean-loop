"""The three rungs of the stuck ladder, as pure predicates over the compressed workspace.

`the build specification (not in this mirror)` § Deliverable 6 → *The stuck ladder* (folded: Ruling 16 [B]),
whose first rung **is always the manager** (build A.1 renamed the planner pair and removed the
executor seat; the fall-through arm — the non-escalated acting tick — is the manager's too):

1. a trap signal past its threshold on a work unit escalates that unit to the **manager**, which
   re-plans it, abandons it, or dismisses the detector;
2. the same goal item re-planned `k_replan` times with no predicate progress escalates to the
   **director**;
3. the director redirecting `k_redirect` times with no goal-stack progress ends the task
   **`stuck`**.

**Rung 3's commit is the runtime's, not this module's.** `protean.runtime.terminal` reads the
same two cortex weights and ends the task; what lives here is the *routing* half — while the
redirects are spent and the progress window has not yet closed, the tick still belongs to the
director. Reading the counts in two places would be a second owner for a threshold, so both
read them from `brain/nodes/cortex/weights.yaml` and neither writes a number.

**Every threshold arrives as data.** No number appears in this package: `LadderWeights` is
loaded from the same two `weights.yaml` files the runtime loads, and a missing key raises rather
than defaulting — a rung silently scored against zero would fire on the first tick, which is the
over-firing Ruling 16 (b) exists to prevent.

**The operator's over-firing constraint, verbatim:** *"make sure this isn't over-firing, we don't want
metaphorical 'over thinking' when we haven't actually reached a stuck state yet."* Every
predicate below therefore reads a **committed count** — a goal's `replan_count`, its
`redirect_count`, a detector scalar that already fired against its own threshold — and none of
them fires on a single tick's signal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from protean import config
from protean.brain.folders import load_weights
from protean.state.enums import (
    CORTEX_WEIGHT_KEYS,
    MONITOR_ROUTER_KEYS,
    GoalStatus,
    NodeName,
    SelectionDecision,
)
from protean.state.outputs import MonitorVerdict
from protean.state.primitives import GoalItem, TrapScalar
from protean.state.workspace import Workspace

#: The cortex weights key rung 2 counts against.
WEIGHT_K_REPLAN = CORTEX_WEIGHT_KEYS[0]

#: The cortex weights key rung 3 counts against.
WEIGHT_K_REDIRECT = CORTEX_WEIGHT_KEYS[1]

#: The anterior cingulate's key the mismatch-streak escalation counts against.
WEIGHT_MISMATCH_STREAK = MONITOR_ROUTER_KEYS[0]


@dataclass(frozen=True, slots=True)
class LadderWeights:
    """The three counts the router reads, each from the file that owns it (folded: S-5)."""

    k_replan: int
    k_redirect: int
    mismatch_streak: int

    @classmethod
    def load(cls, root: Path) -> "LadderWeights":
        """Read them off the same `weights.yaml` files the runtime reads, from one brain root.

        Scenario and runtime therefore can never disagree about what a threshold is: there is
        one file per number and this is not a second copy of it.
        """
        return cls.from_weights(
            cortex=load_weights(_weights_path(root, NodeName.CORTEX)),
            monitor=load_weights(_weights_path(root, NodeName.ANTERIOR_CINGULATE)),
        )

    @classmethod
    def from_weights(
        cls, *, cortex: Mapping[str, Any], monitor: Mapping[str, Any]
    ) -> "LadderWeights":
        """The same three counts, from already-loaded mappings — what the runtime hands a node."""
        return cls(
            k_replan=int(cortex[WEIGHT_K_REPLAN]),
            k_redirect=int(cortex[WEIGHT_K_REDIRECT]),
            mismatch_streak=int(monitor[WEIGHT_MISMATCH_STREAK]),
        )


def _weights_path(root: Path, node: NodeName) -> Path:
    """One node folder's `weights.yaml` under a brain root — `config` owns the layout."""
    return config.node_dir(str(node), root) / "weights.yaml"


def leading_goal(workspace: Workspace) -> GoalItem | None:
    """The open goal the ladder is climbing on. Closed items are retained and never climbed."""
    for goal in workspace.goals:
        if goal.status is GoalStatus.OPEN:
            return goal
    return None


def unit_stack_is_empty(workspace: Workspace) -> bool:
    """No plan has been made, or the last one emitted no unit — the manager's own signal."""
    plan = workspace.latest.manager
    return plan is None or not plan.units


def passed_unit(workspace: Workspace) -> str | None:
    """The unit the monitor graded as matching last tick, if it graded one.

    The compressed workspace carries the goal stack and not the unit stack — the runtime holds
    that — so "there is nothing left to act on" reaches the router as *the last unit passed*.
    A verdict with no `unit_id` graded no unit at all (a manager or director tick) and is not a
    pass; only a matching verdict about a named unit is.
    """
    verdict = workspace.latest.anterior_cingulate
    if verdict is None or verdict.unit_id is None or not verdict.match:
        return None
    return verdict.unit_id


def fired_traps(verdict: MonitorVerdict | None) -> tuple[TrapScalar, ...]:
    """Every trap scalar past its threshold in the last verdict, in the monitor's own order."""
    if verdict is None:
        return ()
    return tuple(scalar for scalar in verdict.traps if scalar.fired)


def traps_for_unit(verdict: MonitorVerdict | None, unit_id: str) -> tuple[TrapScalar, ...]:
    """The fired scalars about one unit — what a manager escalation carries as its evidence."""
    return tuple(scalar for scalar in fired_traps(verdict) if scalar.unit_id == unit_id)


def vetoed_unit(workspace: Workspace) -> str | None:
    """The unit the gate inhibited last tick. A `no_go` sends it to the manager, rung 1 directly."""
    gate = workspace.latest.basal_ganglia
    if gate is None or gate.decision is not SelectionDecision.NO_GO:
        return None
    return gate.unit_id


def streak_is_spent(workspace: Workspace, weights: LadderWeights) -> bool:
    """The monitor's consecutive-mismatch count has reached the threshold that owns it."""
    verdict = workspace.latest.anterior_cingulate
    return verdict is not None and verdict.streak >= weights.mismatch_streak


def replans_are_spent(goal: GoalItem | None, weights: LadderWeights) -> bool:
    """Rung 2: the same goal item re-planned `k_replan` times with no predicate progress."""
    return goal is not None and goal.replan_count >= weights.k_replan


def redirects_are_spent(goal: GoalItem | None, weights: LadderWeights) -> bool:
    """Rung 3's routing half: the director has spent `k_redirect` redirects on this goal.

    The task ends `stuck` when the runtime also finds no goal-stack progress across
    `progress_window`; until that window closes the tick still belongs to the director, and this
    predicate is what keeps it there instead of handing a spent ladder back to the manager's
    dispatch wave.
    """
    return goal is not None and goal.redirect_count >= weights.k_redirect


def answered_this_tick(workspace: Workspace, kind: str) -> bool:
    """An interrupt of this kind was resolved into state at the tick now running.

    § Deliverable 5 puts the answer in `BrainState.resolved_interrupts` "before the next tick
    runs — the landing place that lets an answer change what the brain does next". The
    comparison is against the *current* tick, so the signal is true exactly once and the run
    does not re-route on an answer it has already acted on.
    """
    return any(
        str(item.kind) == kind and item.resolved_at_tick == workspace.tick
        for item in workspace.resolved_interrupts
    )


def escalation_names(selections: Sequence[Any]) -> tuple[str, ...]:
    """`<tier>:<escalation>` per selection — the climb a ladder scenario is graded on."""
    return tuple(
        f"{selection.tier}:{selection.escalation}"
        if selection.escalation is not None
        else str(selection.tier)
        for selection in selections
    )
