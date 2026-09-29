"""The gate. One verb — veto — and the predicate is catastrophic-only.

`the build specification (not in this mirror)` § Deliverable 2's `SelectionVerdict` row, decision 29, and
`brain/nodes/basal_ganglia/NODE.md`. **Two arms and nothing else vetoes** (folded: T-13):

* (a) an `Expectation` argument path outside the workspace root as narrowed by `path_scope`;
* (b) `irreversible: true` with no `allow_irreversible` constraint naming the unit.

`WorkUnit.intent` is prose and contributes no path (folded: U-12), and the gate has **no
weights**: a tunable on a catastrophic-only gate is an invitation to loosen it.
"""

from __future__ import annotations

import pytest

from protean.nodes.basal_ganglia import expectation_paths, run
from protean.nodes.vocabulary import (
    ALLOW_IRREVERSIBLE_UNIT_IDS,
    EXPECTATION_PATH,
    PATH_SCOPE_PATHS,
)
from protean.state.enums import ConstraintKind, ExpectationKind, SelectionDecision
from protean.state.inputs import BasalGangliaInput
from protean.state.outputs import AdmittedContext, SelectionVerdict
from protean.state.primitives import Constraint, Expectation
from tests.nodes.conftest import TASK_ID, UNIT_ID, unit

WORKSPACE = "/tmp/protean-workspace"


def _input(weights, *, pending=None, constraints=(), root=WORKSPACE, tick=1):
    return BasalGangliaInput(
        task_id=TASK_ID,
        tick=tick,
        weights=dict(weights),
        pending_unit=pending,
        admitted=AdmittedContext(tick=tick),
        constraints=list(constraints),
        workspace_root=root,
    )


def _scope(*paths: str, tick: int = 0) -> Constraint:
    return Constraint(
        kind=ConstraintKind.PATH_SCOPE, arguments={PATH_SCOPE_PATHS: list(paths)},
        set_at_tick=tick,
    )


def _allow(*unit_ids: str, tick: int = 0) -> Constraint:
    return Constraint(
        kind=ConstraintKind.ALLOW_IRREVERSIBLE,
        arguments={ALLOW_IRREVERSIBLE_UNIT_IDS: list(unit_ids)},
        set_at_tick=tick,
    )


# --------------------------------------------------------------------------------------
# The default is `go`
# --------------------------------------------------------------------------------------


def test_no_pending_unit_is_a_go_naming_no_unit(gate_weights):
    verdict = run(_input(gate_weights))
    assert isinstance(verdict, SelectionVerdict)
    assert verdict.emitter == "basal_ganglia"
    assert verdict.decision is SelectionDecision.GO
    assert verdict.unit_id is None
    assert verdict.veto_reason is None


def test_an_in_scope_unit_is_a_go_naming_the_unit(gate_weights):
    verdict = run(_input(gate_weights, pending=unit()))
    assert verdict.decision is SelectionDecision.GO
    assert verdict.unit_id == UNIT_ID
    assert verdict.veto_reason is None


def test_a_unit_with_no_predicates_is_a_go(gate_weights):
    verdict = run(_input(gate_weights, pending=unit(paths=())))
    assert verdict.decision is SelectionDecision.GO


# --------------------------------------------------------------------------------------
# Arm (a) — the path scope
# --------------------------------------------------------------------------------------


def test_a_relative_path_escaping_the_root_is_vetoed(gate_weights):
    verdict = run(_input(gate_weights, pending=unit(paths=("../outside.txt",))))
    assert verdict.decision is SelectionDecision.NO_GO
    assert "../outside.txt" in verdict.veto_reason
    assert verdict.unit_id == UNIT_ID


def test_an_absolute_path_outside_the_root_is_vetoed(gate_weights):
    verdict = run(_input(gate_weights, pending=unit(paths=("/etc/hosts",))))
    assert verdict.decision is SelectionDecision.NO_GO
    assert "/etc/hosts" in verdict.veto_reason


def test_a_path_scope_constraint_narrows_the_root(gate_weights):
    inside = run(
        _input(gate_weights, pending=unit(paths=("src/a.py",)), constraints=[_scope("src")])
    )
    outside = run(
        _input(gate_weights, pending=unit(paths=("docs/a.md",)), constraints=[_scope("src")])
    )
    assert inside.decision is SelectionDecision.GO
    assert outside.decision is SelectionDecision.NO_GO
    assert "src" in outside.veto_reason


def test_several_scopes_are_a_union(gate_weights):
    constraints = [_scope("src"), _scope("docs")]
    for path in ("src/a.py", "docs/a.md"):
        assert (
            run(_input(gate_weights, pending=unit(paths=(path,)), constraints=constraints)).decision
            is SelectionDecision.GO
        )
    assert (
        run(
            _input(gate_weights, pending=unit(paths=("other/a",)), constraints=constraints)
        ).decision
        is SelectionDecision.NO_GO
    )


def test_an_empty_scope_list_means_the_unnarrowed_root(gate_weights):
    verdict = run(_input(gate_weights, pending=unit(), constraints=[_scope()]))
    assert verdict.decision is SelectionDecision.GO


def test_one_out_of_scope_predicate_vetoes_the_whole_unit(gate_weights):
    verdict = run(_input(gate_weights, pending=unit(paths=("in.txt", "/etc/hosts"))))
    assert verdict.decision is SelectionDecision.NO_GO


