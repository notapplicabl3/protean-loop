"""Row G15's learner half: the ninth signal, its four rows, and the arm they take.

`the build specification (not in this mirror)` § Deliverable 1, "**And the signal that carries it**",
"**The arm that row takes**" and "**Which arm a step takes**"; § Directional decisions 18;
§ Out of scope, the `protean sleep` bullet and its named narrowings; row B29.

**Zero model calls, and no file under `brain/` is written.** The one `weights.yaml` `decide()`
re-values here is written into `tmp_path`.

**What this module asserts is a closure, not a feature.** A.1 touches build 3's closed
admissible list by **one added entry and two renames** and adds **no class** to `KeyRule`'s arm
table — so the tests below pin the lengths and the members as literals, and the arithmetic
(k = 3, k = 6, ±1, 10 %, the two-task rule, the persistence floor) is asserted unchanged rather
than re-derived.

**The confirmations assertion is instrumented, not inferred.** `detector_fires()` is replaced
with a function that raises; a `firing_check` row must still reach an applied move, and a
detector row under the same patch must still raise — otherwise the instrument would prove
nothing about the firing row.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from protean import config
from protean.sleep import weights as weights_module
from protean.sleep.weights import (
    DONE_TERMINAL,
    INTEGER_STEP,
    LOOSEN_DOWN,
    LOOSEN_UP,
    RATIO_STEP_FRACTION,
    REQUIRED_PAIRS_LOOSEN,
    REQUIRED_PAIRS_TIGHTEN,
    REQUIRED_TASKS,
    SIGNAL_KEY_MAP,
    EvidenceWindow,
    KeyRule,
    WeightsFile,
    WindowPair,
    WindowRuns,
    bounded_step,
    breaches_persistence_floor,
    clears_the_floor,
    decide,
)
from protean.state.enums import TrapDetector

#: § Deliverable 1's nine, in order — two renamed and one added. Compared literally.
NINE_SIGNALS = (
    "homeostasis_cost",
    "hippocampus_citation",
    "thalamus_citation",
    "gate_unit_survives",
    "monitor_next_verdict",
    "dispatch_expectations",
    "manager_horizon",
    "director_progress",
    "firing_check",
)

#: Build 3's four, closed — A.1's narrowings do not reach them.
FOUR_REASONS = ("unjoined", "off-list", "ungradeable", "vacuous")

#: The four firing-key-bearing nodes. `basal_ganglia` is the stated exemption (folded: S-A17):
#: it is outside `WEIGHTS_WRITABLE_NODES`, its `weights.yaml` is contractually empty and its
#: cheap check is structural, reading no threshold key at all.
FIRING_NODES = ("homeostasis", "hippocampus", "thalamus", "anterior_cingulate")

FIRING_ROWS = tuple(rule for rule in SIGNAL_KEY_MAP if rule.signal == "firing_check")


def _firing_rule(node: str = "hippocampus") -> KeyRule:
    return next(rule for rule in FIRING_ROWS if rule.node == node)


def _detector_rule() -> KeyRule:
    return next(rule for rule in SIGNAL_KEY_MAP if rule.detector is not None)


def _window(rule: KeyRule, *, pairs: int, tasks: int, matched: bool = True) -> EvidenceWindow:
    """`pairs` pairs spread over `tasks` tasks, all matched — a loosening window."""
    return EvidenceWindow(
        rule=rule,
        pairs=tuple(
            WindowPair(
                ref=f"t{index % tasks}:{index}:{rule.node}:-:prediction:firing",
                task=f"t{index % tasks}",
                project="",
                matched=matched,
            )
            for index in range(pairs)
        ),
        projects=(),
    )


def _weights_file(tmp_path: Path, *, key: str, value: str) -> WeightsFile:
    path = tmp_path / "weights.yaml"
    path.write_text(f"{key}: {value}\n", encoding="utf-8")
    return WeightsFile(path)


def _runs(tasks: int = 2, *, terminal: str = DONE_TERMINAL) -> WindowRuns:
    return WindowRuns(
        journals={f"t{index}": () for index in range(tasks)},
        terminals={f"t{index}": terminal for index in range(tasks)},
    )


# --------------------------------------------------------------------------------------
# The two closed literal tables
# --------------------------------------------------------------------------------------


def test_the_admissible_list_is_exactly_nine_names() -> None:
    """One added and two renamed — never a tenth (§ Out of scope, the `protean sleep` bullet).

    Re-based by build A.1 (§ Deliverable 1, decision 18): **nine** names, not eight — two
    renamed with the tiers that minted them, and one added, `firing_check`, without which a
    skip prediction would be unreachable by the learner, because build 3's list is closed.
    Absorbs `tests/sleep/test_evidence.py::test_the_signal_list_is_the_config_literal_and_excludes_operator_answer`
    (row S8): the literal equality below implies `len == 9`, `"firing_check" in` and
    `"operator_answer" not in`. The behavioural `operator_answer` claim stays in `test_evidence.py`.
    """
    assert config.ADMISSIBLE_SIGNALS == NINE_SIGNALS
    assert len(config.ADMISSIBLE_SIGNALS) == 9
    assert "planner_horizon" not in config.ADMISSIBLE_SIGNALS
    assert "executor_expectations" not in config.ADMISSIBLE_SIGNALS


def test_the_exclusion_reasons_are_still_the_four_build_three_closed() -> None:
    assert config.SLEEP_EXCLUSION_REASONS == FOUR_REASONS
    assert len(config.SLEEP_EXCLUSION_REASONS) == 4


# --------------------------------------------------------------------------------------
# The four rows — one per firing-key-bearing node, and none for the gate
# --------------------------------------------------------------------------------------


def test_the_map_holds_exactly_four_firing_rows_one_per_node_and_none_for_the_gate() -> None:
    assert len(FIRING_ROWS) == 4
    assert tuple(rule.node for rule in FIRING_ROWS) == FIRING_NODES
    assert "basal_ganglia" not in {rule.node for rule in FIRING_ROWS}
    assert {rule.key for rule in FIRING_ROWS} == {"firing_threshold"}


def test_every_firing_row_is_an_ordinary_non_detector_row_carrying_loosen_up() -> None:
    """The comparison sense decides the arm: `>=` fires, so raising the threshold loosens."""
    for rule in FIRING_ROWS:
        assert rule.detector is None
        assert rule.is_detector is False
        assert rule.polarity == LOOSEN_UP
    assert LOOSEN_DOWN not in {rule.polarity for rule in FIRING_ROWS}


def test_the_re_keyed_cortex_rows_are_present_and_no_row_names_planner_horizon() -> None:
    cortex = [rule for rule in SIGNAL_KEY_MAP if rule.signal == "manager_horizon"]
    assert {(rule.node, rule.key) for rule in cortex} == {
        ("cortex", "k_replan"),
        ("cortex", "manager_horizon"),
    }
    for rule in SIGNAL_KEY_MAP:
        assert rule.key != "planner_horizon"
        assert rule.signal != "planner_horizon"


def test_key_rule_gains_no_class_and_trap_detector_does_not_move() -> None:
    """The two properties that would otherwise have motivated a third arm (folded: S-A64)."""
    assert tuple(KeyRule.__dataclass_fields__) == (
        "node",
        "key",
        "signal",
        "polarity",
        "detector",
    )
    assert tuple(member.value for member in TrapDetector) == (
        "dislodging",
        "forming",
        "location",
        "interruption",
        "misleading",
        "progression",
    )
    assert {rule.detector for rule in SIGNAL_KEY_MAP if rule.detector is not None} == set(
        TrapDetector
    )


def test_the_detector_rows_are_untouched_beside_the_new_ones() -> None:
    """`_detector_rules()` still generates every detector row, all `LOOSEN_DOWN`."""
    detector_rows = [rule for rule in SIGNAL_KEY_MAP if rule.detector is not None]
    assert detector_rows
    for rule in detector_rows:
        assert rule.polarity == LOOSEN_DOWN
        assert rule.signal == "monitor_next_verdict"
        assert rule.node == "anterior_cingulate"


# --------------------------------------------------------------------------------------
# The arm — the direction proven, not asserted
# --------------------------------------------------------------------------------------


def test_the_arithmetic_is_the_one_build_three_closed() -> None:
    assert (REQUIRED_PAIRS_TIGHTEN, REQUIRED_PAIRS_LOOSEN, REQUIRED_TASKS) == (3, 6, 2)
    assert (INTEGER_STEP, RATIO_STEP_FRACTION) == (1, 0.1)


def test_bounded_step_moves_a_firing_threshold_up_on_a_loosening_step() -> None:
    """Raising it makes the node skip more, which is why raising it takes the strict arm."""
    rule = _firing_rule()
    assert bounded_step(0.5, rule.polarity, True) == 0.55
    assert bounded_step(0.5, rule.polarity, True) > 0.5
    assert bounded_step(0.5, rule.polarity, False) == 0.45
    # Under `LOOSEN_DOWN` the skip-more direction would fall on the k = 3 tightening arm.
    assert bounded_step(0.5, LOOSEN_DOWN, True) < 0.5


def test_the_loosening_arm_is_k_six_every_task_done_and_the_floor() -> None:
    assert clears_the_floor(pairs=6, tasks=2, loosening=True, every_task_done=True) is True
    assert clears_the_floor(pairs=5, tasks=2, loosening=True, every_task_done=True) is False
    assert clears_the_floor(pairs=6, tasks=1, loosening=True, every_task_done=True) is False
    assert clears_the_floor(pairs=6, tasks=2, loosening=True, every_task_done=False) is False
    # The tightening arm is k = 3 and is unmoved by this build.
    assert clears_the_floor(pairs=3, tasks=2, loosening=False) is True
    # A firing threshold is not one of the floored window-length keys.
    assert breaches_persistence_floor("firing_threshold", 0.0) is False


def test_a_firing_rows_loosening_step_applies_without_any_confirmations_count_being_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row G15's instrumented clause: the non-detector arm reads no detector's fires."""

    def _refuse(*args, **kwargs):  # pragma: no cover - the instrument, never reached
        raise AssertionError("a firing key read a confirmations count")

    monkeypatch.setattr(weights_module, "detector_fires", _refuse)

    rule = _firing_rule()
    weights = _weights_file(tmp_path, key=rule.key, value="0.5")
    update = decide(
        _window(rule, pairs=REQUIRED_PAIRS_LOOSEN, tasks=REQUIRED_TASKS),
        weights=weights,
        runs=_runs(),
        dismissals=Counter(),
        seed_hashes={rule.weights_key(): "seed-hash"},
        seeded=frozenset(),
    )
    assert update.applied is True
    assert update.withheld_reason == ""
    assert update.direction == "loosen"
    assert (update.from_value, update.to_value) == (0.5, 0.55)
    assert update.evidence.required_pairs == REQUIRED_PAIRS_LOOSEN
    assert update.evidence.confirmations == 0
    assert update.evidence.every_task_done is True
    assert update.evidence.floor_minimum is None
    assert weights.value_of(rule.key) == 0.5  # the parsed original; the text is what moved
    assert "0.55" in weights.text


