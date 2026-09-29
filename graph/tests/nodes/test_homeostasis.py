"""Homeostasis — it measures, and it raises the one stop it is allowed.

`the build specification (not in this mirror)` § Deliverable 2's `HomeostasisReport` row ("cumulative per
task", "the read-out of `BrainState.cost`") and § Deliverable 3's `stopped` terminal —
"homeostasis's contractual stop, including the tick ceiling from its weights".

Builder-verified row M20's homeostasis half. **Every ceiling arrives on `weights`**; the module
names no number, so every assertion below reads its expectation out of the seed file rather
than restating one.
"""

from __future__ import annotations

import pytest

from protean.nodes.homeostasis import (
    CEILING_KEYS,
    CEILING_TICKS,
    CEILING_TOKENS,
    CEILING_WALL_SECONDS,
    effective_ceilings,
    error_rate,
    run,
)
from protean.state.enums import ConstraintKind
from protean.state.inputs import HomeostasisInput
from protean.state.outputs import HomeostasisReport
from protean.state.primitives import Constraint
from tests.nodes.conftest import TASK_ID, cost, overrides


def _input(weights, *, counters=None, ceiling_overrides=None, constraints=(), tick=1):
    return HomeostasisInput(
        task_id=TASK_ID,
        tick=tick,
        weights=dict(weights),
        cost=counters if counters is not None else cost(),
        ceiling_overrides=ceiling_overrides if ceiling_overrides is not None else overrides(),
        constraints=list(constraints),
    )


def test_the_report_is_the_read_out_of_the_cost_counters(homeostasis_weights):
    counters = cost(tokens=1200, wall_seconds=3.5, errors=2, ticks=8)
    report = run(_input(homeostasis_weights, counters=counters))

    assert isinstance(report, HomeostasisReport)
    assert report.emitter == "homeostasis"
    assert report.tokens == 1200
    assert report.wall_seconds == 3.5
    assert report.ticks == 8
    assert report.error_rate == pytest.approx(2 / 8)
    assert report.tick == 1


def test_it_is_cumulative_per_task_not_per_tick(homeostasis_weights):
    """Two reports off a growing counter grow with it — nothing here resets."""
    first = run(_input(homeostasis_weights, counters=cost(tokens=10, ticks=1)))
    second = run(_input(homeostasis_weights, counters=cost(tokens=25, ticks=2), tick=2))
    assert (first.tokens, second.tokens) == (10, 25)
    assert (first.ticks, second.ticks) == (1, 2)


def test_a_task_that_has_run_no_tick_has_no_error_rate():
    assert error_rate(3, 0) == 0.0
    assert error_rate(0, 0) == 0.0
    assert error_rate(3, 6) == 0.5


def test_the_ceilings_reported_are_exactly_the_weights_files_keys(homeostasis_weights):
    report = run(_input(homeostasis_weights))
    assert set(report.ceilings) == {
        key for key in CEILING_KEYS if key in homeostasis_weights
    }
    for key, value in report.ceilings.items():
        assert value == float(homeostasis_weights[key])


def test_a_ceiling_absent_from_the_weights_file_is_not_invented(homeostasis_weights):
    homeostasis_weights.pop(CEILING_TOKENS)
    report = run(_input(homeostasis_weights))
    assert CEILING_TOKENS not in report.ceilings


def test_no_ceiling_crossed_means_no_stop(homeostasis_weights):
    report = run(_input(homeostasis_weights, counters=cost(ticks=1, tokens=1)))
    assert report.stop is False
    assert report.stop_reason is None


def test_a_crossed_tick_ceiling_stops_and_names_the_key(homeostasis_weights):
    ceiling = int(homeostasis_weights[CEILING_TICKS])
    report = run(_input(homeostasis_weights, counters=cost(ticks=ceiling)))
    assert report.stop is True
    assert CEILING_TICKS in report.stop_reason


def test_the_ceiling_is_crossed_at_equality_not_only_past_it(homeostasis_weights):
    ceiling = int(homeostasis_weights[CEILING_TICKS])
    assert run(_input(homeostasis_weights, counters=cost(ticks=ceiling - 1))).stop is False
    assert run(_input(homeostasis_weights, counters=cost(ticks=ceiling))).stop is True


def test_every_crossed_ceiling_is_named_in_the_reason(homeostasis_weights):
    counters = cost(
        ticks=int(homeostasis_weights[CEILING_TICKS]),
        tokens=int(homeostasis_weights[CEILING_TOKENS]),
    )
    report = run(_input(homeostasis_weights, counters=counters))
    assert CEILING_TICKS in report.stop_reason
    assert CEILING_TOKENS in report.stop_reason


