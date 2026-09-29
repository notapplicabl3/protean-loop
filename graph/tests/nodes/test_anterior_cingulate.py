"""The anterior cingulate — conflict monitoring. It grades the tick and it measures stuckness.

`the build specification (not in this mirror)` § Deliverable 2's `MonitorVerdict` row, § Deliverable 4's trap
table, decision 16 ("the monitor's build-1 comparator is the planner's declared `expected`") and
`brain/nodes/anterior_cingulate/NODE.md`.

**The verdict is mechanical, never a judgment** (folded: S-7): the node evaluates predicates and
reports match or mismatch. It does not classify *why* — `ManagerPlan.mismatch_class` does, and
the planner is a judgment seat. **A veto is an observation, not an absence**, and **a dismissal
resets a detector's window** (Ruling 16 (a)).

The last section is build 3's repair (b) (`the build specification (not in this mirror)` § Deliverable 1): an
`exit_code` predicate carrying no `code` argument is ungradeable and is counted neither passed nor
failed, every other predicate kind's verdict is unchanged, and the node's `ungradeable()` is
pinned to `protean.runtime.report.ungradeable()`, which it deliberately duplicates because a node
may not import the writer (`tests/nodes/test_purity.py`).
"""

from __future__ import annotations

import pytest

from protean.nodes.anterior_cingulate import (
    ARMED_KINDS,
    evaluate,
    mismatch_streak,
    run,
    traps_for,
    ungradeable,
    withheld_from_verdict,
)
from protean.runtime.report import ungradeable as report_ungradeable
from protean.nodes.vocabulary import (
    EXPECTATION_CODE,
    EXPECTATION_FIELD,
    EXPECTATION_PATH,
    EXPECTATION_VALUE,
)
from protean.state.enums import TRAP_WEIGHT_KEYS, ExpectationKind, TrapDetector
from protean.state.inputs import MonitorInput
from protean.state.outputs import MonitorVerdict
from protean.state.primitives import Expectation, WorkUnit, WorkspaceObservation
from protean.state.seats import ExecutorSummary
from tests.nodes.conftest import GOAL_ID, TASK_ID, UNIT_ID, observation, unit


def _summary(**overrides) -> ExecutorSummary:
    payload = dict(tick=1, unit_id=UNIT_ID, narrative="did it")
    payload.update(overrides)
    return ExecutorSummary(**payload)


def _input(
    weights,
    *,
    units=(),
    windows=None,
    dismissals=None,
    summary=None,
    vetoed=None,
    tick=1,
):
    return MonitorInput(
        task_id=TASK_ID,
        tick=tick,
        weights=dict(weights),
        units=list(units),
        unit_windows=windows or {},
        trap_dismissals=dismissals or {},
        executor_summary=summary,
        vetoed_unit_id=vetoed,
    )


# --------------------------------------------------------------------------------------
# `evaluate` — one deterministic predicate over an `ExecutorSummary`
# --------------------------------------------------------------------------------------


def test_file_exists_reads_the_observation_for_that_path():
    expectation = Expectation(
        id="e1", kind=ExpectationKind.FILE_EXISTS, arguments={EXPECTATION_PATH: "out.txt"}
    )
    present = _summary(
        observations=[
            WorkspaceObservation(path="out.txt", exists=True, size_bytes=1, content_hash="h")
        ]
    )
    missing = _summary(
        observations=[
            WorkspaceObservation(path="out.txt", exists=False, size_bytes=0, content_hash="h")
        ]
    )
    assert evaluate(expectation, present) is True
    assert evaluate(expectation, missing) is False
    assert evaluate(expectation, _summary()) is False, "no observation is not an existence claim"


def test_file_absent_is_the_mirror():
    expectation = Expectation(
        id="e1", kind=ExpectationKind.FILE_ABSENT, arguments={EXPECTATION_PATH: "out.txt"}
    )
    assert evaluate(expectation, _summary()) is True
    assert (
        evaluate(
            expectation,
            _summary(
                observations=[
                    WorkspaceObservation(
                        path="out.txt", exists=True, size_bytes=1, content_hash="h"
                    )
                ]
            ),
        )
        is False
    )


