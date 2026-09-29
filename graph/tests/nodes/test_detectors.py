"""The six trap detectors, as pure functions over one unit's committed observation window.

`the build specification (not in this mirror)` § Deliverable 4's trap table under Ruling 16 [B] and the operator's
over-firing constraint, verbatim: *"make sure this isn't over-firing, we don't want metaphorical
'over thinking' when we haven't actually reached a stuck state yet."*

Builder-verified row M11's detector half. Two properties are asserted for every detector:

* **every threshold comes from `brain/nodes/anterior_cingulate/weights.yaml`** — a missing key
  is a `KeyError`, never a silent zero, because a detector scored against zero fires on every
  tick, and every threshold the tests use is read out of the seed file;
* **`fired` is `value >= threshold` and nothing else**, which `TrapScalar`'s own validator
  enforces from the other side — so a detector that lied about firing is unconstructible.
"""

from __future__ import annotations

import pytest

from protean.nodes.detectors import DETECTORS, THRESHOLD_KEYS, measure
from protean.state.enums import TRAP_WEIGHT_KEYS, TrapDetector
from tests.nodes.conftest import UNIT_ID, observation

ALL = list(TrapDetector)


def _threshold(weights, detector: TrapDetector) -> float:
    return float(weights[THRESHOLD_KEYS[detector]])


# --------------------------------------------------------------------------------------
# The table itself
# --------------------------------------------------------------------------------------


def test_there_are_exactly_six_detectors_in_the_tables_order():
    assert list(DETECTORS) == ALL
    assert len(DETECTORS) == 6


def test_every_detector_is_scored_against_a_key_its_own_row_names():
    for detector, key in THRESHOLD_KEYS.items():
        assert key in TRAP_WEIGHT_KEYS[detector]


def test_every_weights_key_the_table_names_is_seeded(monitor_weights):
    """With `test_every_detector_is_scored_against_a_key_its_own_row_names` above, this absorbs
    `test_every_threshold_key_exists_in_the_seed_weights_file` (audit row N7): each threshold
    key is in its detector's table row, and every table key is seeded, so the removed test's
    claim is the two together.
    """
    for detector, keys in TRAP_WEIGHT_KEYS.items():
        for key in keys:
            assert key in monitor_weights, (detector, key)


@pytest.mark.parametrize("detector", ALL)
def test_a_missing_threshold_key_is_a_key_error_not_a_silent_zero(monitor_weights, detector):
    """A detector scored against zero would fire on every tick — Ruling 16 (b)'s failure."""
    for key in TRAP_WEIGHT_KEYS[detector]:
        weights = dict(monitor_weights)
        weights.pop(key)
        with pytest.raises(KeyError):
            DETECTORS[detector](UNIT_ID, [observation(1, failed=("e1",))], weights)


@pytest.mark.parametrize("detector", ALL)
def test_a_scalar_names_its_unit_its_key_and_its_threshold(monitor_weights, detector):
    """Every identity field of the scalar, and the empty window that fires nothing.

    Folded (audit row N3): `test_an_empty_window_fires_nothing` measured the same detector over
    the same empty window and asserted `fired` on the same object — both claims are kept here,
    the second as the last line. The operator's over-firing constraint keeps its own case at
    `test_one_mismatching_tick_fires_no_detector`, which is untouched.
    """
    scalar = DETECTORS[detector](UNIT_ID, [], monitor_weights)
    assert scalar.detector is detector
    assert scalar.unit_id == UNIT_ID
    assert scalar.weight_key == THRESHOLD_KEYS[detector]
    assert scalar.threshold == _threshold(monitor_weights, detector)
    assert scalar.fired == (scalar.value >= scalar.threshold)
    assert scalar.fired is False, "an empty window fires nothing"


def test_one_mismatching_tick_fires_no_detector(monitor_weights):
    """the operator's over-firing constraint: no detector can trip on a single tick under the seed."""
    window = [observation(1, failed=("e1",))]
    assert [scalar.detector for scalar in measure(UNIT_ID, window, monitor_weights) if scalar.fired] == []


def test_measure_returns_all_six_in_the_tables_order(monitor_weights):
    scalars = measure(UNIT_ID, [observation(1, failed=("e1",))], monitor_weights)
    assert [scalar.detector for scalar in scalars] == ALL


# --------------------------------------------------------------------------------------
# Dislodging — stuck in a rut
# --------------------------------------------------------------------------------------


def test_dislodging_counts_the_trailing_run_of_identical_failures(monitor_weights):
    ticks = int(monitor_weights[TRAP_WEIGHT_KEYS[TrapDetector.DISLODGING][0]])
    window = [observation(tick, failed=("e1",)) for tick in range(1, ticks + 1)]
    scalar = DETECTORS[TrapDetector.DISLODGING](UNIT_ID, window, monitor_weights)
    assert scalar.value == float(ticks)
    assert scalar.fired is True


