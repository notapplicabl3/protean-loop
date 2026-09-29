"""The anterior cingulate — conflict monitoring. It grades the tick and it measures stuckness.

`the build specification (not in this mirror)` § Deliverable 2's `MonitorVerdict` row, § Deliverable 4's
trap table, decision 16 ("the monitor's build-1 comparator is the planner's declared
`expected`"), and `brain/nodes/anterior_cingulate/NODE.md`.

**The verdict is mechanical, never a judgment** (folded: S-7). It evaluates the unit's
`Expectation` predicates against the `ExecutorSummary` and reports match or mismatch with the
failed ids and the streak. It does not classify *why* — `ManagerPlan.mismatch_class` does, and
the manager is a judgment seat.

**A veto is an observation, not an absence.** When the gate inhibited the pending unit this tick,
every one of the unit's `expected` counts as failed and the change volume is zero — so the
vetoed tick is a *failing* tick for the detectors rather than a gap in the window.

**A predicate the summary cannot answer is ungradeable, not failed**
(`the build specification (not in this mirror)` § Deliverable 1, repair (b)). Run 1's planner emitted
`exit_code` predicates carrying no `code` argument, so `evaluate()`'s default arm compared the
reported code against `None`, failed by *absence*, and the executor was re-dispatched three ticks
on a predicate that could not pass. `ungradeable()` below is the presence-asking mirror of
`evaluate()` — one arm per arm, same order, same argument keys, so a fifth `ExpectationKind`
cannot be added to one without the other's default arm catching it — and the verdict withholds
exactly that default arm. It is a deliberate duplicate of `protean.runtime.report.ungradeable()`,
which a node may not import (`tests/nodes/test_purity.py`); the two are pinned to each other by
`tests/nodes/test_anterior_cingulate.py`.

**A dismissal resets a detector's window for a unit** (Ruling 16 (a)). `trap_dismissals` carries
`{unit_id: {detector: tick}}`, and a detector only sees observations after the tick its
dismissal landed on — which is what makes "the manager may dismiss it" a real reset instead of
a note nobody reads.

Every threshold arrives on `weights`; this module names no number.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final, Mapping

from protean.nodes.detectors import DETECTORS
from protean.nodes.vocabulary import (
    EXPECTATION_CODE,
    EXPECTATION_FIELD,
    EXPECTATION_PATH,
    EXPECTATION_VALUE,
)
from protean.state.calls import FiringDecision
from protean.state.enums import CallType, ExpectationKind, NodeName, TrapDetector
from protean.state.inputs import MonitorInput
from protean.state.outputs import MonitorVerdict
from protean.state.primitives import Expectation, TrapScalar, UnitObservation, WorkUnit
from protean.state.seats import ExecutorSummary


def _observation_for(summary: ExecutorSummary, path: str):
    for observation in summary.observations:
        if observation.path == path:
            return observation
    return None


def evaluate(expectation: Expectation, summary: ExecutorSummary) -> bool:
    """One deterministic predicate over an `ExecutorSummary`. Build 2's oracle emits the same
    type as a second source, which is why this is a function of the contract and not of a seat.
    """
    arguments: Mapping[str, Any] = expectation.arguments
    if expectation.kind is ExpectationKind.FILE_EXISTS:
        observation = _observation_for(summary, str(arguments.get(EXPECTATION_PATH, "")))
        return observation is not None and observation.exists
    if expectation.kind is ExpectationKind.FILE_ABSENT:
        observation = _observation_for(summary, str(arguments.get(EXPECTATION_PATH, "")))
        return observation is None or not observation.exists
    if expectation.kind is ExpectationKind.FILE_CONTAINS:
        read = summary.expectation_values.get(expectation.id)
        return isinstance(read, str) and str(arguments.get(EXPECTATION_VALUE, "")) in read
    if expectation.kind is ExpectationKind.SUMMARY_FIELD_EQUALS:
        field = str(arguments.get(EXPECTATION_FIELD, ""))
        payload = summary.model_dump(mode="json")
        return field in payload and payload[field] == arguments.get(EXPECTATION_VALUE)
    return summary.exit_code == arguments.get(EXPECTATION_CODE)


#: The four kinds `evaluate()` names an arm for. Everything else — `exit_code` today, a fifth
#: kind tomorrow — reaches its default arm, which is the arm repair (b) withholds.
ARMED_KINDS: Final[tuple[ExpectationKind, ...]] = (
    ExpectationKind.FILE_EXISTS,
    ExpectationKind.FILE_ABSENT,
    ExpectationKind.FILE_CONTAINS,
    ExpectationKind.SUMMARY_FIELD_EQUALS,
)


def ungradeable(expectation: Expectation, summary: ExecutorSummary) -> bool:
    """Whether this predicate's grade would come from missing evidence rather than from evidence.

    One arm per arm of `evaluate()`, asking *presence* where that function asks value, in the same
    order and reading the same argument keys. The duplicate of
    `protean.runtime.report.ungradeable()` is deliberate: that module is the writer and a node may
    not import it.
    """
    arguments: Mapping[str, Any] = expectation.arguments
    if expectation.kind in (ExpectationKind.FILE_EXISTS, ExpectationKind.FILE_ABSENT):
        path = str(arguments.get(EXPECTATION_PATH, ""))
        return not path or _observation_for(summary, path) is None
    if expectation.kind is ExpectationKind.FILE_CONTAINS:
        return EXPECTATION_VALUE not in arguments or not isinstance(
            summary.expectation_values.get(expectation.id), str
        )
    if expectation.kind is ExpectationKind.SUMMARY_FIELD_EQUALS:
        field = str(arguments.get(EXPECTATION_FIELD, ""))
        return not field or field not in summary.model_dump(mode="json")
    return EXPECTATION_CODE not in arguments


def withheld_from_verdict(expectation: Expectation, summary: ExecutorSummary) -> bool:
    """Repair (b): the predicates a verdict counts neither passed nor failed.

    Only `evaluate()`'s default arm — an `exit_code` predicate with no `code` argument, which
    would otherwise be compared against `None` and fail forever. § Deliverable 1 keeps *"every
    other predicate kind's verdict unchanged"*, so the four armed kinds still grade an absence as
    a failure exactly as build 1 wrote them.
    """
    return expectation.kind not in ARMED_KINDS and ungradeable(expectation, summary)


def _graded_unit(payload: MonitorInput) -> WorkUnit | None:
    """The unit this verdict is about: the vetoed one, else the summary's, else none."""
    wanted = payload.vetoed_unit_id or (
        payload.executor_summary.unit_id if payload.executor_summary is not None else None
    )
    if wanted is None:
        return None
    return next((unit for unit in payload.units if unit.id == wanted), None)