def test_file_contains_reads_what_the_executor_reported_reading():
    expectation = Expectation(
        id="e1",
        kind=ExpectationKind.FILE_CONTAINS,
        arguments={EXPECTATION_PATH: "out.txt", EXPECTATION_VALUE: "needle"},
    )
    assert evaluate(expectation, _summary(expectation_values={"e1": "a needle here"})) is True
    assert evaluate(expectation, _summary(expectation_values={"e1": "nothing"})) is False
    assert evaluate(expectation, _summary()) is False


def test_summary_field_equals_compares_a_named_field():
    expectation = Expectation(
        id="e1",
        kind=ExpectationKind.SUMMARY_FIELD_EQUALS,
        arguments={EXPECTATION_FIELD: "narrative", EXPECTATION_VALUE: "did it"},
    )
    assert evaluate(expectation, _summary()) is True
    assert evaluate(expectation, _summary(narrative="did something else")) is False


def test_an_unknown_summary_field_is_a_failure_not_an_error():
    expectation = Expectation(
        id="e1",
        kind=ExpectationKind.SUMMARY_FIELD_EQUALS,
        arguments={EXPECTATION_FIELD: "no_such_field", EXPECTATION_VALUE: 1},
    )
    assert evaluate(expectation, _summary()) is False


def test_exit_code_compares_the_reported_code():
    expectation = Expectation(
        id="e1", kind=ExpectationKind.EXIT_CODE, arguments={EXPECTATION_CODE: 0}
    )
    assert evaluate(expectation, _summary(exit_code=0)) is True
    assert evaluate(expectation, _summary(exit_code=1)) is False


# --------------------------------------------------------------------------------------
# The verdict
# --------------------------------------------------------------------------------------


def test_no_graded_unit_is_a_match_with_no_predicates(monitor_weights):
    verdict = run(_input(monitor_weights))
    assert isinstance(verdict, MonitorVerdict)
    assert verdict.emitter == "anterior_cingulate"
    assert verdict.unit_id is None
    assert verdict.match is True
    assert verdict.failed_predicate_ids == []


def test_a_satisfied_predicate_matches(monitor_weights):
    work = unit()
    summary = _summary(
        observations=[
            WorkspaceObservation(path="out.txt", exists=True, size_bytes=1, content_hash="h")
        ]
    )
    verdict = run(_input(monitor_weights, units=[work], summary=summary))
    assert verdict.unit_id == UNIT_ID
    assert verdict.match is True
    assert verdict.passed_predicate_ids == ["e1"]
    assert verdict.failed_predicate_ids == []
    assert verdict.streak == 0


def test_an_unsatisfied_predicate_mismatches_and_names_it(monitor_weights):
    work = unit()
    verdict = run(_input(monitor_weights, units=[work], summary=_summary()))
    assert verdict.match is False
    assert verdict.failed_predicate_ids == ["e1"]
    assert verdict.passed_predicate_ids == []
    assert verdict.streak == 1


def test_a_partial_pass_is_a_mismatch(monitor_weights):
    work = unit(paths=("a.txt", "b.txt"))
    summary = _summary(
        observations=[
            WorkspaceObservation(path="a.txt", exists=True, size_bytes=1, content_hash="h")
        ]
    )
    verdict = run(_input(monitor_weights, units=[work], summary=summary))
    assert verdict.match is False
    assert verdict.passed_predicate_ids == ["e1"]
    assert verdict.failed_predicate_ids == ["e2"]


def test_it_does_not_classify_why(monitor_weights):
    """`MonitorVerdict` carries no mismatch class — the planner is the judgment seat."""
    verdict = run(_input(monitor_weights, units=[unit()], summary=_summary()))
    assert not hasattr(verdict, "mismatch_class")


# --------------------------------------------------------------------------------------
# A veto is an observation, not an absence
# --------------------------------------------------------------------------------------


def test_a_vetoed_tick_fails_every_expected_predicate(monitor_weights):
    work = unit(paths=("a.txt", "b.txt"))
    verdict = run(_input(monitor_weights, units=[work], vetoed=UNIT_ID))
    assert verdict.unit_id == UNIT_ID
    assert verdict.match is False
    assert verdict.failed_predicate_ids == ["e1", "e2"]
    assert verdict.passed_predicate_ids == []


def test_a_unit_with_no_summary_and_no_veto_is_still_graded_as_a_mismatch(monitor_weights):
    """The graded unit is the vetoed one, else the summary's — neither means nothing to grade."""
    verdict = run(_input(monitor_weights, units=[unit()]))
    assert verdict.unit_id is None
    assert verdict.match is True