def test_dislodging_stays_under_threshold_one_tick_short(monitor_weights):
    ticks = int(monitor_weights[TRAP_WEIGHT_KEYS[TrapDetector.DISLODGING][0]])
    window = [observation(tick, failed=("e1",)) for tick in range(1, ticks)]
    assert DETECTORS[TrapDetector.DISLODGING](UNIT_ID, window, monitor_weights).fired is False


def test_dislodging_breaks_when_the_failing_set_changes(monitor_weights):
    window = [
        observation(1, failed=("e1",)),
        observation(2, failed=("e1",)),
        observation(3, failed=("e2",)),
    ]
    assert DETECTORS[TrapDetector.DISLODGING](UNIT_ID, window, monitor_weights).value == 1.0


def test_dislodging_breaks_when_the_change_volume_moves(monitor_weights):
    """"Band-aids on a broken bone": a rut is failure *while nothing moves*."""
    delta_max = int(monitor_weights[TRAP_WEIGHT_KEYS[TrapDetector.DISLODGING][1]])
    window = [
        observation(1, failed=("e1",)),
        observation(2, failed=("e1",), change=delta_max),
        observation(3, failed=("e1",)),
    ]
    assert DETECTORS[TrapDetector.DISLODGING](UNIT_ID, window, monitor_weights).value == 1.0


def test_a_vetoed_tick_counts_as_a_failing_tick_with_zero_change(monitor_weights):
    ticks = int(monitor_weights[TRAP_WEIGHT_KEYS[TrapDetector.DISLODGING][0]])
    window = [observation(tick, failed=("e1",), vetoed=True) for tick in range(1, ticks + 1)]
    assert DETECTORS[TrapDetector.DISLODGING](UNIT_ID, window, monitor_weights).fired is True


def test_a_passing_tick_ends_the_rut(monitor_weights):
    window = [observation(1, failed=("e1",)), observation(2, passed=("e1",))]
    assert DETECTORS[TrapDetector.DISLODGING](UNIT_ID, window, monitor_weights).value == 0.0


# --------------------------------------------------------------------------------------
# Forming — right problem, wrong approach
# --------------------------------------------------------------------------------------


def test_forming_counts_a_window_that_never_passed_anything(monitor_weights):
    ticks = int(monitor_weights[TRAP_WEIGHT_KEYS[TrapDetector.FORMING][0]])
    window = [observation(tick, failed=("e1",)) for tick in range(1, ticks + 1)]
    scalar = DETECTORS[TrapDetector.FORMING](UNIT_ID, window, monitor_weights)
    assert scalar.value == float(ticks)
    assert scalar.fired is True


def test_forming_is_zero_once_any_predicate_has_ever_passed(monitor_weights):
    ticks = int(monitor_weights[TRAP_WEIGHT_KEYS[TrapDetector.FORMING][0]])
    window = [observation(1, passed=("e1",))] + [
        observation(tick, failed=("e1",)) for tick in range(2, ticks + 2)
    ]
    assert DETECTORS[TrapDetector.FORMING](UNIT_ID, window, monitor_weights).value == 0.0


def test_forming_needs_the_mismatch_from_the_units_first_tick(monitor_weights):
    """A window with a clean tick in it is not "from the unit's first tick"."""
    window = [observation(1), observation(2, failed=("e1",))]
    assert DETECTORS[TrapDetector.FORMING](UNIT_ID, window, monitor_weights).value == 0.0


# --------------------------------------------------------------------------------------
# Location — a crucial early step skipped, paid for as late structural rework
# --------------------------------------------------------------------------------------


def test_location_measures_the_spike_against_the_windows_median(monitor_weights):
    span = int(monitor_weights[TRAP_WEIGHT_KEYS[TrapDetector.LOCATION][1]])
    ratio = float(monitor_weights[TRAP_WEIGHT_KEYS[TrapDetector.LOCATION][0]])
    window = [observation(tick, change=10) for tick in range(1, span + 1)]
    window.append(observation(span + 1, change=int(10 * ratio)))
    scalar = DETECTORS[TrapDetector.LOCATION](UNIT_ID, window, monitor_weights)
    assert scalar.value == pytest.approx(ratio)
    assert scalar.fired is True


def test_location_is_silent_before_the_window_has_filled(monitor_weights):
    span = int(monitor_weights[TRAP_WEIGHT_KEYS[TrapDetector.LOCATION][1]])
    window = [observation(tick, change=10_000) for tick in range(1, span + 1)]
    assert DETECTORS[TrapDetector.LOCATION](UNIT_ID, window, monitor_weights).value == 0.0


def test_a_steady_change_volume_is_no_spike(monitor_weights):
    span = int(monitor_weights[TRAP_WEIGHT_KEYS[TrapDetector.LOCATION][1]])
    window = [observation(tick, change=10) for tick in range(1, span + 2)]
    assert DETECTORS[TrapDetector.LOCATION](UNIT_ID, window, monitor_weights).fired is False


# --------------------------------------------------------------------------------------
# Interruption — the train of thought broken
# --------------------------------------------------------------------------------------