def mismatch_streak(window: Sequence[UnitObservation], this_tick_matched: bool) -> int:
    """Consecutive mismatching observations ending with this tick's verdict."""
    if this_tick_matched:
        return 0
    streak = 1
    for row in reversed(window):
        if row.failed_predicate_ids or row.vetoed:
            streak += 1
        else:
            break
    return streak


def _window_after_dismissal(
    window: Sequence[UnitObservation], dismissals: Mapping[str, int], detector: TrapDetector
) -> list[UnitObservation]:
    """The slice a detector may see: everything after the tick its dismissal landed on."""
    since = dismissals.get(str(detector))
    if since is None:
        return list(window)
    return [row for row in window if row.tick > since]


def traps_for(payload: MonitorInput) -> list[TrapScalar]:
    """Every unit's six scalars, each detector reading only past its own dismissal."""
    scalars: list[TrapScalar] = []
    for unit_id, window in sorted(payload.unit_windows.items()):
        dismissals = payload.trap_dismissals.get(unit_id, {})
        for detector, detect in DETECTORS.items():
            sliced = _window_after_dismissal(window, dismissals, detector)
            scalars.append(detect(unit_id, sliced, payload.weights))
    return scalars


#: This node's firing threshold and the check it names (§ Deliverable 1, seam contract C3).
WEIGHT_FIRING: Final[str] = "firing_threshold"
CHECK_LIVE_UNITS: Final[str] = "live_units"