def test_a_veto_on_a_unit_that_is_not_on_the_stack_grades_nothing(monitor_weights):
    verdict = run(_input(monitor_weights, units=[], vetoed="u-ghost"))
    assert verdict.unit_id is None
    assert verdict.match is True


# --------------------------------------------------------------------------------------
# The streak
# --------------------------------------------------------------------------------------


def test_a_match_resets_the_streak():
    assert mismatch_streak([observation(1, failed=("e1",))], True) == 0


def test_the_streak_counts_back_through_failing_observations():
    window = [observation(1, failed=("e1",)), observation(2, failed=("e1",))]
    assert mismatch_streak(window, False) == 3


def test_the_streak_stops_at_the_first_passing_observation():
    window = [observation(1, passed=("e1",)), observation(2, failed=("e1",))]
    assert mismatch_streak(window, False) == 2


def test_a_vetoed_observation_extends_the_streak():
    window = [observation(1, vetoed=True, failed=("e1",))]
    assert mismatch_streak(window, False) == 2


def test_the_verdicts_streak_reads_the_committed_window(monitor_weights):
    work = unit()
    windows = {UNIT_ID: [observation(1, failed=("e1",)), observation(2, failed=("e1",))]}
    verdict = run(
        _input(monitor_weights, units=[work], windows=windows, summary=_summary(), tick=3)
    )
    assert verdict.streak == 3


# --------------------------------------------------------------------------------------
# The traps
# --------------------------------------------------------------------------------------


def test_every_unit_in_the_window_gets_all_six_scalars(monitor_weights):
    windows = {"u1": [observation(1)], "u2": [observation(1)]}
    scalars = traps_for(_input(monitor_weights, windows=windows))
    assert len(scalars) == 12
    assert {scalar.unit_id for scalar in scalars} == {"u1", "u2"}


def test_the_scalars_ride_the_verdict(monitor_weights):
    windows = {UNIT_ID: [observation(1, failed=("e1",))]}
    verdict = run(_input(monitor_weights, units=[unit()], windows=windows, summary=_summary()))
    assert len(verdict.traps) == 6
    assert all(scalar.unit_id == UNIT_ID for scalar in verdict.traps)


def test_a_dismissal_hides_every_observation_up_to_its_tick(monitor_weights):
    """Ruling 16 (a): the planner's dismissal is a real reset, not a note nobody reads."""
    ticks = int(monitor_weights[TRAP_WEIGHT_KEYS[TrapDetector.DISLODGING][0]])
    windows = {UNIT_ID: [observation(tick, failed=("e1",)) for tick in range(1, ticks + 1)]}

    before = traps_for(_input(monitor_weights, windows=windows))
    dislodging = next(s for s in before if s.detector is TrapDetector.DISLODGING)
    assert dislodging.fired is True

    dismissals = {UNIT_ID: {str(TrapDetector.DISLODGING): ticks}}
    after = traps_for(_input(monitor_weights, windows=windows, dismissals=dismissals))
    dismissed = next(s for s in after if s.detector is TrapDetector.DISLODGING)
    assert dismissed.value == 0.0
    assert dismissed.fired is False


def test_a_dismissal_touches_only_the_detector_it_names(monitor_weights):
    ticks = int(monitor_weights[TRAP_WEIGHT_KEYS[TrapDetector.FORMING][0]])
    windows = {UNIT_ID: [observation(tick, failed=("e1",)) for tick in range(1, ticks + 1)]}
    dismissals = {UNIT_ID: {str(TrapDetector.DISLODGING): ticks}}
    scalars = traps_for(_input(monitor_weights, windows=windows, dismissals=dismissals))
    forming = next(s for s in scalars if s.detector is TrapDetector.FORMING)
    assert forming.fired is True


def test_a_signal_past_its_threshold_is_not_a_stop(monitor_weights):
    """It feeds the ladder; only the ladder's last rung ends the task."""
    ticks = int(monitor_weights[TRAP_WEIGHT_KEYS[TrapDetector.DISLODGING][0]])
    windows = {UNIT_ID: [observation(tick, failed=("e1",)) for tick in range(1, ticks + 1)]}
    verdict = run(_input(monitor_weights, units=[unit()], windows=windows, summary=_summary()))
    assert any(scalar.fired for scalar in verdict.traps)
    assert verdict.interrupt is None


# --------------------------------------------------------------------------------------
# Purity
# --------------------------------------------------------------------------------------


