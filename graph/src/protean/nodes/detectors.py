"""The six trap detectors, as pure functions over one unit's committed observation window.

`the build specification (not in this mirror)` § Deliverable 4's trap table (Prather et al.'s eight traps,
six of which are measurable from what the loop already records) under Ruling 16 [B] and the operator's
over-firing constraint, verbatim: *"make sure this isn't over-firing, we don't want metaphorical
'over thinking' when we haven't actually reached a stuck state yet."*

**Every input is the projected `unit_windows` slice, and every threshold arrives on `weights`.**
No detector opens a trace file, and no number below is written in this module — the values live
in `brain/nodes/anterior_cingulate/weights.yaml` and reach the node on `MonitorInput`. That is
what makes decision 25 true and what makes retuning a detector an edit to a seed file rather
than to code.

**A signal is never a stop.** Each detector returns a `TrapScalar` carrying its value, the
threshold it was scored against and the weights key that supplied it, so the evidence body of a
`stuck` interrupt is rulable by the operator — and `fired` is computed as `value >= threshold` and
nowhere else, which is the invariant `TrapScalar`'s own validator enforces from the other side.

**Persistence, not a single tick** (Ruling 16 (b)). Five of the six detectors count consecutive
or windowed *observations*, and an observation is only appended for a unit that produced an
`ExecutorSummary` or was vetoed (folded: T-8) — so an intervening tick without an observation neither breaks
nor extends a streak.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from statistics import median
from types import MappingProxyType
from typing import Final, Mapping

from protean.state.enums import TRAP_WEIGHT_KEYS, TrapDetector
from protean.state.primitives import TrapScalar, UnitObservation

#: Which of a detector's weights keys is the one its value is **scored against**. Five of the
#: six detectors are scored against their first key; `misleading` is scored against its second
#: (`mislead_window` sizes the window, `mislead_rise` is the threshold). The positions are
#: recorded here rather than the key names, so `protean.state.enums.TRAP_WEIGHT_KEYS` stays the
#: single place any key is spelled.
_THRESHOLD_POSITION: Final[Mapping[TrapDetector, int]] = MappingProxyType(
    {
        TrapDetector.DISLODGING: 0,
        TrapDetector.FORMING: 0,
        TrapDetector.LOCATION: 0,
        TrapDetector.INTERRUPTION: 0,
        TrapDetector.MISLEADING: 1,
        TrapDetector.PROGRESSION: 0,
    }
)

#: Detector → the weights key its threshold is read from.
THRESHOLD_KEYS: Final[Mapping[TrapDetector, str]] = MappingProxyType(
    {
        detector: TRAP_WEIGHT_KEYS[detector][position]
        for detector, position in _THRESHOLD_POSITION.items()
    }
)


def _threshold(detector: TrapDetector, weights: Mapping[str, object]) -> float:
    """The threshold this detector is scored against. A missing key is a `KeyError`, not a
    default: a detector silently scored against zero would fire on every tick, which is the
    over-firing Ruling 16 (b) exists to prevent."""
    return float(weights[THRESHOLD_KEYS[detector]])  # type: ignore[arg-type]


def _weight(weights: Mapping[str, object], key: str) -> float:
    return float(weights[key])  # type: ignore[arg-type]


def _scalar(
    detector: TrapDetector, unit_id: str, value: float, threshold: float
) -> TrapScalar:
    return TrapScalar(
        detector=detector,
        value=value,
        threshold=threshold,
        weight_key=THRESHOLD_KEYS[detector],
        fired=value >= threshold,
        unit_id=unit_id,
    )


def _mismatched(row: UnitObservation) -> bool:
    """An observation is a mismatch when a predicate failed, or the tick was vetoed."""
    return bool(row.failed_predicate_ids) or row.vetoed


def dislodging(
    unit_id: str, window: Sequence[UnitObservation], weights: Mapping[str, object]
) -> TrapScalar:
    """Stuck in a rut: the same predicates failing while nothing moves.

    Value is the length of the trailing run of observations whose failed-predicate set is
    identical and non-empty and whose `change_bytes_total` stays under `rut_delta_max`.
    """
    delta_max = _weight(weights, TRAP_WEIGHT_KEYS[TrapDetector.DISLODGING][1])
    run = 0
    signature: frozenset[str] | None = None
    for row in reversed(window):
        failed = frozenset(row.failed_predicate_ids)
        if not failed or row.change_bytes_total >= delta_max:
            break
        if signature is None:
            signature = failed
        elif failed != signature:
            break
        run += 1
    return _scalar(
        TrapDetector.DISLODGING, unit_id, float(run), _threshold(TrapDetector.DISLODGING, weights)
    )


def forming(
    unit_id: str, window: Sequence[UnitObservation], weights: Mapping[str, object]
) -> TrapScalar:
    """Right problem, wrong approach: mismatch from the unit's first tick, nothing ever passing."""
    if not window or any(row.passed_predicate_ids for row in window):
        value = 0.0
    elif all(_mismatched(row) for row in window):
        value = float(len(window))
    else:
        value = 0.0
    return _scalar(
        TrapDetector.FORMING, unit_id, value, _threshold(TrapDetector.FORMING, weights)
    )


