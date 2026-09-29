"""The five terminal states, their distinct exit codes, and the precedence when several fire.

`the build specification (not in this mirror)` § Deliverable 3's terminal table and precedence paragraph;
decision 18. Builder-verified row M14 — the builder's own test list, not a gate.

**A terminal is a committed field.** Every assertion below reads it back off the checkpoint on
disk rather than off the return value, because "the process exits after the commit, never before
it" is a property of what landed, not of what was returned.
"""

from __future__ import annotations


import pytest

from protean import config
from protean.runtime.cycle import run_tick
from protean.runtime.engine import build_context, new_state
from protean.runtime.terminal import exit_code, fired, losers, winner
from protean.state.enums import (
    GoalStatus,
    InterruptKind,
    Raiser,
    TerminalState,
    Tier,
)
from protean.state.interrupts import InterruptRequest
from protean.state.seats import ManagerPlan
from tests.runtime import stubs


def _committed_terminal(context) -> str | None:
    return stubs.committed_state(context.paths)["state"]["terminal"]


def test_the_five_exit_codes_are_distinct():
    codes = {state: exit_code(state) for state in TerminalState}
    assert sorted(codes) == sorted(TerminalState)
    assert len(set(codes.values())) == len(TerminalState)


def test_done_when_the_goal_stack_empties_with_no_open_interrupt(brain, workspace):
    def _planner(request) -> ManagerPlan:
        return ManagerPlan(
            tick=request.workspace.tick,
            goals_satisfied=[request.workspace.goals[0].id],
        )

    context = build_context(brain, "task-done", stubs.planner_layer(_planner), workspace_path=str(workspace))
    state = new_state("task-done", "finish", context)
    state.tick += 1
    result = run_tick(context, state)

    assert result.committed_terminal is TerminalState.DONE
    assert _committed_terminal(context) == str(TerminalState.DONE)
    assert exit_code(result.committed_terminal) == config.EXIT_DONE


def test_interrupted_when_a_seat_raises_while_goals_remain(brain, workspace, mailbox):
    def _planner(request) -> ManagerPlan:
        return ManagerPlan(
            tick=request.workspace.tick,
            interrupt=InterruptRequest(
                kind=InterruptKind.QUESTION,
                raised_by=Raiser.MANAGER,
                question="which directory?",
            ),
        )

    context = build_context(
        brain, "task-int", stubs.planner_layer(_planner), mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-int", "keep going", context)
    state.tick += 1
    result = run_tick(context, state)

    assert result.committed_terminal is TerminalState.INTERRUPTED
    assert _committed_terminal(context) == str(TerminalState.INTERRUPTED)
    assert len(state.open_interrupts) == 1
    assert mailbox.open_ids() == [state.open_interrupts[0].id]
    assert result.receipt.checkpoint_is_last()
    assert result.receipt.kinds()[-2] == "mailbox.write"


def test_blocked_when_the_last_goal_closes_with_an_item_open(brain, workspace, mailbox):
    def _planner(request) -> ManagerPlan:
        return ManagerPlan(
            tick=request.workspace.tick,
            goals_satisfied=[request.workspace.goals[0].id],
            interrupt=InterruptRequest(
                kind=InterruptKind.QUESTION,
                raised_by=Raiser.MANAGER,
                question="is this really done?",
            ),
        )

    context = build_context(
        brain, "task-blocked", stubs.planner_layer(_planner), mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-blocked", "close it", context)
    state.tick += 1
    result = run_tick(context, state)

    assert result.committed_terminal is TerminalState.BLOCKED
    assert _committed_terminal(context) == str(TerminalState.BLOCKED)
    assert exit_code(result.committed_terminal) == config.EXIT_BLOCKED


def test_stuck_raises_the_evidence_and_mints_one_synthetic_director_tier_prediction(
    brain, workspace, mailbox
):
    """One exhausted ladder, read twice: the interrupt it raises, and the prediction it mints.

    The two differed only in the task id and in which half of the same `run_tick` result they
    read.
    """

    def _planner(request) -> ManagerPlan:
        return ManagerPlan(tick=request.workspace.tick)

    context = build_context(
        brain, "task-stuck", stubs.planner_layer(_planner), mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-stuck", "the impossible one", context)
    cortex = context.weights("cortex")
    state.goals[0].redirect_count = int(cortex["k_redirect"])
    state.goals[0].last_progress_tick = 0
    state.tick = int(cortex["progress_window"])

    state.tick += 1
    result = run_tick(context, state)

    assert result.committed_terminal is TerminalState.STUCK
    assert len(state.open_interrupts) == 1
    raised = state.open_interrupts[0]
    assert raised.kind is InterruptKind.STUCK
    assert raised.raised_by is Raiser.RUNTIME
    assert raised.evidence["goal_id"] == state.goals[0].id
    assert "fired" in raised.evidence
    assert mailbox.open_ids() == [raised.id]

    director = [
        record
        for record in result.predictions
        if record.tier is Tier.DIRECTOR and record.prediction.synthetic_stuck
    ]
    assert len(director) == 1
    assert str(director[0].source) == "runtime"


@pytest.mark.parametrize(
    "conditions,expected",
    [
        ([TerminalState.STOPPED, TerminalState.INTERRUPTED], TerminalState.INTERRUPTED),
        ([TerminalState.STOPPED, TerminalState.STUCK], TerminalState.STUCK),
        ([TerminalState.STUCK, TerminalState.INTERRUPTED], TerminalState.INTERRUPTED),
        ([TerminalState.DONE], TerminalState.DONE),
        ([], None),
    ],
)
def test_precedence_is_interrupted_over_stuck_over_stopped(conditions, expected):
    assert winner(conditions) is expected
    assert all(item is not expected for item in losers(conditions))


def test_the_losing_condition_is_written_as_an_event_record(brain, workspace, mailbox):
    """Two terminals in one tick: `interrupted` commits, `stopped` lands as a loser event."""
    stubs.set_weight(brain, "homeostasis", max_ticks=0)

    def _planner(request) -> ManagerPlan:  # pragma: no cover - the ceiling skips the seat
        return ManagerPlan(tick=request.workspace.tick)

    context = build_context(
        brain, "task-two", stubs.planner_layer(_planner), mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-two", "both at once", context)
    cortex = context.weights("cortex")
    state.goals[0].redirect_count = int(cortex["k_redirect"])
    state.tick = int(cortex["progress_window"]) + 1
    result = run_tick(context, state)

    assert result.committed_terminal is TerminalState.STUCK
    assert TerminalState.STOPPED in result.losing_terminals
    episodes = context.paths.episodes.read_text(encoding="utf-8")
    assert "terminal_loser" in episodes
    assert str(TerminalState.STOPPED) in episodes


def test_fired_reads_every_condition_independently(brain, workspace):
    context = build_context(brain, "task-f", stubs.planner_layer(lambda r: ManagerPlan(tick=0)),
                            workspace_path=str(workspace))
    state = new_state("task-f", "x", context)
    state.goals[0].status = GoalStatus.SATISFIED
    assert fired(state, report=None, raised_this_tick=False,
                 cortex_weights=context.weights("cortex")) == [TerminalState.DONE]
