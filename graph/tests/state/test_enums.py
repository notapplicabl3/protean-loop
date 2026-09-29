"""Every closed set is closed, and `config` is the one owner of the literals it shares.

`the build specification (not in this mirror)` § Deliverable 2, § Deliverable 3 (the five terminal states),
§ Deliverable 6 (three tiers, three is the ceiling).

A closed set that quietly gained a member would widen a contract without anyone editing a
contract, so each one is asserted **by exact value list**, not by membership. The agreement
between `protean.config` and the enums is asserted here as well as at import time: the import
guard fails the whole package, which is right at runtime and useless as a receipt.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from protean import config
from protean.state import (
    CallType,
    ConstraintKind,
    EpisodeKind,
    Escalation,
    EventName,
    ExpectationKind,
    GoalStatus,
    InterruptKind,
    MismatchClass,
    NodeName,
    Raiser,
    SelectionDecision,
    TerminalState,
    Tier,
    TraceKind,
    TraceSource,
    TrapDetector,
    UnitStatus,
    WorkUnit,
)

CLOSED_SETS = {
    NodeName: (
        "homeostasis",
        "hippocampus",
        "thalamus",
        "basal_ganglia",
        "cortex",
        "anterior_cingulate",
    ),
    Tier: ("director", "manager"),
    CallType: ("think", "escalate", "delegate", "dispatch"),
    TerminalState: ("done", "blocked", "stopped", "interrupted", "stuck"),
    GoalStatus: ("open", "satisfied", "abandoned"),
    UnitStatus: ("pending", "active", "passed", "abandoned"),
    SelectionDecision: ("go", "no_go"),
    ConstraintKind: ("path_scope", "allow_irreversible", "budget"),
    ExpectationKind: (
        "file_exists",
        "file_absent",
        "file_contains",
        "summary_field_equals",
        "exit_code",
    ),
    MismatchClass: ("approach_wrong", "execution_slip"),
    InterruptKind: ("question", "stuck"),
    TraceKind: ("prediction", "outcome"),
    TraceSource: (
        "node",
        "runtime",
        "firing",
        "runtime_grade",
        "operator_answer",
        "firing_grade",
    ),
    EpisodeKind: ("tick", "event"),
    # Two of the eight metacognitive traps are deliberately not here: Assumption needs a second
    # expectation source, which is build 2's oracle.
    TrapDetector: (
        "dislodging",
        "forming",
        "location",
        "interruption",
        "misleading",
        "progression",
    ),
}


@pytest.mark.parametrize("case", CLOSED_SETS.items(), ids=lambda c: c[0].__name__)
def test_the_set_is_exactly_these_members(case) -> None:
    enum, members = case
    assert tuple(m.value for m in enum) == members


def test_the_node_order_is_the_cycle_the_spec_draws() -> None:
    """decision 8, and binding contract 5's first half: the order is a literal in config.py."""
    assert config.NODE_ORDER == (
        "homeostasis",
        "hippocampus",
        "thalamus",
        "basal_ganglia",
        "cortex",
        "anterior_cingulate",
    )
    assert config.DETERMINISTIC_NODES == (
        "homeostasis",
        "hippocampus",
        "thalamus",
        "basal_ganglia",
        "anterior_cingulate",
    )
    assert config.CORTEX_NODE == "cortex"


def test_config_and_the_enums_agree() -> None:
    assert sorted(config.NODE_ORDER) == sorted(n.value for n in NodeName)
    assert sorted(config.TIERS) == sorted(t.value for t in Tier)
    assert sorted(config.TERMINAL_STATES) == sorted(t.value for t in TerminalState)


def test_every_raiser_is_a_node_a_seat_a_call_type_or_the_runtime() -> None:
    """Contract 4's first amendment, re-based rather than relaxed.

    Build A.1 widened `Raiser` because a subagent and a non-seat call had nowhere legal to sit:
    the five outer nodes, the two seats, **every call type** and the runtime. `planner` and
    `executor` left with their tiers.
    """
    assert set(r.value for r in Raiser) == (
        set(config.DETERMINISTIC_NODES)
        | set(config.TIERS)
        | set(config.CALL_TYPES)
        | {"runtime"}
    )


def test_the_event_names_are_the_ones_the_commit_protocol_writes() -> None:
    assert tuple(e.value for e in EventName) == (
        "task_start",
        "lock_reclaimed",
        "interrupt_resolved",
        "terminal",
        "terminal_loser",
        "abandoned",
        "reseeded",
    )


def test_the_escalations_climb_the_ladder_in_order() -> None:
    assert tuple(e.value for e in Escalation) == (
        "empty_unit_stack",
        "mismatch_streak",
        "trap_signal",
        "veto",
        "replan_exhausted",
        "redirect_exhausted",
    )


@pytest.mark.parametrize("bad", ["Done", "DONE", "finished", ""])
def test_a_value_outside_a_closed_set_is_refused(bad: str) -> None:
    with pytest.raises(ValidationError):
        WorkUnit(id="u", goal_id="g", intent="i", status=bad)
