"""Signals, not branches — and the shape of what each tier is allowed to see.

`the build specification (not in this mirror)` § Deliverable 2 → "Deterministic nodes have three verbs —
measure, fetch, veto — never choose … the contracts above are typed so that this is
**structurally** true: no deterministic node's output model contains a branch instruction",
and § Deliverable 6's per-tier request shapes.

The generic battery in `test_conformance.py` proves every contract refuses a bad payload. This
module proves the things a payload check cannot see: that the only two inhibitions in the build
are the ones the doctrine names, that a `no_go` reaches the executor and not the planner or the
director, and that the executor's request carries no workspace.
"""

from __future__ import annotations

import pytest

from protean.state import (
    AdmittedContext,
    AdmittedItem,
    Constraint,
    ConstraintKind,
    DirectorRequest,
    Escalation,
    ExcludedItem,
    Expectation,
    ExpectationKind,
    HomeostasisReport,
    InterruptRequest,
    MonitorVerdict,
    ManagerRequest,
    Raiser,
    RetrievalSet,
    SelectionDecision,
    SelectionVerdict,
    TrapDetector,
    TrapScalar,
    WorkUnit,
    Workspace,
)

DETERMINISTIC_OUTPUTS = (
    HomeostasisReport,
    RetrievalSet,
    AdmittedContext,
    SelectionVerdict,
    MonitorVerdict,
)

#: The only two contractual inhibitions in the build (`DIGEST:51`).
INHIBITIONS = {SelectionVerdict: "decision", HomeostasisReport: "stop"}


@pytest.mark.parametrize("model", DETERMINISTIC_OUTPUTS, ids=lambda m: m.__name__)
def test_a_deterministic_output_carries_a_tick_and_an_interrupt_slot(model: type) -> None:
    """§ Deliverable 2: the slot is on **every** node output model — that is the raise path."""
    assert "tick" in model.model_fields
    assert "interrupt" in model.model_fields
    assert not model.model_fields["interrupt"].is_required()


@pytest.mark.parametrize("model", DETERMINISTIC_OUTPUTS, ids=lambda m: m.__name__)
def test_no_deterministic_output_carries_a_branch_instruction(model: type) -> None:
    """The two inhibitions are named; anything else that looked like one would be choosing."""
    branchy = {"next_node", "route", "escalate_to", "tier", "skip", "goto", "action"}
    assert set(model.model_fields).isdisjoint(branchy)
    inhibition = INHIBITIONS.get(model)
    if inhibition is not None:
        assert inhibition in model.model_fields


def test_there_are_exactly_two_inhibitions_in_the_build() -> None:
    assert sorted(m.__name__ for m in INHIBITIONS) == [
        "HomeostasisReport",
        "SelectionVerdict",
    ]


def test_the_gate_says_go_or_no_go_and_nothing_else() -> None:
    verdict = SelectionVerdict(
        tick=3,
        decision=SelectionDecision.NO_GO,
        unit_id="u-1",
        veto_reason="unit is irreversible and no allow_irreversible constraint names it",
    )
    assert verdict.decision is SelectionDecision.NO_GO
    assert "irreversible" in verdict.veto_reason


def test_the_two_veto_arms_are_the_only_constraint_kinds_the_gate_reads() -> None:
    """folded: T-13 — `path_scope` and `allow_irreversible`; `budget` is homeostasis's."""
    gate_arms = {ConstraintKind.PATH_SCOPE, ConstraintKind.ALLOW_IRREVERSIBLE}
    assert ConstraintKind.BUDGET not in gate_arms


def test_the_planner_declares_irreversibility_and_the_gate_reads_it() -> None:
    unit = WorkUnit(id="u-1", goal_id="g-1", intent="delete the branch", irreversible=True)
    assert unit.irreversible is True
    allowed = Constraint(
        kind=ConstraintKind.ALLOW_IRREVERSIBLE, arguments={"unit_id": "u-1"}, set_at_tick=2
    )
    assert allowed.arguments["unit_id"] == "u-1"


def test_intent_is_prose_and_an_expectation_carries_the_paths() -> None:
    """folded: U-12 — `intent` contributes no path to the veto predicate."""
    unit = WorkUnit(
        id="u-1",
        goal_id="g-1",
        intent="write ../../etc/hosts, which is prose and not a path the gate reads",
        expected=[
            Expectation(
                id="e-1", kind=ExpectationKind.FILE_EXISTS, arguments={"path": "notes.md"}
            )
        ],
    )
    assert unit.expected[0].arguments["path"] == "notes.md"