def test_the_instrument_fires_on_a_detector_row_under_the_same_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control: without this, the test above would prove nothing about the firing row."""

    def _refuse(*args, **kwargs):
        raise AssertionError("a firing key read a confirmations count")

    monkeypatch.setattr(weights_module, "detector_fires", _refuse)

    rule = _detector_rule()
    with pytest.raises(AssertionError):
        decide(
            _window(rule, pairs=REQUIRED_PAIRS_LOOSEN, tasks=REQUIRED_TASKS),
            weights=_weights_file(tmp_path, key=rule.key, value="0.5"),
            runs=_runs(),
            dismissals=Counter(),
            seed_hashes={rule.weights_key(): "seed-hash"},
            seeded=frozenset(),
        )


def test_a_short_window_withholds_the_firing_move_on_the_strict_arm(tmp_path: Path) -> None:
    """Five pairs is one short of k = 6, so the loosening step does not land."""
    rule = _firing_rule()
    update = decide(
        _window(rule, pairs=REQUIRED_PAIRS_LOOSEN - 1, tasks=REQUIRED_TASKS),
        weights=_weights_file(tmp_path, key=rule.key, value="0.5"),
        runs=_runs(),
        dismissals=Counter(),
        seed_hashes={rule.weights_key(): "seed-hash"},
        seeded=frozenset(),
    )
    assert update.applied is False
    assert "6" in update.withheld_reason


def test_a_task_that_did_not_end_done_withholds_the_firing_move(tmp_path: Path) -> None:
    """The second half of the non-detector loosening arm, reached by a firing row."""
    rule = _firing_rule()
    update = decide(
        _window(rule, pairs=REQUIRED_PAIRS_LOOSEN, tasks=REQUIRED_TASKS),
        weights=_weights_file(tmp_path, key=rule.key, value="0.5"),
        runs=_runs(terminal="stopped"),
        dismissals=Counter(),
        seed_hashes={rule.weights_key(): "seed-hash"},
        seeded=frozenset(),
    )
    assert update.applied is False
    assert update.evidence.every_task_done is False