#: This node's **think trigger** (`the build specification (not in this mirror)` § Deliverable 1, the anterior
#: cingulate rule): the call check below plans one think when the count of predicates graded
#: against a summary this tick is **>=** this key's value. **Off is `null` or the key absent**,
#: which is how the shipping seed carries it. The key is **static** — no sleep rule names it and
#: no learner moves it — and it sits in series behind `firing_threshold`, which reads a different
#: score (`live_units`), so both conditions must hold.
WEIGHT_THINK_TRIGGER: Final[str] = "think_threshold"


def live_units(payload: MonitorInput) -> float:
    """How many units there are to grade and to measure traps over. The cheap check's score."""
    return float(len(payload.units))


def firing_check(payload: MonitorInput) -> FiringDecision:
    """The cheap check, beside the body (§ Deliverable 1, seam contract C3).

    It **fires when the score is ≥ its threshold**, so **raising** `firing_threshold` makes the
    node skip more (folded: S-A91). The monitor's **defined empty input** is untouched by this:
    no summary this tick is no grade and an unchanged unit, which is the body's business and not
    the check's.
    """
    threshold = float(payload.weights.get(WEIGHT_FIRING, 0.0))
    value = live_units(payload)
    return FiringDecision(
        tick=payload.tick,
        node=NodeName.ANTERIOR_CINGULATE,
        check=CHECK_LIVE_UNITS,
        key=WEIGHT_FIRING,
        value=value,
        threshold=threshold,
        fired=value >= threshold,
    )


def graded_predicates(payload: MonitorInput) -> float:
    """How many of the graded unit's `expected` predicates `run()` grades against a summary.

    The call check's score: the set `run()` grades once `withheld_from_verdict` has removed repair
    (b)'s predicates, on the unit `_graded_unit` names. It is **zero** on a tick with no summary
    or a vetoed unit, because `run()` grades nothing against a claim there — which is why a
    positive trigger never plans a think on such a tick.
    """
    unit = _graded_unit(payload)
    summary = payload.executor_summary
    if unit is None or summary is None or payload.vetoed_unit_id == unit.id:
        return 0.0
    return float(len([e for e in unit.expected if not withheld_from_verdict(e, summary)]))


def call_check(payload: MonitorInput) -> tuple[CallType, ...]:
    """The call check, beside the cheap check (build A.2.i, § Deliverable 1).

    **It decides that this node thinks, and never makes the call.** The answer is the tuple of
    call types the node plans this tick — one `think` when its trigger key is on and
    `graded_predicates` is **>= that key's value**, the firing checks' own sense; nothing when the
    key is off (`null` or absent) or the count is below it. The runtime asks only when
    `firing_check` fired, and that check reads `live_units`, so the two gates read different
    scores and both must hold. Whether the key's value is a legal one is the policy's refusal at
    task start, never this function's.
    """
    trigger = payload.weights.get(WEIGHT_THINK_TRIGGER)
    if trigger is None:
        return ()
    return (CallType.THINK,) if graded_predicates(payload) >= float(trigger) else ()


def run(payload: MonitorInput) -> MonitorVerdict:
    """Grade the tick against the manager's declared `expected`, and post the six scalars."""
    unit = _graded_unit(payload)
    traps = traps_for(payload)

    if unit is None:
        return MonitorVerdict(tick=payload.tick, unit_id=None, match=True, traps=traps)

    window = payload.unit_windows.get(unit.id, [])

    if payload.vetoed_unit_id == unit.id or payload.executor_summary is None:
        failed = [expectation.id for expectation in unit.expected]
        return MonitorVerdict(
            tick=payload.tick,
            unit_id=unit.id,
            match=not failed,
            failed_predicate_ids=failed,
            passed_predicate_ids=[],
            streak=mismatch_streak(window, not failed),
            traps=traps,
        )

    summary = payload.executor_summary
    graded = [e for e in unit.expected if not withheld_from_verdict(e, summary)]
    passed = [e.id for e in graded if evaluate(e, summary)]
    failed = [e.id for e in graded if e.id not in passed]
    matched = not failed
    return MonitorVerdict(
        tick=payload.tick,
        unit_id=unit.id,
        match=matched,
        failed_predicate_ids=failed,
        passed_predicate_ids=passed,
        streak=mismatch_streak(window, matched),
        traps=traps,
    )