def test_the_same_input_yields_the_same_verdict(monitor_weights):
    payload = _input(
        monitor_weights,
        units=[unit()],
        windows={UNIT_ID: [observation(1, failed=("e1",))]},
        summary=_summary(),
    )
    assert run(payload) == run(payload)


def test_the_input_model_is_not_mutated(monitor_weights):
    payload = _input(
        monitor_weights, units=[unit()], windows={UNIT_ID: [observation(1)]}, summary=_summary()
    )
    before = payload.model_dump(mode="json")
    run(payload)
    assert payload.model_dump(mode="json") == before


def test_a_missing_threshold_refuses_the_whole_verdict(monitor_weights):
    """No detector may be silently scored against zero, so the node cannot report a partial set."""
    monitor_weights.pop(TRAP_WEIGHT_KEYS[TrapDetector.PROGRESSION][0])
    with pytest.raises(KeyError):
        run(_input(monitor_weights, units=[unit()], windows={UNIT_ID: [observation(1)]}))


def test_the_goal_id_is_read_only_context(monitor_weights):
    """The monitor grades a unit; the goal stack reaches it as its read slice, unwritten."""
    work = unit()
    assert work.goal_id == GOAL_ID
    payload = _input(monitor_weights, units=[work], summary=_summary())
    run(payload)
    assert payload.units[0].goal_id == GOAL_ID


# --------------------------------------------------------------------------------------
# Repair (b) — the predicate that fails by absence (§ Deliverable 1, DoD row L1 clause 2)
# --------------------------------------------------------------------------------------


def _unit_expecting(*expectations: Expectation) -> WorkUnit:
    """A unit whose `expected` is exactly what the test hands it."""
    return WorkUnit(
        id=UNIT_ID, goal_id=GOAL_ID, intent="write the file", expected=list(expectations)
    )


CODELESS = Expectation(id="e-branch-1", kind=ExpectationKind.EXIT_CODE, arguments={})
WITH_CODE = Expectation(
    id="e-branch-2", kind=ExpectationKind.EXIT_CODE, arguments={EXPECTATION_CODE: 0}
)


def test_a_codeless_exit_code_predicate_is_ungradeable():
    """Run 1's defect, named: `summary.exit_code == None` is a grade from an absence."""
    summary = _summary(exit_code=0)
    assert ungradeable(CODELESS, summary) is True
    assert withheld_from_verdict(CODELESS, summary) is True
    assert evaluate(CODELESS, summary) is False, "which is why it failed forever before"


def test_a_code_carrying_exit_code_predicate_is_gradeable():
    summary = _summary(exit_code=0)
    assert ungradeable(WITH_CODE, summary) is False
    assert withheld_from_verdict(WITH_CODE, summary) is False


def test_a_codeless_exit_code_predicate_is_counted_neither_passed_nor_failed(monitor_weights):
    """Row L1, clause 2: classified `ungradeable`, never `failed`."""
    verdict = run(
        _input(monitor_weights, units=[_unit_expecting(CODELESS)], summary=_summary(exit_code=0))
    )
    assert verdict.failed_predicate_ids == []
    assert verdict.passed_predicate_ids == []
    assert verdict.match is True
    assert verdict.streak == 0


def test_a_code_carrying_predicate_beside_it_still_grades_normally(monitor_weights):
    """The mixed unit: the gradeable predicate decides the verdict and the other is withheld."""
    unit_ = _unit_expecting(CODELESS, WITH_CODE)

    passing = run(_input(monitor_weights, units=[unit_], summary=_summary(exit_code=0)))
    assert passing.passed_predicate_ids == ["e-branch-2"]
    assert passing.failed_predicate_ids == []
    assert passing.match is True

    failing = run(_input(monitor_weights, units=[unit_], summary=_summary(exit_code=1)))
    assert failing.passed_predicate_ids == []
    assert failing.failed_predicate_ids == ["e-branch-2"]
    assert failing.match is False