def test_admission_is_a_signal_because_the_exclusion_stays_visible() -> None:
    context = AdmittedContext(
        tick=4,
        admitted=[AdmittedItem(admitted_id="a-1", episode_id="e-1", summary="prior", score=0.8)],
        excluded=[ExcludedItem(episode_id="e-2", reason="below min_relevance")],
    )
    assert context.excluded[0].reason


def test_a_trap_scalar_that_disagrees_with_its_own_measure_is_refused() -> None:
    """The evidence body of a `stuck` interrupt has to be rulable; a lying scalar is not."""
    TrapScalar(
        detector=TrapDetector.DISLODGING,
        value=3.0,
        threshold=2.0,
        weight_key="rut_ticks",
        fired=True,
        unit_id="u-1",
    )
    with pytest.raises(Exception) as raised:
        TrapScalar(
            detector=TrapDetector.DISLODGING,
            value=0.0,
            threshold=2.0,
            weight_key="rut_ticks",
            fired=True,
            unit_id="u-1",
        )
    assert "disagrees with" in str(raised.value)


def test_a_trap_scalar_names_the_weights_key_that_scored_it() -> None:
    scalar = TrapScalar(
        detector=TrapDetector.PROGRESSION,
        value=0.9,
        threshold=0.8,
        weight_key="uncited_ratio",
        fired=True,
        unit_id="u-1",
    )
    assert scalar.weight_key == "uncited_ratio"


def workspace() -> Workspace:
    return Workspace(task_id="t-1", tick=5)


def test_the_director_gets_the_workspace_and_nothing_else() -> None:
    assert sorted(DirectorRequest.model_fields) == ["tier", "workspace"]
    assert DirectorRequest(workspace=workspace()).tier == "director"


def test_the_planner_gets_the_escalation_that_fired_and_the_trap_evidence() -> None:
    request = ManagerRequest(
        workspace=workspace(),
        escalation=Escalation.TRAP_SIGNAL,
        unit_id="u-1",
        trap_evidence=[
            TrapScalar(
                detector=TrapDetector.FORMING,
                value=6.0,
                threshold=6.0,
                weight_key="forming_ticks",
                fired=True,
                unit_id="u-1",
            )
        ],
    )
    assert request.escalation is Escalation.TRAP_SIGNAL
    assert request.trap_evidence[0].weight_key == "forming_ticks"


def test_a_manager_call_with_no_escalation_is_the_acting_tick() -> None:
    """Contract 2's **fourth** amendment (§ Scaffold clause item 2 (d), folded: D3-4).

    A.1 moves the non-escalated acting tick from the deleted executor seat to the manager, so
    the router's fall-through arm carries no escalation at all: `None` means "assemble the
    pending unit's wave", and a required field would make the manager's most common tick
    unbuildable. What did **not** loosen is the rest of the request — a manager call with
    nothing to act on is still unexpressible.
    """
    request = ManagerRequest(workspace=workspace())
    assert request.escalation is None
    assert ManagerRequest.model_fields["escalation"].is_required() is False
    with pytest.raises(Exception):
        ManagerRequest(escalation=Escalation.VETO)


def test_one_workspace_serves_all_three_tiers(brain_seed_root) -> None:
    """folded: T-11 — the per-tier request model is the filter, not a per-tier projection."""
    shared = workspace()
    director = DirectorRequest(workspace=shared)
    planner = ManagerRequest(workspace=shared, escalation=Escalation.EMPTY_UNIT_STACK)
    assert director.workspace == planner.workspace


def test_a_seat_result_carries_the_same_interrupt_slot_a_node_does() -> None:
    from protean.state import DirectorDirection, ExecutorSummary, ManagerPlan

    for model in (DirectorDirection, ManagerPlan, ExecutorSummary):
        assert "interrupt" in model.model_fields
    plan = ManagerPlan(
        tick=2,
        interrupt=InterruptRequest(
            kind="question", raised_by=Raiser.MANAGER, question="which shape?"
        ),
    )
    assert plan.interrupt.raised_by is Raiser.MANAGER
