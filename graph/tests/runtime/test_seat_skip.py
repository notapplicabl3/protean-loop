"""The two conditions that skip the seat call, and neither shortens the tick.

`the build specification (not in this mirror)` § Deliverable 3 → *Two conditions skip the seat call*: the
gate's `no_go`, which inhibits the **executor** only, and a mid-tick terminal — homeostasis's
ceiling — detected mid-tick and committed at the boundary. Builder-verified rows M15 and part
of M14; not a gate row, kept because the behaviour is the veto's whole meaning.

The ceiling condition is asserted at the scripted layer instead, by
`test_call_cost.py::test_a_crossed_ceiling_suppresses_every_further_call_and_the_nodes_still_run`;
this module keeps the gate's veto.
"""

from __future__ import annotations

from protean import config
from protean.runtime.cycle import run_tick
from protean.runtime.engine import build_context, new_state
from protean.runtime.journal import load
from protean.state.enums import (
    CallType,
    Escalation,
    ExpectationKind,
    SelectionDecision,
    Tier,
)
from protean.state.primitives import Expectation, WorkUnit
from protean.state.seats import ExecutorSummary, ManagerPlan
from tests.runtime import stubs
from tests.runtime.conftest import EXPECTATION_ID, UNIT_ID


def _irreversible_layer(workspace):
    def _planner(request) -> ManagerPlan:
        return ManagerPlan(
            tick=request.workspace.tick,
            units=[
                WorkUnit(
                    id=UNIT_ID,
                    goal_id=request.workspace.goals[0].id,
                    intent="delete the tree",
                    irreversible=True,
                    expected=[
                        Expectation(
                            id=EXPECTATION_ID,
                            kind=ExpectationKind.FILE_ABSENT,
                            arguments={"path": "out.txt"},
                        )
                    ],
                )
            ],
        )

    def _executor(request) -> ExecutorSummary:  # pragma: no cover - the veto prevents this
        raise AssertionError("a vetoed tick must not invoke the executor")

    seat = stubs.StubSeat(
        responder=stubs.request_keyed(
            {
                str(Tier.MANAGER): _planner,
                str(CallType.DISPATCH): _executor,
                str(Tier.DIRECTOR): lambda request: {"tick": request.workspace.tick},
            }
        )
    )
    router = stubs.StubRouter(rule=stubs.manager_then_dispatch(UNIT_ID))
    return stubs.layer(router, seat), router, seat


def test_a_veto_skips_the_executor_records_itself_and_never_inhibits_the_planner(
    brain, workspace
):
    """Row M15 and part of M14, off **one** two-tick drive of the irreversible unit.

    The three claims were three drives of the same scenario, and they read it in tick order:

    * **tick 1** — the planner is never inhibited by the gate: rung 1 is reachable, and the
      selection that put it there is the empty unit stack. The veto inhibits the *act*, not the
      judgment seats;
    * **tick 2** — the gate vetoes the unit, so the seat call is skipped and only the planner
      tick called the seat, while the tick still completes: every node writes its entry, the
      journal on disk carries them all, and the checkpoint is the last thing written; and
    * **the observation** the vetoed tick records — one window row, `vetoed`, the predicate it
      failed, and no change volume.
    """
    seat_layer, router, seat = _irreversible_layer(workspace)
    context = build_context(
        brain, "task-veto", seat_layer, workspace_path=str(workspace)
    )
    state = new_state("task-veto", "delete the tree", context)

    state.tick += 1
    run_tick(context, state)          # the planner mints the irreversible unit

    assert router.selections[0].tier is Tier.MANAGER
    assert router.selections[0].escalation is Escalation.EMPTY_UNIT_STACK

    state.tick += 1
    result = run_tick(context, state)  # the gate vetoes it

    assert state.latest.basal_ganglia.decision is SelectionDecision.NO_GO
    assert result.seat_skipped is True
    assert len(seat.calls) == 1, "only the planner tick called the seat"
    assert result.journal_entries == len(config.NODE_ORDER)
    assert len(load(context.paths.journal(state.tick))) == len(config.NODE_ORDER)
    assert result.receipt.checkpoint_is_last()

    window = state.unit_windows[UNIT_ID]
    assert len(window) == 1
    row = window[-1]
    assert row.vetoed is True
    assert row.failed_predicate_ids == [EXPECTATION_ID]
    assert row.change_bytes_total == 0
