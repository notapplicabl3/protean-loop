"""Outcome derivation — the runtime's job, mechanically, at the boundary.

`the build specification (not in this mirror)` § Deliverable 3 → *Outcomes are the runtime's job,
mechanically*: "No node grades itself and none reads a trace file. At each boundary the runtime
takes the previous tick's prediction records, reads the observable Deliverable 4's table names
for that node, and appends one `outcome` record with `source: runtime_grade` and `ref` set to
the prediction's key."

**Two grading schedules, both from the table.** Six rows are graded at the next boundary; the
manager's and the director's are graded "at the boundary where the horizon closes" and carry
`scored_at_tick` accordingly. This module finds both by scanning each folder's committed
predictions for ones no `outcome` has claimed yet, so a resume grades exactly what a clean run
would — the schedule is a property of the record on disk, not of a queue in memory.

**The observables come from state, never from a file.** The tick snapshots `state.latest` before
its first node runs; that snapshot *is* the previous tick's outputs, and the checkpoint carries
it across a resume. So a grader reads two `LatestOutputs` and the committed `unit_windows`, and
nothing else.

**Both citation grades compare in one id space** (`the build specification (not in this mirror)`
§ Deliverable 1, repair (a)). The hippocampus predicts bare episode ids and the thalamus mints —
and the seat cites — `admitted:<episode id>`, so before build 3 the hippocampus's intersection was
empty on every tick against the thalamus's `matched: true` on the same citations. The comparison
now runs over `_citation_key()` on both sides; each grade still *records* ids in its own node's
convention, so the thalamus's recorded `cited_admitted_ids` are byte-identical to build 2's.

**The synthetic `stuck` prediction is not graded here.** Its outcome is the operator's answer,
`source: operator_answer`, written by the resolution path — grading it mechanically would put a
verdict on the node that asked, which `OperatorAnswerOutcome` deliberately declines to do.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from protean import config
from protean.nodes.thalamus import admitted_id
from protean.state.brain_state import BrainState
from protean.state.enums import NodeName, TraceKind, TraceSource
from protean.state.primitives import UnitObservation
from protean.state.records import (
    BasalGangliaOutcome,
    DirectorOutcome,
    DispatchOutcome,
    FiringOutcome,
    HippocampusOutcome,
    HomeostasisOutcome,
    MonitorOutcome,
    ManagerOutcome,
    ThalamusOutcome,
    TraceRecord,
)
from protean.state.workspace import LatestOutputs

from protean.runtime.predictions import NO_SUBJECT


@dataclass(frozen=True, slots=True)
class TickCost:
    """What one tick actually spent — the observable homeostasis's forecast is graded on."""

    tokens: int = 0
    wall_seconds: float = 0.0


def _seat_citations(latest: LatestOutputs, tick: int) -> list[str]:
    """`cited_ids` from whichever addressee produced a result on that tick."""
    for result in (latest.dispatch, latest.manager, latest.director):
        if result is not None and result.tick == tick:
            return list(result.cited_ids)
    return []


#: The thalamus's own prefix, read off its minting function rather than restated as a literal —
#: one place mints `admitted:<episode id>` and one place undoes it.
_ADMITTED_PREFIX: Final[str] = admitted_id("")


def _citation_key(identifier: str) -> str:
    """An episode id under whichever convention cited it — the one space both grades compare in.

    Which side normalizes is a builder's default (§ Deliverable 1, repair (a)); this normalizes
    the seat's side down to the bare episode id, because that is the id the hippocampus predicts
    and the id an `AdmittedItem` carries beside its `admitted_id`.
    """
    if identifier.startswith(_ADMITTED_PREFIX):
        return identifier[len(_ADMITTED_PREFIX) :]
    return identifier


def _cited_from(payload_ids: Sequence[str], cited: Sequence[str]) -> list[str]:
    """The predicted ids the seat cited, compared under `_citation_key()` and reported as predicted.

    Reported in the *prediction's* convention rather than the seat's, so the thalamus keeps
    recording `admitted:`-prefixed ids exactly as build 2 did and only the hippocampus's records
    move — which is the whole of repair (a)'s blast radius.
    """
    keys = {_citation_key(one) for one in cited}
    return sorted({one for one in payload_ids if _citation_key(one) in keys})