# --------------------------------------------------------------------------------------
# `resume --extend` and a `budget` constraint
# --------------------------------------------------------------------------------------


def test_an_extend_raises_the_tick_ceiling(homeostasis_weights):
    base = float(homeostasis_weights[CEILING_TICKS])
    payload = _input(homeostasis_weights, ceiling_overrides=overrides(extra_ticks=5))
    assert effective_ceilings(payload)[CEILING_TICKS] == base + 5


def test_an_extend_raises_the_wall_clock_ceiling_in_seconds(homeostasis_weights):
    base = float(homeostasis_weights[CEILING_WALL_SECONDS])
    payload = _input(homeostasis_weights, ceiling_overrides=overrides(extra_seconds=120.0))
    assert effective_ceilings(payload)[CEILING_WALL_SECONDS] == base + 120.0


def test_an_extend_lets_a_stopped_task_pass_its_ceiling(homeostasis_weights):
    ceiling = int(homeostasis_weights[CEILING_TICKS])
    counters = cost(ticks=ceiling)
    assert run(_input(homeostasis_weights, counters=counters)).stop is True
    extended = run(
        _input(
            homeostasis_weights,
            counters=counters,
            ceiling_overrides=overrides(extra_ticks=1),
        )
    )
    assert extended.stop is False


def test_a_budget_constraint_narrows_a_named_ceiling(homeostasis_weights):
    constraint = Constraint(
        kind=ConstraintKind.BUDGET, arguments={CEILING_TICKS: 3}, set_at_tick=0
    )
    payload = _input(homeostasis_weights, constraints=[constraint])
    assert effective_ceilings(payload)[CEILING_TICKS] == 3.0
    assert run(_input(homeostasis_weights, counters=cost(ticks=3), constraints=[constraint])).stop


def test_a_budget_constraint_never_widens_a_ceiling(homeostasis_weights):
    base = float(homeostasis_weights[CEILING_TICKS])
    constraint = Constraint(
        kind=ConstraintKind.BUDGET, arguments={CEILING_TICKS: base * 10}, set_at_tick=0
    )
    payload = _input(homeostasis_weights, constraints=[constraint])
    assert effective_ceilings(payload)[CEILING_TICKS] == base


def test_the_tightest_budget_wins(homeostasis_weights):
    constraints = [
        Constraint(kind=ConstraintKind.BUDGET, arguments={CEILING_TICKS: 9}, set_at_tick=0),
        Constraint(kind=ConstraintKind.BUDGET, arguments={CEILING_TICKS: 4}, set_at_tick=1),
    ]
    payload = _input(homeostasis_weights, constraints=constraints)
    assert effective_ceilings(payload)[CEILING_TICKS] == 4.0


def test_a_budget_cannot_be_escaped_by_an_extend(homeostasis_weights):
    """The extend is added to the weights ceiling *before* the budget narrows it."""
    constraint = Constraint(
        kind=ConstraintKind.BUDGET, arguments={CEILING_TICKS: 3}, set_at_tick=0
    )
    payload = _input(
        homeostasis_weights,
        constraints=[constraint],
        ceiling_overrides=overrides(extra_ticks=100),
    )
    assert effective_ceilings(payload)[CEILING_TICKS] == 3.0


def test_a_non_budget_constraint_moves_no_ceiling(homeostasis_weights):
    constraint = Constraint(
        kind=ConstraintKind.PATH_SCOPE, arguments={"paths": ["src"]}, set_at_tick=0
    )
    base = effective_ceilings(_input(homeostasis_weights))
    assert effective_ceilings(_input(homeostasis_weights, constraints=[constraint])) == base


# --------------------------------------------------------------------------------------
# Purity
# --------------------------------------------------------------------------------------


def test_the_same_input_yields_the_same_report(homeostasis_weights):
    payload = _input(homeostasis_weights, counters=cost(tokens=5, ticks=2, errors=1))
    assert run(payload) == run(payload)


def test_the_input_model_is_not_mutated(homeostasis_weights):
    payload = _input(homeostasis_weights, counters=cost(tokens=5, ticks=2))
    before = payload.model_dump(mode="json")
    run(payload)
    assert payload.model_dump(mode="json") == before


def test_it_raises_no_interrupt_of_its_own(homeostasis_weights):
    """The stop is inhibition; a question is a seat's job (§ Deliverable 5's two raisers)."""
    assert run(_input(homeostasis_weights, counters=cost(ticks=10_000))).interrupt is None