@pytest.mark.parametrize(
    "expectation",
    [
        Expectation(id="e1", kind=ExpectationKind.FILE_EXISTS, arguments={EXPECTATION_PATH: "x"}),
        Expectation(id="e1", kind=ExpectationKind.FILE_CONTAINS, arguments={EXPECTATION_VALUE: "x"}),
        Expectation(
            id="e1",
            kind=ExpectationKind.SUMMARY_FIELD_EQUALS,
            arguments={EXPECTATION_FIELD: "no_such_field", EXPECTATION_VALUE: 1},
        ),
    ],
    ids=["file_exists", "file_contains", "summary_field_equals"],
)
def test_every_other_kind_still_fails_by_absence(monitor_weights, expectation: Expectation):
    """§ Deliverable 1: *every other predicate kind's verdict is unchanged* — build 1's, exactly."""
    summary = _summary()
    assert ungradeable(expectation, summary) is True, "the classifier still names it ungradeable"
    assert withheld_from_verdict(expectation, summary) is False, "but the verdict is not withheld"

    verdict = run(_input(monitor_weights, units=[_unit_expecting(expectation)], summary=summary))
    assert verdict.failed_predicate_ids == ["e1"]
    assert verdict.match is False


def test_a_vetoed_tick_still_fails_a_codeless_predicate(monitor_weights):
    """A veto is an observation, not an absence — the veto arm is untouched by repair (b)."""
    verdict = run(
        _input(monitor_weights, units=[_unit_expecting(CODELESS)], vetoed=UNIT_ID, summary=None)
    )
    assert verdict.failed_predicate_ids == ["e-branch-1"]
    assert verdict.match is False


def test_only_the_evaluators_default_arm_is_withheld():
    """The arm map is complete: every kind but `exit_code` has its own arm in both functions."""
    assert set(ExpectationKind) - set(ARMED_KINDS) == {ExpectationKind.EXIT_CODE}


_AGREEMENT_CASES = [
    ("file_exists observed", Expectation(id="e1", kind=ExpectationKind.FILE_EXISTS,
        arguments={EXPECTATION_PATH: "out.txt"}),
        _summary(observations=[
            WorkspaceObservation(path="out.txt", exists=True, size_bytes=1, content_hash="h")
        ])),
    ("file_exists unobserved", Expectation(id="e1", kind=ExpectationKind.FILE_EXISTS,
        arguments={EXPECTATION_PATH: "out.txt"}), _summary()),
    ("file_exists no path", Expectation(id="e1", kind=ExpectationKind.FILE_EXISTS,
        arguments={}), _summary()),
    ("file_absent unobserved", Expectation(id="e1", kind=ExpectationKind.FILE_ABSENT,
        arguments={EXPECTATION_PATH: "out.txt"}), _summary()),
    ("file_contains read", Expectation(id="e1", kind=ExpectationKind.FILE_CONTAINS,
        arguments={EXPECTATION_VALUE: "hi"}), _summary(expectation_values={"e1": "hi there"})),
    ("file_contains unread", Expectation(id="e1", kind=ExpectationKind.FILE_CONTAINS,
        arguments={EXPECTATION_VALUE: "hi"}), _summary()),
    ("file_contains no value", Expectation(id="e1", kind=ExpectationKind.FILE_CONTAINS,
        arguments={}), _summary(expectation_values={"e1": "hi there"})),
    ("summary_field known", Expectation(id="e1", kind=ExpectationKind.SUMMARY_FIELD_EQUALS,
        arguments={EXPECTATION_FIELD: "narrative", EXPECTATION_VALUE: "did it"}), _summary()),
    ("summary_field unknown", Expectation(id="e1", kind=ExpectationKind.SUMMARY_FIELD_EQUALS,
        arguments={EXPECTATION_FIELD: "nope", EXPECTATION_VALUE: 1}), _summary()),
    ("summary_field no field", Expectation(id="e1", kind=ExpectationKind.SUMMARY_FIELD_EQUALS,
        arguments={EXPECTATION_VALUE: 1}), _summary()),
    ("exit_code with code", WITH_CODE, _summary(exit_code=0)),
    ("exit_code codeless", CODELESS, _summary(exit_code=0)),
]


@pytest.mark.parametrize(
    "expectation,summary", [case[1:] for case in _AGREEMENT_CASES],
    ids=[case[0] for case in _AGREEMENT_CASES],
)
def test_the_node_and_the_run_report_classify_identically(expectation, summary):
    """The duplicate is pinned. `runtime/report.py` is the writer; a node may not import it.

    Both functions are one arm per arm of `evaluate()` in the same order; this is the test that
    turns "deliberately duplicated" into a checkable claim rather than a comment.
    """
    assert ungradeable(expectation, summary) == report_ungradeable(expectation, summary)