def _work_arrived(latest: LatestOutputs, node: NodeName, tick: int) -> bool:
    """Whether anything for this node arrived in the tick it skipped (§ Deliverable 1).

    The observable behind the skip grade, and it is the **projection boundary's own stamp test**
    rather than a second mechanism: `projections._this_tick()` hands a slot to a consumer only
    when the slot's stamp is that tick, and `LatestOutputs` types one slot per node — so "anything
    for that node" is that node's own slot and "arrived in that tick" is its stamp. A node that
    declined ran no body and left its slot exactly as last tick left it, so nothing arrived and
    the decline was right.

    **Homeostasis is the one node this reads as `True` on a tick it declined**, because its body
    is contractual (`runtime.firing.CONTRACTUAL_BODIES`): only its think call is skippable, so
    its slot is stamped either way (ledger `D19-2`).
    """
    slot = getattr(latest, str(node), None)
    return slot is not None and slot.tick == tick


def _observation(state: BrainState, unit_id: str, tick: int) -> UnitObservation | None:
    for row in state.unit_windows.get(unit_id, []):
        if row.tick == tick:
            return row
    return None


def _outcome_record(
    prediction: TraceRecord, outcome, *, scored_at_tick: int,
    source: TraceSource = TraceSource.RUNTIME_GRADE,
) -> TraceRecord:
    return TraceRecord(
        schema_version=config.TRACE_SCHEMA_VERSION,
        task=prediction.task,
        tick=scored_at_tick,
        node=prediction.node,
        tier=prediction.tier,
        kind=TraceKind.OUTCOME,
        source=source,
        outcome=outcome,
        ref=prediction.prediction_key(),
        scored_at_tick=scored_at_tick,
    )


def _grade_next_boundary(
    prediction: TraceRecord,
    *,
    tick: int,
    state: BrainState,
    previous: LatestOutputs,
    current: LatestOutputs,
    cost: TickCost,
) -> TraceRecord | None:
    """The six rows the table grades at the boundary after the prediction's tick."""
    payload = prediction.prediction
    signal = getattr(payload, "signal", "")

    if signal == "homeostasis_cost":
        return _outcome_record(
            prediction,
            HomeostasisOutcome(
                observed_tokens=cost.tokens,
                observed_wall_seconds=cost.wall_seconds,
                matched=cost.tokens == payload.next_tick_tokens,
            ),
            scored_at_tick=tick,
        )

    if signal == "hippocampus_citation":
        cited = _seat_citations(previous, prediction.tick)
        hit = _cited_from(payload.episode_ids, cited)
        return _outcome_record(
            prediction,
            HippocampusOutcome(
                cited_episode_ids=hit,
                matched=bool(hit) if payload.episode_ids else not cited,
            ),
            scored_at_tick=tick,
        )

    if signal == "thalamus_citation":
        cited = _seat_citations(previous, prediction.tick)
        hit = _cited_from(payload.admitted_ids, cited)
        return _outcome_record(
            prediction,
            ThalamusOutcome(
                cited_admitted_ids=hit,
                matched=bool(hit) if payload.admitted_ids else not cited,
            ),
            scored_at_tick=tick,
        )

    if signal == "gate_unit_survives":
        if payload.unit_id == NO_SUBJECT:
            return _outcome_record(
                prediction,
                BasalGangliaOutcome(abandoned=False, trap_flagged=False, matched=True),
                scored_at_tick=tick,
            )
        row = _observation(state, payload.unit_id, prediction.tick)
        abandoned = bool(row.abandoned) if row is not None else False
        verdict = previous.anterior_cingulate
        flagged = bool(
            verdict is not None
            and any(scalar.fired and scalar.unit_id == payload.unit_id for scalar in verdict.traps)
        )
        return _outcome_record(
            prediction,
            BasalGangliaOutcome(
                abandoned=abandoned,
                trap_flagged=flagged,
                matched=not (abandoned or flagged),
            ),
            scored_at_tick=tick,
        )

    if signal == "monitor_next_verdict":
        verdict = current.anterior_cingulate
        if verdict is None or verdict.tick != tick:
            return None
        return _outcome_record(
            prediction,
            MonitorOutcome(
                observed_match=verdict.match,
                matched=verdict.match == payload.next_verdict_match,
            ),
            scored_at_tick=tick,
        )

    if signal == "firing_check":
        # **The skip grade, minted under its own outcome source** (§ Deliverable 1, contract 3's
        # fifth amendment). `_outcome_record()` sets `ref` from the prediction's own
        # `prediction_key()`, which carries the `:firing` suffix because the prediction's source
        # is `firing` — so the tick's two predictions are two separately gradeable keys rather
        # than one, and `append_trace()` finds the key committed (folded: S-A83, folded: S-A89).
        arrived = _work_arrived(previous, prediction.node, prediction.tick)
        return _outcome_record(
            prediction,
            FiringOutcome(work_arrived=arrived, matched=not arrived),
            scored_at_tick=tick,
            source=TraceSource.FIRING_GRADE,
        )

    if signal == "dispatch_expectations":
        verdict = previous.anterior_cingulate
        if verdict is None:
            return None
        return _outcome_record(
            prediction,
            DispatchOutcome(
                verdict_match=verdict.match,
                failed_predicate_ids=list(verdict.failed_predicate_ids),
                matched=verdict.match,
            ),
            scored_at_tick=tick,
        )

    return None