def test_the_intent_prose_contributes_no_path(gate_weights):
    """`WorkUnit.intent` is prose (folded: U-12): only `Expectation` arguments are walked."""
    pending = unit(paths=("in.txt",), intent="delete /etc/hosts and ../../secrets")
    assert run(_input(gate_weights, pending=pending)).decision is SelectionDecision.GO
    assert expectation_paths(pending) == ["in.txt"]


def test_only_path_bearing_expectation_kinds_are_walked(gate_weights):
    pending = unit(paths=())
    pending.expected.append(
        Expectation(id="e9", kind=ExpectationKind.EXIT_CODE, arguments={"code": 0})
    )
    assert expectation_paths(pending) == []
    assert run(_input(gate_weights, pending=pending)).decision is SelectionDecision.GO


def test_the_gate_touches_no_filesystem(gate_weights, tmp_path):
    """A root that does not exist yields the same verdict: nothing is stat-ed or resolved."""
    absent = str(tmp_path / "never-created")
    assert (
        run(_input(gate_weights, pending=unit(), root=absent)).decision is SelectionDecision.GO
    )
    assert (
        run(_input(gate_weights, pending=unit(paths=("/etc/hosts",)), root=absent)).decision
        is SelectionDecision.NO_GO
    )


# --------------------------------------------------------------------------------------
# Arm (b) — the irreversible declaration
# --------------------------------------------------------------------------------------


def test_an_irreversible_unit_with_no_clearance_is_vetoed(gate_weights):
    verdict = run(_input(gate_weights, pending=unit(irreversible=True)))
    assert verdict.decision is SelectionDecision.NO_GO
    assert "irreversible" in verdict.veto_reason
    assert UNIT_ID in verdict.veto_reason


def test_an_allow_irreversible_constraint_naming_the_unit_clears_it(gate_weights):
    verdict = run(
        _input(gate_weights, pending=unit(irreversible=True), constraints=[_allow(UNIT_ID)])
    )
    assert verdict.decision is SelectionDecision.GO


def test_clearance_for_another_unit_does_not_clear_this_one(gate_weights):
    verdict = run(
        _input(gate_weights, pending=unit(irreversible=True), constraints=[_allow("u-other")])
    )
    assert verdict.decision is SelectionDecision.NO_GO


def test_the_gate_does_not_infer_irreversibility(gate_weights):
    """The planner declares it; nothing in the intent or the predicate kinds implies it."""
    pending = unit(intent="rm -rf the whole tree", irreversible=False)
    assert run(_input(gate_weights, pending=pending)).decision is SelectionDecision.GO


def test_the_path_arm_is_checked_before_the_irreversible_arm(gate_weights):
    verdict = run(
        _input(
            gate_weights,
            pending=unit(paths=("/etc/hosts",), irreversible=True),
            constraints=[_allow(UNIT_ID)],
        )
    )
    assert verdict.decision is SelectionDecision.NO_GO
    assert "/etc/hosts" in verdict.veto_reason


# --------------------------------------------------------------------------------------
# Nothing else vetoes
# --------------------------------------------------------------------------------------


def test_a_budget_constraint_never_vetoes(gate_weights):
    constraint = Constraint(
        kind=ConstraintKind.BUDGET, arguments={"max_ticks": 0}, set_at_tick=0
    )
    assert (
        run(_input(gate_weights, pending=unit(), constraints=[constraint])).decision
        is SelectionDecision.GO
    )


def test_the_gate_reads_nothing_out_of_its_weights(gate_weights):
    """`brain/nodes/basal_ganglia/weights.yaml` is the empty mapping, deliberately."""
    assert gate_weights == {}
    noisy = run(_input({"rut_ticks": 0, "anything": 1}, pending=unit(irreversible=True)))
    assert noisy.decision is SelectionDecision.NO_GO
    assert run(_input({"rut_ticks": 0}, pending=unit())).decision is SelectionDecision.GO


def test_the_admitted_context_does_not_change_the_verdict(gate_weights):
    """The gate is handed this tick's admission, and it is not part of the predicate."""
    payload = _input(gate_weights, pending=unit())
    assert run(payload).decision is SelectionDecision.GO


# --------------------------------------------------------------------------------------
# Purity
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pending",
    [None, unit(), unit(irreversible=True), unit(paths=("/etc/hosts",))],
)
def test_the_same_input_yields_the_same_verdict(gate_weights, pending):
    payload = _input(gate_weights, pending=pending)
    assert run(payload) == run(payload)


def test_the_input_model_is_not_mutated(gate_weights):
    payload = _input(gate_weights, pending=unit(), constraints=[_scope("src")])
    before = payload.model_dump(mode="json")
    run(payload)
    assert payload.model_dump(mode="json") == before


def test_it_raises_no_interrupt_of_its_own(gate_weights):
    assert run(_input(gate_weights, pending=unit(irreversible=True))).interrupt is None


def test_the_expectation_path_key_is_the_one_the_vocabulary_names(gate_weights):
    pending = unit(paths=())
    pending.expected.append(
        Expectation(
            id="e1", kind=ExpectationKind.FILE_EXISTS, arguments={EXPECTATION_PATH: "/etc/hosts"}
        )
    )
    assert run(_input(gate_weights, pending=pending)).decision is SelectionDecision.NO_GO