def test_interruption_counts_abandonments_with_no_verdict_evaluated(monitor_weights):
    count = int(monitor_weights[TRAP_WEIGHT_KEYS[TrapDetector.INTERRUPTION][0]])
    window = [observation(tick, abandoned=True) for tick in range(1, count + 1)]
    scalar = DETECTORS[TrapDetector.INTERRUPTION](UNIT_ID, window, monitor_weights)
    assert scalar.value == float(count)
    assert scalar.fired is True


def test_an_abandonment_that_produced_a_verdict_does_not_count(monitor_weights):
    count = int(monitor_weights[TRAP_WEIGHT_KEYS[TrapDetector.INTERRUPTION][0]])
    window = [
        observation(tick, abandoned=True, failed=("e1",)) for tick in range(1, count + 1)
    ]
    assert DETECTORS[TrapDetector.INTERRUPTION](UNIT_ID, window, monitor_weights).value == 0.0


def test_interruption_only_looks_inside_its_own_window(monitor_weights):
    count = int(monitor_weights[TRAP_WEIGHT_KEYS[TrapDetector.INTERRUPTION][0]])
    span = int(monitor_weights[TRAP_WEIGHT_KEYS[TrapDetector.INTERRUPTION][1]])
    window = [observation(tick, abandoned=True) for tick in range(1, count + 1)]
    window += [observation(tick) for tick in range(count + 1, count + span + 1)]
    assert DETECTORS[TrapDetector.INTERRUPTION](UNIT_ID, window, monitor_weights).fired is False


# --------------------------------------------------------------------------------------
# Misleading — bad advice followed
# --------------------------------------------------------------------------------------


def test_misleading_measures_the_rise_across_the_redirect_marker(monitor_weights):
    window = [
        observation(1, passed=("e1",)),
        observation(2, passed=("e1",)),
        observation(3, failed=("e1",), redirect_by="director"),
        observation(4, failed=("e1",)),
    ]
    scalar = DETECTORS[TrapDetector.MISLEADING](UNIT_ID, window, monitor_weights)
    assert scalar.value == pytest.approx(1.0)
    assert scalar.fired is True


def test_no_redirect_marker_means_no_signal(monitor_weights):
    window = [observation(tick, failed=("e1",)) for tick in range(1, 5)]
    assert DETECTORS[TrapDetector.MISLEADING](UNIT_ID, window, monitor_weights).value == 0.0


def test_a_marker_on_the_first_observation_has_no_before_to_compare(monitor_weights):
    window = [
        observation(1, failed=("e1",), redirect_by="director"),
        observation(2, failed=("e1",)),
    ]
    assert DETECTORS[TrapDetector.MISLEADING](UNIT_ID, window, monitor_weights).value == 0.0


def test_advice_that_helped_is_a_fall_not_a_rise(monitor_weights):
    window = [
        observation(1, failed=("e1",)),
        observation(2, failed=("e1",)),
        observation(3, passed=("e1",), redirect_by="director"),
        observation(4, passed=("e1",)),
    ]
    scalar = DETECTORS[TrapDetector.MISLEADING](UNIT_ID, window, monitor_weights)
    assert scalar.value == pytest.approx(-1.0)
    assert scalar.fired is False


# --------------------------------------------------------------------------------------
# Progression — output beyond what is understood
# --------------------------------------------------------------------------------------


def test_progression_reads_the_newest_uncited_ratio(monitor_weights):
    threshold = _threshold(monitor_weights, TrapDetector.PROGRESSION)
    window = [observation(1, uncited=0.0), observation(2, uncited=threshold)]
    scalar = DETECTORS[TrapDetector.PROGRESSION](UNIT_ID, window, monitor_weights)
    assert scalar.value == pytest.approx(threshold)
    assert scalar.fired is True


def test_a_fully_cited_tick_does_not_fire_progression(monitor_weights):
    window = [observation(1, uncited=0.0)]
    assert DETECTORS[TrapDetector.PROGRESSION](UNIT_ID, window, monitor_weights).fired is False


def test_progression_forgets_an_older_spike(monitor_weights):
    """It is the newest observation's ratio: the signal is about this tick's output."""
    threshold = _threshold(monitor_weights, TrapDetector.PROGRESSION)
    window = [observation(1, uncited=threshold), observation(2, uncited=0.0)]
    assert DETECTORS[TrapDetector.PROGRESSION](UNIT_ID, window, monitor_weights).value == 0.0


# --------------------------------------------------------------------------------------
# Purity
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("detector", ALL)
def test_a_detector_neither_mutates_its_window_nor_its_weights(monitor_weights, detector):
    window = [observation(1, failed=("e1",), change=4), observation(2, passed=("e1",))]
    snapshot = [row.model_dump(mode="json") for row in window]
    weights = dict(monitor_weights)
    DETECTORS[detector](UNIT_ID, window, weights)
    assert [row.model_dump(mode="json") for row in window] == snapshot
    assert weights == monitor_weights
