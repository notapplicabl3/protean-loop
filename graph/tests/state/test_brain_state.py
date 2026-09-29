"""M2, first half: `BrainState` v1 carries every field § Deliverable 2's table names.

The nested tables get one case per field name, so a field dropped from a nested contract fails
as itself rather than inside a round-trip assertion that could be read three ways — `GoalItem`'s
ladder counters and `UnitObservation`'s twelve columns are named in the same table and are as
much part of v1 as the top-level slots.

**v1 is complete.** Nothing below is a later bump (decision 10), so this list is not a
snapshot of today's model — it is the contract, transcribed from the SPEC, and the model is
what has to agree with it.
"""

from __future__ import annotations

import pytest

from protean import config
from protean.state import (
    BrainState,
    CostCounters,
    GoalItem,
    LatestOutputs,
    Modulators,
    PathBaseline,
    ProjectExtension,
    TerminalState,
    UnitObservation,
    WorkUnit,
)
from tests.state.conftest import populated_state

#: § Deliverable 2's state table, group by group, in its order.
STATE_FIELDS = (
    "schema_version",
    "task_id",
    "tick",
    "goals",
    "units",
    "latest",
    "unit_windows",
    "path_baselines",
    "window_len",
    "trap_dismissals",
    "open_interrupts",
    "resolved_interrupts",
    "seat_sessions",
    "cost",
    "ceiling_overrides",
    "modulators",
    "constraints",
    "terminal",
    "extensions",
)

#: The nested models the same table names, field by field.
NESTED_FIELDS = {
    GoalItem: (
        "id",
        "text",
        "status",
        "opened_at_tick",
        "last_progress_tick",
        "replan_count",
        "redirect_count",
    ),
    WorkUnit: ("id", "revision", "goal_id", "status"),
    LatestOutputs: (
        "homeostasis",
        "hippocampus",
        "thalamus",
        "basal_ganglia",
        "anterior_cingulate",
        "director",
        "manager",
        "dispatch",
    ),
    UnitObservation: (
        "tick",
        "unit_revision",
        "failed_predicate_ids",
        "passed_predicate_ids",
        "change_bytes",
        "change_bytes_total",
        "paths_new",
        "abandoned",
        "vetoed",
        "uncited_ratio",
        "redirect_by",
        "mismatch_class",
    ),
    PathBaseline: ("size_bytes", "content_hash", "tick"),
    CostCounters: ("tokens", "wall_seconds", "errors", "ticks"),
    Modulators: ("reward_error", "arousal", "confidence"),
    ProjectExtension: ("name", "version", "payload"),
}

NESTED_CASES = [(m, f) for m, fields in NESTED_FIELDS.items() for f in fields]


@pytest.mark.parametrize(
    "case", NESTED_CASES, ids=lambda c: f"{c[0].__name__}.{c[1]}"
)
def test_the_nested_contract_carries(case: tuple[type, str]) -> None:
    model, field = case
    assert field in model.model_fields


def test_v1_has_no_field_the_spec_does_not_name() -> None:
    """Both directions at once: a field nobody wrote down is a contract nobody agreed to, and
    set equality also carries every `field in BrainState.model_fields` case the top-level list
    used to get one by one.

    The "fails as itself" argument lives here now. A dropped top-level field no longer fails
    under its own test name — it fails as a diff of two sorted lists, which names it just as
    plainly and cannot be read as a round-trip failure. The nested tables keep the per-field
    shape because they have no equality sibling.
    """
    assert sorted(BrainState.model_fields) == sorted(STATE_FIELDS)


def test_the_schema_version_default_is_the_one_config_pins() -> None:
    assert BrainState(task_id="t").schema_version == config.BRAIN_STATE_SCHEMA_VERSION


def test_no_progress_ticks_is_derived_and_never_stored() -> None:
    """folded: T-10 — a stored copy is a second source of truth a resume can desynchronize."""
    assert "no_progress_ticks" not in GoalItem.model_fields
    goal = GoalItem(id="g-1", text="ship it", opened_at_tick=1, last_progress_tick=4)
    assert goal.no_progress_ticks(9) == 5


def test_seat_sessions_are_keyed_by_tier_and_a_fourth_key_is_refused() -> None:
    state = BrainState(task_id="t", seat_sessions={t: f"s-{t}" for t in config.TIERS})
    assert sorted(state.seat_sessions) == sorted(config.TIERS)
    with pytest.raises(Exception) as raised:
        BrainState(task_id="t", seat_sessions={"oracle": "s-4"})
    assert "unknown keys" in str(raised.value)


def test_a_task_occupies_the_root_until_its_terminal_is_done() -> None:
    """§ Deliverable 3: `run` refuses while a task exists whose terminal is anything but done."""
    assert BrainState(task_id="t").occupies_root() is True
    assert BrainState(task_id="t", terminal=TerminalState.STUCK).occupies_root() is True
    assert BrainState(task_id="t", terminal=TerminalState.DONE).occupies_root() is False


def test_open_goals_ignores_closed_items_which_are_retained() -> None:
    state = BrainState(
        task_id="t",
        goals=[
            GoalItem(id="g-1", text="a", opened_at_tick=0, last_progress_tick=0),
            GoalItem(
                id="g-2", text="b", status="satisfied", opened_at_tick=0, last_progress_tick=1
            ),
        ],
    )
    assert [g.id for g in state.open_goals()] == ["g-1"]
    assert len(state.goals) == 2


def test_a_populated_state_round_trips_through_json_unchanged() -> None:
    state = populated_state()
    assert BrainState.model_validate(state.model_dump(mode="json")) == state
