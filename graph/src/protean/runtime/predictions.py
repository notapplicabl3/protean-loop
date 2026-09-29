"""Minting one prediction per node folder per tick, from the node's own typed output.

`the build specification (not in this mirror)` § Deliverable 4's observable table and decision 13: "each node
folder writes exactly one prediction record per `(folder, tier)` per tick in which it ran".

**The runtime mints; the node does not.** Decision 25 makes a node a pure callable from a typed
input model to a typed output model, and no output model in `protean.state` carries a prediction
slot — so the prediction is derived mechanically here, from the output the node just produced
plus committed state, and written with `source: node` because the prediction belongs to the node
folder. The one exception is the synthetic `stuck` prediction, `source: runtime`, minted at a
ladder exhaustion so the operator's answer has a `ref` (folded: T-7).

**Every derivation is the table read literally.** Homeostasis forecasts the next tick's cost
increment as this tick's; the hippocampus predicts the episodes it returned will be cited; the
thalamus predicts the admitted items will be cited; the gate predicts the unit it let through
survives; the monitor predicts the next verdict repeats this one. A.1 maps the cortex rows
to director, manager and the merged dispatch observation; dispatch is a call type, not a seat.

**`input_signature` is a digest over the node's already-typed input model**, so "what did this
node see when it predicted that" is answerable without storing the projection twice.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from pydantic import BaseModel

from protean import config
from protean.state.enums import Addressee, CallType, NodeName, Tier, TraceKind, TraceSource
from protean.state.outputs import (
    AdmittedContext,
    HomeostasisReport,
    MonitorVerdict,
    RetrievalSet,
    SelectionVerdict,
)
from protean.state.calls import FiringDecision
from protean.state.records import (
    BasalGangliaPrediction,
    DirectorPrediction,
    DispatchPrediction,
    FiringPrediction,
    HippocampusPrediction,
    HomeostasisPrediction,
    InputSignature,
    MonitorPrediction,
    ManagerPrediction,
    ThalamusPrediction,
    TraceRecord,
)
from protean.state.seats import DirectorDirection, ExecutorSummary, ManagerPlan

#: The subject of a prediction whose subject does not exist this tick — the gate on a tick with
#: no pending unit, the manager with no unit to name, the director with no open goal. The
#: record is still written, because § Deliverable 4 makes it one per folder per tick in which
#: the node ran, and the grader reads the sentinel as "nothing to survive", scoring it matched.
NO_SUBJECT = "-"

#: The cortex weights keys the two horizon predictions carry into their own records.
WEIGHT_MANAGER_HORIZON = "manager_horizon"
WEIGHT_PROGRESS_WINDOW = "progress_window"


def input_signature(node: NodeName | str, payload: BaseModel, tier: Addressee | None = None) -> InputSignature:
    """A sha256 over the input model's canonical JSON, naming the model it digested."""
    body = json.dumps(
        payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return InputSignature(
        node=NodeName(node),
        tier=tier,
        model=type(payload).__name__,
        digest=hashlib.sha256(body.encode("utf-8")).hexdigest(),
    )


def _record(
    *,
    task: str,
    tick: int,
    node: NodeName,
    tier: Addressee | None,
    prediction: Any,
    signature: InputSignature | None,
    source: TraceSource = TraceSource.NODE,
) -> TraceRecord:
    return TraceRecord(
        schema_version=config.TRACE_SCHEMA_VERSION,
        task=task,
        tick=tick,
        node=node,
        tier=tier,
        kind=TraceKind.PREDICTION,
        source=source,
        input_signature=signature,
        prediction=prediction,
    )


def homeostasis(
    *, task: str, tick: int, report: HomeostasisReport, tokens_this_tick: int,
    seconds_this_tick: float, signature: InputSignature | None = None,
) -> TraceRecord:
    """"The next tick's cost in its own units" — a persistence forecast off this tick's spend."""
    return _record(
        task=task,
        tick=tick,
        node=NodeName.HOMEOSTASIS,
        tier=None,
        signature=signature,
        prediction=HomeostasisPrediction(
            next_tick_tokens=tokens_this_tick, next_tick_wall_seconds=seconds_this_tick
        ),
    )


def hippocampus(
    *, task: str, tick: int, retrieval: RetrievalSet, signature: InputSignature | None = None
) -> TraceRecord:
    """"The episodes it retrieved will be cited by the seat that consumed them"."""
    return _record(
        task=task,
        tick=tick,
        node=NodeName.HIPPOCAMPUS,
        tier=None,
        signature=signature,
        prediction=HippocampusPrediction(
            episode_ids=[item.episode_id for item in retrieval.candidates]
        ),
    )


def thalamus(
    *, task: str, tick: int, admitted: AdmittedContext, signature: InputSignature | None = None
) -> TraceRecord:
    """"Which admitted items the seat will cite this tick"."""
    return _record(
        task=task,
        tick=tick,
        node=NodeName.THALAMUS,
        tier=None,
        signature=signature,
        prediction=ThalamusPrediction(
            admitted_ids=[item.admitted_id for item in admitted.admitted]
        ),
    )


def basal_ganglia(
    *, task: str, tick: int, verdict: SelectionVerdict, signature: InputSignature | None = None
) -> TraceRecord:
    """"The unit it let through will not be abandoned or trap-flagged this tick"."""
    return _record(
        task=task,
        tick=tick,
        node=NodeName.BASAL_GANGLIA,
        tier=None,
        signature=signature,
        prediction=BasalGangliaPrediction(unit_id=verdict.unit_id or NO_SUBJECT),
    )


def anterior_cingulate(
    *, task: str, tick: int, verdict: MonitorVerdict, signature: InputSignature | None = None
) -> TraceRecord:
    """"The next tick's verdict — repeat or clear"."""
    return _record(
        task=task,
        tick=tick,
        node=NodeName.ANTERIOR_CINGULATE,
        tier=None,
        signature=signature,
        prediction=MonitorPrediction(next_verdict_match=verdict.match),
    )


def dispatch(
    *, task: str, tick: int, summary: ExecutorSummary, expectation_ids: list[str],
    signature: InputSignature | None = None,
) -> TraceRecord:
    """The unit's `expected` (folded: S-5), graded against this tick's `MonitorVerdict`.

    Minted under the **addressee** `dispatch` rather than under a tier (folded: S-A28): the
    executor seat is gone and the observation this grades is the wave's **merged** one, so the
    record sits under the cortex folder keyed by who emitted it. The wave itself is order W8's.
    """
    return _record(
        task=task,
        tick=tick,
        node=NodeName.CORTEX,
        tier=CallType.DISPATCH,
        signature=signature,
        prediction=DispatchPrediction(unit_id=summary.unit_id, expectation_ids=expectation_ids),
    )


def manager(
    *, task: str, tick: int, plan: ManagerPlan, unit_id: str | None,
    weights: Mapping[str, Any], signature: InputSignature | None = None,
) -> TraceRecord:
    """The mismatch class, any dismissal, and that the emitted unit passes within the horizon."""
    subject = unit_id or (plan.units[0].id if plan.units else NO_SUBJECT)
    return _record(
        task=task,
        tick=tick,
        node=NodeName.CORTEX,
        tier=Tier.MANAGER,
        signature=signature,
        prediction=ManagerPrediction(
            unit_id=subject,
            mismatch_class=plan.mismatch_class,
            trap_dismissed=list(plan.trap_dismissed),
            horizon_ticks=int(weights[WEIGHT_MANAGER_HORIZON]),
        ),
    )


def director(
    *, task: str, tick: int, direction: DirectorDirection, goal_id: str | None,
    weights: Mapping[str, Any], signature: InputSignature | None = None,
) -> TraceRecord:
    """"The redirect will restore goal-stack progress within `progress_window`"."""
    subject = direction.redirect_of or goal_id or NO_SUBJECT
    return _record(
        task=task,
        tick=tick,
        node=NodeName.CORTEX,
        tier=Tier.DIRECTOR,
        signature=signature,
        prediction=DirectorPrediction(
            goal_id=subject,
            progress_window_ticks=int(weights[WEIGHT_PROGRESS_WINDOW]),
        ),
    )


def firing(*, task: str, tick: int, decision: FiringDecision) -> TraceRecord:
    """The skip prediction: one `FiringDecision` onto the trace, `source: firing`.

    **Build A.1's ninth signal** (§ Deliverable 1, decision 18). A node that declines its cheap
    check does no work at its step and mints no ordinary prediction (folded: D15-5), so this is
    that folder's record for the tick: the check that ran, the value it read and the threshold it
    read it against. Without it a node's grades are computed only over the ticks it chose to act
    on, and a mis-tuned check that mutes a node is invisible to `SleepReport` and to the learner.

    **`source: firing` is what keeps it off the node's own key.** The trace's dedupe key is
    `(task, tick, node, tier, kind, source)` and `prediction_key()` takes a `:firing` suffix on
    the same condition, so homeostasis — whose full report is never skippable and whose think
    call is — can record both this and its own prediction in one tick and have both graded
    (folded: S-A62, folded: S-A75, folded: S-A83).

    **No `input_signature`.** A declining node projected a slice but ran no body, so there is no
    typed input model the tick digested for it; `synthetic_stuck()` is the same shape for the
    same reason.
    """
    return _record(
        task=task,
        tick=tick,
        node=decision.node,
        tier=None,
        signature=None,
        source=TraceSource.FIRING,
        prediction=FiringPrediction(
            check=decision.check,
            key=decision.key,
            value=decision.value,
            threshold=decision.threshold,
            fired=decision.fired,
        ),
    )


def firing_records(
    *, task: str, tick: int, decisions: Iterable[FiringDecision]
) -> list[TraceRecord]:
    """Every skip prediction a tick owes, read off `TickResult.firing` (folded: D15-6).

    That tuple carries **every** outer node's decision in `NODE_ORDER`, firing and declining
    alike, because a node that fired has no journal carrier for its decision. What is *recorded*
    is the skip — "a skip is a recorded prediction, not an absence" — so a fired decision mints
    nothing here: it already has its node's own ordinary prediction for the tick.
    """
    return [firing(task=task, tick=tick, decision=one) for one in decisions if not one.fired]


def synthetic_stuck(
    *, task: str, tick: int, goal_id: str, weights: Mapping[str, Any]
) -> TraceRecord:
    """The one `source: runtime` prediction: minted at a `stuck` raise so the operator's answer has a ref.

    § Deliverable 3's `stuck` row and decision 26: it is minted **only when no director-tier
    record exists for that tick**, which is the caller's check — the record itself carries
    `synthetic_stuck`, so the grader knows to leave it for the `operator_answer` outcome instead of
    scoring it at the window's close.
    """
    return _record(
        task=task,
        tick=tick,
        node=NodeName.CORTEX,
        tier=Tier.DIRECTOR,
        signature=None,
        source=TraceSource.RUNTIME,
        prediction=DirectorPrediction(
            goal_id=goal_id,
            progress_window_ticks=int(weights[WEIGHT_PROGRESS_WINDOW]),
            synthetic_stuck=True,
        ),
    )