def location(
    unit_id: str, window: Sequence[UnitObservation], weights: Mapping[str, object]
) -> TrapScalar:
    """A crucial early step skipped, paid for as late structural rework.

    Value is the newest observation's change volume as a multiple of the median of the
    `rework_window` observations before it — a spike after a run of small-change ticks.
    """
    span = int(_weight(weights, TRAP_WEIGHT_KEYS[TrapDetector.LOCATION][1]))
    threshold = _threshold(TrapDetector.LOCATION, weights)
    if len(window) <= span:
        return _scalar(TrapDetector.LOCATION, unit_id, 0.0, threshold)
    prior = [float(row.change_bytes_total) for row in window[-(span + 1) : -1]]
    baseline = median(prior) if prior else 0.0
    latest = float(window[-1].change_bytes_total)
    value = latest / baseline if baseline > 0 else latest
    return _scalar(TrapDetector.LOCATION, unit_id, value, threshold)


def interruption(
    unit_id: str, window: Sequence[UnitObservation], weights: Mapping[str, object]
) -> TrapScalar:
    """The train of thought broken: abandonments inside a window with no verdict evaluated."""
    span = int(_weight(weights, TRAP_WEIGHT_KEYS[TrapDetector.INTERRUPTION][1]))
    recent = window[-span:] if span > 0 else []
    value = float(
        sum(
            1
            for row in recent
            if row.abandoned and not row.passed_predicate_ids and not row.failed_predicate_ids
        )
    )
    return _scalar(
        TrapDetector.INTERRUPTION, unit_id, value, _threshold(TrapDetector.INTERRUPTION, weights)
    )


def misleading(
    unit_id: str, window: Sequence[UnitObservation], weights: Mapping[str, object]
) -> TrapScalar:
    """Bad advice followed: the mismatch rate rising after a redirect marker.

    Value is the mismatch rate from the newest `redirect_by` marker onward minus the rate
    before it, both measured inside `mislead_window` observations. This is the detector whose
    own input is the director's prediction, which is why the marker lives on the observation.
    """
    span = int(_weight(weights, TRAP_WEIGHT_KEYS[TrapDetector.MISLEADING][0]))
    threshold = _threshold(TrapDetector.MISLEADING, weights)
    recent = list(window[-span:]) if span > 0 else []
    marker = next(
        (index for index in range(len(recent) - 1, -1, -1) if recent[index].redirect_by), None
    )
    if marker is None or marker == 0:
        return _scalar(TrapDetector.MISLEADING, unit_id, 0.0, threshold)
    before = recent[:marker]
    after = recent[marker:]
    rate_before = sum(1 for row in before if _mismatched(row)) / len(before)
    rate_after = sum(1 for row in after if _mismatched(row)) / len(after)
    return _scalar(TrapDetector.MISLEADING, unit_id, rate_after - rate_before, threshold)


def progression(
    unit_id: str, window: Sequence[UnitObservation], weights: Mapping[str, object]
) -> TrapScalar:
    """Output beyond what is understood: the seat citing material never admitted."""
    value = float(window[-1].uncited_ratio) if window else 0.0
    return _scalar(
        TrapDetector.PROGRESSION, unit_id, value, _threshold(TrapDetector.PROGRESSION, weights)
    )


#: The shape every detector shares: one unit, its window, the weights → one scalar.
Detector = Callable[[str, Sequence[UnitObservation], Mapping[str, object]], TrapScalar]

#: Detector → its function, in the table's order. The anterior cingulate iterates this map, so
#: adding a seventh detector is one entry here plus its weights key in the seed file.
DETECTORS: Final[Mapping[TrapDetector, Detector]] = MappingProxyType(
    {
        TrapDetector.DISLODGING: dislodging,
        TrapDetector.FORMING: forming,
        TrapDetector.LOCATION: location,
        TrapDetector.INTERRUPTION: interruption,
        TrapDetector.MISLEADING: misleading,
        TrapDetector.PROGRESSION: progression,
    }
)


def measure(
    unit_id: str, window: Sequence[UnitObservation], weights: Mapping[str, object]
) -> list[TrapScalar]:
    """All six scalars for one unit, in the table's order."""
    return [detect(unit_id, window, weights) for detect in DETECTORS.values()]