def _grade_horizon(
    prediction: TraceRecord, *, tick: int, state: BrainState
) -> TraceRecord | None:
    """The two rows graded where their window closes — the manager's and the director's."""
    payload = prediction.prediction
    signal = getattr(payload, "signal", "")

    if signal == "manager_horizon":
        if tick < prediction.tick + payload.horizon_ticks:
            return None
        window = state.unit_windows.get(payload.unit_id, [])
        passed = any(
            row.tick > prediction.tick
            and row.tick <= prediction.tick + payload.horizon_ticks
            and row.passed_predicate_ids
            and not row.failed_predicate_ids
            for row in window
        )
        return _outcome_record(
            prediction,
            ManagerOutcome(passed_within_horizon=passed, matched=passed),
            scored_at_tick=tick,
        )

    if signal == "director_progress":
        if payload.synthetic_stuck:
            return None
        if tick < prediction.tick + payload.progress_window_ticks:
            return None
        goal = next((item for item in state.goals if item.id == payload.goal_id), None)
        progressed = bool(goal is not None and goal.last_progress_tick > prediction.tick)
        return _outcome_record(
            prediction,
            DirectorOutcome(progress_observed=progressed, matched=progressed),
            scored_at_tick=tick,
        )

    return None


def derive(
    *,
    tick: int,
    state: BrainState,
    previous: LatestOutputs,
    current: LatestOutputs,
    cost: TickCost,
    committed: Mapping[str, Sequence[TraceRecord]],
    graded: Mapping[str, set[str]],
) -> list[TraceRecord]:
    """Every outcome this boundary can derive, in node-order then tick order.

    `committed` is folder name → its committed `prediction` records; `graded` is folder name →
    the `ref`s an outcome already claims there. Both come from `protean.brain.trace`, which is
    the runtime reading a trace file — decision 25 forbids that to a *node*, never to the
    runtime, which is the only writer of the file in the first place.
    """
    records: list[TraceRecord] = []
    for node in config.NODE_ORDER:
        for prediction in sorted(committed.get(node, ()), key=lambda item: item.tick):
            key = prediction.prediction_key()
            if key in graded.get(node, set()):
                continue
            if prediction.node is not NodeName(node):  # pragma: no cover - folder mismatch
                continue
            outcome = None
            if prediction.tick == tick - 1:
                outcome = _grade_next_boundary(
                    prediction,
                    tick=tick,
                    state=state,
                    previous=previous,
                    current=current,
                    cost=cost,
                )
            if outcome is None:
                outcome = _grade_horizon(prediction, tick=tick, state=state)
            if outcome is not None:
                records.append(outcome)
    return records
