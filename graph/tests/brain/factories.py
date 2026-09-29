"""One valid `TraceRecord` per node folder, and the outcome that grades it.

`the build specification (not in this mirror)` § Deliverable 4's observable table names one prediction
payload per row, and `TraceRecord`'s own validator makes `tier` the cortex folder's key and
only the cortex folder's — so "a record for folder X" is not a single shape and a battery that
parametrizes over the six folders needs the mapping written down once.

**These are the smallest records the contract accepts, not realistic ones.** The runtime mints
the realistic ones (`protean.runtime.predictions`); what the append path is entitled to be
tested on is the *contract*, so every payload here carries its required fields and nothing
more. Where a value is load-bearing to an assertion the test passes it in.
"""

from __future__ import annotations

from typing import Any

from protean import config
from protean.state.enums import CallType, NodeName, Tier, TraceKind, TraceSource
from protean.state.records import (
    BasalGangliaOutcome,
    BasalGangliaPrediction,
    DirectorOutcome,
    DirectorPrediction,
    DispatchOutcome,
    DispatchPrediction,
    HippocampusOutcome,
    HippocampusPrediction,
    HomeostasisOutcome,
    HomeostasisPrediction,
    MonitorOutcome,
    MonitorPrediction,
    ManagerOutcome,
    ManagerPrediction,
    ThalamusOutcome,
    ThalamusPrediction,
    TraceRecord,
)

#: Folder → every `(folder, addressee)` key its `trace.jsonl` carries. Five folders have exactly
#: one key and no addressee; the cortex folder has three (§ Deliverable 4), re-based by build A.1
#: to **two seats plus the `dispatch` addressee** — `TraceRecord.tier` is the addressee now, so a
#: dispatch record has a legal place to sit under the cortex folder.
FOLDER_TIERS: dict[str, tuple[Tier | None, ...]] = {
    "homeostasis": (None,),
    "hippocampus": (None,),
    "thalamus": (None,),
    "basal_ganglia": (None,),
    "cortex": (Tier.DIRECTOR, Tier.MANAGER, CallType.DISPATCH),
    "anterior_cingulate": (None,),
}

#: The default tier a six-folder parametrization uses for the cortex. Any of the three would
#: do; the director's is the one the `stuck` ladder also lands on, so it is the busiest.
DEFAULT_TIER: dict[str, Tier | None] = {
    node: tiers[0] for node, tiers in FOLDER_TIERS.items()
}


def prediction_payload(node: str, tier: Tier | None = None):
    """The prediction payload § Deliverable 4's table names for this `(folder, tier)`."""
    name = NodeName(node)
    if name is NodeName.HOMEOSTASIS:
        return HomeostasisPrediction(next_tick_tokens=7, next_tick_wall_seconds=0.5)
    if name is NodeName.HIPPOCAMPUS:
        return HippocampusPrediction(episode_ids=["task-f:1"])
    if name is NodeName.THALAMUS:
        return ThalamusPrediction(admitted_ids=["admitted:task-f:1"])
    if name is NodeName.BASAL_GANGLIA:
        return BasalGangliaPrediction(unit_id="u1")
    if name is NodeName.ANTERIOR_CINGULATE:
        return MonitorPrediction(next_verdict_match=True)
    if tier is CallType.DISPATCH:
        return DispatchPrediction(unit_id="u1", expectation_ids=["e1"])
    if tier is Tier.MANAGER:
        return ManagerPrediction(unit_id="u1", horizon_ticks=4)
    return DirectorPrediction(goal_id="g1", progress_window_ticks=8)


def outcome_payload(node: str, tier: Tier | None = None):
    """The outcome payload that grades the same row."""
    name = NodeName(node)
    if name is NodeName.HOMEOSTASIS:
        return HomeostasisOutcome(observed_tokens=7, observed_wall_seconds=0.5, matched=True)
    if name is NodeName.HIPPOCAMPUS:
        return HippocampusOutcome(cited_episode_ids=["task-f:1"], matched=True)
    if name is NodeName.THALAMUS:
        return ThalamusOutcome(cited_admitted_ids=["admitted:task-f:1"], matched=True)
    if name is NodeName.BASAL_GANGLIA:
        return BasalGangliaOutcome(abandoned=False, trap_flagged=False, matched=True)
    if name is NodeName.ANTERIOR_CINGULATE:
        return MonitorOutcome(observed_match=True, matched=True)
    if tier is CallType.DISPATCH:
        return DispatchOutcome(verdict_match=True, matched=True)
    if tier is Tier.MANAGER:
        return ManagerOutcome(passed_within_horizon=True, matched=True)
    return DirectorOutcome(progress_observed=True, matched=True)


def prediction(
    node: str,
    tier: Tier | None = None,
    *,
    task: str = "task-f",
    tick: int = 1,
    source: TraceSource = TraceSource.NODE,
) -> TraceRecord:
    """A valid `prediction`-kind record for one `(folder, tier)`."""
    return TraceRecord(
        schema_version=config.TRACE_SCHEMA_VERSION,
        task=task,
        tick=tick,
        node=NodeName(node),
        tier=tier,
        kind=TraceKind.PREDICTION,
        source=source,
        prediction=prediction_payload(node, tier),
    )


def outcome(
    ref: str,
    node: str,
    tier: Tier | None = None,
    *,
    task: str = "task-f",
    tick: int = 2,
    source: TraceSource = TraceSource.RUNTIME_GRADE,
) -> TraceRecord:
    """A valid `outcome`-kind record whose `ref` is whatever the caller hands it."""
    return TraceRecord(
        schema_version=config.TRACE_SCHEMA_VERSION,
        task=task,
        tick=tick,
        node=NodeName(node),
        tier=tier,
        kind=TraceKind.OUTCOME,
        source=source,
        outcome=outcome_payload(node, tier),
        ref=ref,
        scored_at_tick=tick,
    )


def without_prediction(record: TraceRecord) -> dict[str, Any]:
    """The wire payload of a `prediction` record with its `prediction` stripped.

    The model refuses to *construct* one — which is why the append path takes a raw mapping:
    the enforcement point has to be the writer, or a caller that hand-built a malformed line
    would still get it onto disk.
    """
    payload = record.model_dump(mode="json")
    payload.pop("prediction", None)
    return payload


def unknown_ref(task: str = "task-f", tick: int = 99, node: str = "homeostasis") -> str:
    """A `ref` in the right shape naming a prediction no folder has committed."""
    tier = DEFAULT_TIER[node]
    return f"{task}:{tick}:{node}:{tier if tier is not None else '-'}:prediction"


assert tuple(FOLDER_TIERS) == config.NODE_ORDER, (
    "the folder table is keyed by config.NODE_ORDER — the six node folders, in the tick order"
)
