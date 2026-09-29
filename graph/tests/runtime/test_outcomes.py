"""Outcome derivation — the runtime's job, mechanically, at the boundary.

`the build specification (not in this mirror)` § Deliverable 3 → *Outcomes are the runtime's job,
mechanically*: "No node grades itself and none reads a trace file. At each boundary the runtime
takes the previous tick's prediction records, reads the observable Deliverable 4's table names
for that node, and appends one `outcome` record with `source: runtime_grade` and `ref` set to
the prediction's key."

Builder-verified row M9: **one scenario per node and per cortex tier in which the observable is
forced both ways and the recorded `outcome` follows it.** Every assertion reads the outcome back
off the committed `trace.jsonl` rather than off `TickResult`, because the row is about what the
boundary appended.

`cited_ids` is what grades the thalamus's and the hippocampus's predictions, so the citation
scenarios drive a seat that cites and one that does not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from protean import config
from protean.brain.jsonl import read_lines
from protean.runtime.cycle import run_tick
from protean.runtime.engine import build_context, new_state
from protean.state.enums import CallType, Escalation, ExpectationKind, Tier
from protean.state.primitives import Expectation, WorkUnit, WorkspaceObservation
from protean.state.seats import ExecutorSummary, ManagerPlan, WaveMember
from tests.runtime import stubs
from tests.runtime.conftest import EXPECTATION_ID, REPO_ROOT, UNIT_ID

TARGET = "out.txt"


def _outcomes(brain: Path, node: str) -> list[dict[str, Any]]:
    path = config.node_dir(node, brain) / "trace.jsonl"
    return [record for record in read_lines(path) if record["kind"] == "outcome"]


def _graded(brain: Path, node: str, tick: int, tier: Tier | None = None) -> dict[str, Any]:
    """The outcome record grading the prediction this folder made on `tick`."""
    key = f":{tick}:{node}:{tier if tier is not None else '-'}:prediction"
    matches = [record for record in _outcomes(brain, node) if record["ref"].endswith(key)]
    assert len(matches) == 1, f"{node}@{tick}: {[m['ref'] for m in matches]}"
    return matches[0]


def _drive(
    brain: Path,
    workspace: Path,
    task_id: str,
    *,
    rule,
    responders: dict[str, Callable],
    ticks: int,
    between=None,
) -> tuple[Any, Any, list, stubs.StubSeat]:
    seat = stubs.StubSeat(responder=stubs.member_keyed(responders))
    router = stubs.StubRouter(rule=rule)
    context = build_context(
        brain, task_id, stubs.layer(router, seat), workspace_path=str(workspace)
    )
    state = new_state(task_id, "grade me", context)
    results = []
    for _ in range(ticks):
        state.tick += 1
        if between is not None:
            between(state.tick, seat)
        results.append(run_tick(context, state))
    return context, state, results, seat


def _unit(request, *, target: str = TARGET) -> WorkUnit:
    return WorkUnit(
        id=UNIT_ID,
        goal_id=request.workspace.goals[0].id,
        intent="write the file",
        expected=[
            Expectation(
                id=EXPECTATION_ID,
                kind=ExpectationKind.FILE_EXISTS,
                arguments={"path": target},
            )
        ],
    )


#: The subagent kind the wave's one member asks for. **Re-based by build A.1**: the act is a
#: manager dispatch rather than a seat, so the acting pass is a `ManagerPlan` carrying a wave and
#: the return arrives on the `dispatch` addressee (§ Deliverable 3).
KIND = "writer"


def _planner(request) -> ManagerPlan:
    """Plan the unit, and dispatch its wave on every pass that already names one.

    The opening pass has no unit to dispatch for, so it carries no wave — exactly the two-phase
    shape build 1's planner/executor pair had, with the act moved onto the manager's own plan.
    """
    wave = (
        [WaveMember(kind=KIND, unit_id=UNIT_ID, admitted_ref="admitted")]
        if request.unit_id
        else []
    )
    return ManagerPlan(tick=request.workspace.tick, units=[_unit(request)], wave=wave)


def _passing_executor(member) -> ExecutorSummary:
    """One wave member's return. The member request carries no path and no tick: the workspace
    is the runtime's to fill and the decoder stamps the tick over whatever a responder wrote."""
    return ExecutorSummary(
        tick=0,
        unit_id=member.unit_id,
        narrative="wrote it",
        observations=[
            WorkspaceObservation(path=TARGET, exists=True, size_bytes=11, content_hash="h1")
        ],
    )


def _failing_executor(member) -> ExecutorSummary:
    return ExecutorSummary(tick=0, unit_id=member.unit_id, narrative="did nothing")


def _director(request) -> dict[str, Any]:
    return {"tick": request.workspace.tick}


def _plan_then_execute(executor):
    return {
        str(Tier.MANAGER): _planner,
        str(CallType.DISPATCH): executor,
        str(Tier.DIRECTOR): _director,
    }


# --------------------------------------------------------------------------------------
# Homeostasis — "the next tick's cost in its own units"
# --------------------------------------------------------------------------------------


def test_homeostasis_mismatches_when_the_spend_moves(brain: Path, workspace: Path):
    def _spend(tick: int, seat: stubs.StubSeat) -> None:
        seat.tokens_per_call = 0 if tick == 1 else 40

    _drive(
        brain, workspace, "task-h2",
        rule=stubs.manager_then_dispatch(UNIT_ID),
        responders=_plan_then_execute(_passing_executor),
        ticks=3,
        between=_spend,
    )
    record = _graded(brain, "homeostasis", 1)
    # **Two calls, not one** (`the build specification (not in this mirror)` § Deliverable 7, row G8):
    # the graded tick makes the manager's seat call and dispatches one wave member, and A.1
    # counts every call in the tick rather than the seat's envelope alone. The landed `40` was
    # the N−1 under-count this row exists to close.
    assert record["outcome"]["observed_tokens"] == 80
    assert record["outcome"]["matched"] is False


# --------------------------------------------------------------------------------------
# Hippocampus and thalamus — `cited_ids` is the observable
# --------------------------------------------------------------------------------------


def _citing_planner(field: str):
    """A planner that cites what it was given, keyed by which id the grader intersects on."""

    def _respond(request) -> ManagerPlan:
        admitted = request.workspace.admitted
        cited = [getattr(item, field) for item in (admitted.admitted if admitted else [])]
        return ManagerPlan(tick=request.workspace.tick, units=[_unit(request)], cited_ids=cited)

    return _respond


def _always_planner():
    return stubs.always(
        stubs.SeatSelection(tier=Tier.MANAGER, escalation=Escalation.EMPTY_UNIT_STACK)
    )


def test_the_hippocampus_matches_when_the_seat_cites_what_it_retrieved(
    brain: Path, workspace: Path
):
    _drive(
        brain, workspace, "task-r1",
        rule=_always_planner(),
        responders={
            str(Tier.MANAGER): _citing_planner("episode_id"),
            str(CallType.DISPATCH): _passing_executor,
            str(Tier.DIRECTOR): _director,
        },
        ticks=3,
    )
    record = _graded(brain, "hippocampus", 2)
    assert record["outcome"]["cited_episode_ids"] == ["task-r1:1"]
    assert record["outcome"]["matched"] is True


def test_a_seat_that_cites_the_admitted_id_matches_both_folders_that_offered_it(
    brain: Path, workspace: Path
):
    """One drive, one `_graded` block per node: the hippocampus's and the thalamus's grades are
    two readings of the *same* citing pass.

    **The hippocampus block is repair (a), on the live path**: a real seat cites
    `admitted:<episode id>`, never the bare id.
    `the build specification (not in this mirror)` § Deliverable 1 — the id-space mismatch that graded the
    `~/workload` run `matched: false` on every tick. The test above cites the bare `episode_id` and
    still passes; this one cites what the thalamus actually mints, which before the repair
    intersected with nothing.
    """
    _drive(
        brain, workspace, "task-r3",
        rule=_always_planner(),
        responders={
            str(Tier.MANAGER): _citing_planner("admitted_id"),
            str(CallType.DISPATCH): _passing_executor,
            str(Tier.DIRECTOR): _director,
        },
        ticks=3,
    )

    # The hippocampus retrieved it.
    retrieval = _graded(brain, "hippocampus", 2)
    assert retrieval["outcome"]["cited_episode_ids"] == ["task-r3:1"]
    assert retrieval["outcome"]["matched"] is True

    # The thalamus admitted it, and the id the seat cited is the one it minted.
    admission = _graded(brain, "thalamus", 2)
    assert admission["outcome"]["cited_admitted_ids"] == ["admitted:task-r3:1"]
    assert admission["outcome"]["matched"] is True


def test_a_seat_that_cites_nothing_mismatches_both_folders_that_offered_it(
    brain: Path, workspace: Path
):
    """The negative control of the pair above, and the same two readings of one pass."""
    _drive(
        brain, workspace, "task-r2",
        rule=_always_planner(),
        responders={
            str(Tier.MANAGER): _planner,
            str(CallType.DISPATCH): _passing_executor,
            str(Tier.DIRECTOR): _director,
        },
        ticks=3,
    )

    retrieval = _graded(brain, "hippocampus", 2)
    assert retrieval["outcome"]["cited_episode_ids"] == []
    assert retrieval["outcome"]["matched"] is False

    admission = _graded(brain, "thalamus", 2)
    assert admission["outcome"]["cited_admitted_ids"] == []
    assert admission["outcome"]["matched"] is False


# --------------------------------------------------------------------------------------
# The gate — "the unit it let through will not be abandoned or trap-flagged this tick"
# --------------------------------------------------------------------------------------


def test_the_gate_matches_until_a_trap_flags_the_unit_and_mismatches_after(
    brain: Path, workspace: Path
):
    """One drive, two readings: the gate's grade before the trap fires and after it.

    The two were two drives of the same five failing ticks, read at tick 2 and tick 4.
    """
    _drive(
        brain, workspace, "task-g1",
        rule=stubs.manager_then_dispatch(UNIT_ID),
        responders=_plan_then_execute(_failing_executor),
        ticks=5,
    )

    # Early: no trap has flagged the unit the gate let through.
    early = _graded(brain, "basal_ganglia", 2)
    assert early["outcome"]["trap_flagged"] is False
    assert early["outcome"]["abandoned"] is False
    assert early["outcome"]["matched"] is True

    # Late: `rut_ticks` consecutive identical failures with no change volume — the seed's own
    # number — and the prediction the gate made on that tick is a mismatch.
    late = _graded(brain, "basal_ganglia", 4)
    assert late["outcome"]["trap_flagged"] is True
    assert late["outcome"]["matched"] is False


def test_a_gate_with_no_pending_unit_skips_and_writes_no_ordinary_prediction(
    brain: Path, workspace: Path
):
    """Re-based by build A.1 (§ Deliverable 1, ruling D15-5): a tick with no pending unit is the
    `NO_SUBJECT` case, and the gate **skips** it — no ordinary prediction is minted, so there is
    nothing for the sentinel grade to read, and "skipping there deletes nothing that was ever
    graded". The skip itself is recorded as a `FiringDecision` on the gate's `call# = 0` entry."""
    _drive(
        brain, workspace, "task-g3",
        rule=_always_planner(),
        responders={
            str(Tier.MANAGER): lambda request: ManagerPlan(tick=request.workspace.tick),
            str(CallType.DISPATCH): _passing_executor,
            str(Tier.DIRECTOR): _director,
        },
        ticks=3,
    )
    predictions = [
        record
        for record in read_lines(config.node_dir("basal_ganglia", brain) / "trace.jsonl")
        if record["kind"] == "prediction"
    ]
    assert [record for record in predictions if record["source"] == "node"] == []
    outcomes = [
        record
        for record in read_lines(config.node_dir("basal_ganglia", brain) / "trace.jsonl")
        if record["kind"] == "outcome" and record["source"] == "runtime_grade"
    ]
    assert outcomes == [], "no ordinary prediction, so no ordinary grade — the skip's own pair is W7's"


# --------------------------------------------------------------------------------------
# The monitor — "the next tick's verdict, repeat or clear"
# --------------------------------------------------------------------------------------


def test_the_monitor_matches_when_the_verdict_repeats(brain: Path, workspace: Path):
    _drive(
        brain, workspace, "task-m1",
        rule=stubs.manager_then_dispatch(UNIT_ID),
        responders=_plan_then_execute(_failing_executor),
        ticks=4,
    )
    record = _graded(brain, "anterior_cingulate", 2)
    assert record["outcome"]["observed_match"] is False
    assert record["outcome"]["matched"] is True


def test_the_monitor_mismatches_when_the_verdict_clears(brain: Path, workspace: Path):
    # **Re-based by build A.1**: a `WaveMember` carries no tick — the workspace and the tick are
    # the runtime's to fill, and the decoder stamps the tick over whatever a responder wrote —
    # so the pass the work lands on is driven from the loop rather than read off the request.
    cleared = {"now": False}

    def _executor(member) -> ExecutorSummary:
        return _passing_executor(member) if cleared["now"] else _failing_executor(member)

    _drive(
        brain, workspace, "task-m2",
        rule=stubs.manager_then_dispatch(UNIT_ID),
        responders=_plan_then_execute(_executor),
        ticks=4,
        between=lambda tick, _seat: cleared.update(now=tick > 2),
    )
    record = _graded(brain, "anterior_cingulate", 2)
    assert record["outcome"]["observed_match"] is True
    assert record["outcome"]["matched"] is False


# --------------------------------------------------------------------------------------
# The cortex, tier by tier
# --------------------------------------------------------------------------------------


def test_the_executor_tier_mismatches_when_its_unit_fails(brain: Path, workspace: Path):
    _drive(
        brain, workspace, "task-e2",
        rule=stubs.manager_then_dispatch(UNIT_ID),
        responders=_plan_then_execute(_failing_executor),
        ticks=3,
    )
    record = _graded(brain, config.CORTEX_NODE, 2, CallType.DISPATCH)
    assert record["outcome"]["verdict_match"] is False
    assert record["outcome"]["failed_predicate_ids"] == [EXPECTATION_ID]
    assert record["outcome"]["matched"] is False


def _shorten(brain: Path, **keys: int) -> None:
    """Retune the cortex ladder counts on the throwaway root — the horizons are weights keys."""
    stubs.set_weight(brain, config.CORTEX_NODE, **keys)


def test_the_planner_tier_matches_when_its_unit_passes_inside_the_horizon(
    brain: Path, workspace: Path
):
    _shorten(brain, manager_horizon=2)
    _drive(
        brain, workspace, "task-p1",
        rule=stubs.manager_then_dispatch(UNIT_ID),
        responders=_plan_then_execute(_passing_executor),
        ticks=4,
    )
    record = _graded(brain, config.CORTEX_NODE, 1, Tier.MANAGER)
    assert record["scored_at_tick"] == 3, "graded where the horizon closes, not at the next tick"
    assert record["outcome"]["passed_within_horizon"] is True
    assert record["outcome"]["matched"] is True


def test_the_planner_tier_mismatches_when_the_horizon_closes_unpassed(
    brain: Path, workspace: Path
):
    _shorten(brain, manager_horizon=2)
    _drive(
        brain, workspace, "task-p2",
        rule=stubs.manager_then_dispatch(UNIT_ID),
        responders=_plan_then_execute(_failing_executor),
        ticks=4,
    )
    record = _graded(brain, config.CORTEX_NODE, 1, Tier.MANAGER)
    assert record["outcome"]["passed_within_horizon"] is False
    assert record["outcome"]["matched"] is False


def test_a_planner_prediction_is_not_graded_before_its_horizon_closes(
    brain: Path, workspace: Path
):
    _shorten(brain, manager_horizon=6)
    _drive(
        brain, workspace, "task-p3",
        rule=stubs.manager_then_dispatch(UNIT_ID),
        responders=_plan_then_execute(_passing_executor),
        ticks=3,
    )
    refs = [record["ref"] for record in _outcomes(brain, config.CORTEX_NODE)]
    assert not any(ref.endswith(f":1:{config.CORTEX_NODE}:{Tier.MANAGER}:prediction") for ref in refs)


def _director_then_work(unit_id: str):
    """Direct on the first pass, then plan, then act — the shape the director's window is
    graded on.

    **Re-based by build A.1**: the acting pass is the **manager's**, naming the unit it
    dispatches for; tier three is not a seat and a router cannot select it (§ Deliverable 3).
    """

    def _rule(workspace):
        if workspace.latest.director is None:
            return stubs.SeatSelection(tier=Tier.DIRECTOR)
        if workspace.latest.manager is None:
            return stubs.SeatSelection(
                tier=Tier.MANAGER, escalation=Escalation.EMPTY_UNIT_STACK
            )
        return stubs.SeatSelection(tier=Tier.MANAGER, unit_id=unit_id)

    return _rule


def test_the_director_tier_matches_when_progress_lands_inside_the_window(
    brain: Path, workspace: Path
):
    _shorten(brain, progress_window=3)
    _drive(
        brain, workspace, "task-d1",
        rule=_director_then_work(UNIT_ID),
        responders=_plan_then_execute(_passing_executor),
        ticks=5,
    )
    record = _graded(brain, config.CORTEX_NODE, 1, Tier.DIRECTOR)
    assert record["scored_at_tick"] == 4
    assert record["outcome"]["progress_observed"] is True
    assert record["outcome"]["matched"] is True


def test_the_director_tier_mismatches_when_the_window_closes_without_progress(
    brain: Path, workspace: Path
):
    _shorten(brain, progress_window=3)
    _drive(
        brain, workspace, "task-d2",
        rule=_director_then_work(UNIT_ID),
        responders=_plan_then_execute(_failing_executor),
        ticks=5,
    )
    record = _graded(brain, config.CORTEX_NODE, 1, Tier.DIRECTOR)
    assert record["outcome"]["progress_observed"] is False
    assert record["outcome"]["matched"] is False


# --------------------------------------------------------------------------------------
# The shape of every derived record
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def shape_drive(tmp_path_factory) -> Path:
    """One four-tick passing drive for the module — the shape claim is node-independent.

    The claim below is graded per node off the same six traces, and the drive that writes them
    names no node: it was re-run, with a fresh `seed_brain`, once per parametrized node. Nothing
    reads it but the parametrized case, and that case only reads.
    """
    base = tmp_path_factory.mktemp("shape")
    brain = stubs.seed_brain(REPO_ROOT / "brain", base / "brain")
    workspace = base / "workspace"
    workspace.mkdir()
    _drive(
        brain, workspace, "task-shape",
        rule=stubs.manager_then_dispatch(UNIT_ID),
        responders=_plan_then_execute(_passing_executor),
        ticks=4,
    )
    return brain


@pytest.mark.parametrize("node", list(config.NODE_ORDER))
def test_every_outcome_is_a_runtime_grade_referring_to_a_committed_prediction(
    shape_drive: Path, node: str
):
    brain = shape_drive
    records = read_lines(config.node_dir(node, brain) / "trace.jsonl")
    predictions = {
        record["ref"] if record["kind"] == "outcome" else None for record in records
    } - {None}
    keys = {
        f"{record['task']}:{record['tick']}:{record['node']}:"
        f"{record['tier'] or '-'}:prediction"
        # A.1 § Deliverable 1: a firing prediction's key takes the `:firing` suffix, and only
        # a firing prediction's (folded: S-A83).
        + (":firing" if record["source"] == "firing" else "")
        for record in records
        if record["kind"] == "prediction"
    }
    assert predictions <= keys, node
    for record in records:
        if record["kind"] != "outcome":
            continue
        # `runtime_grade` grades a node's own prediction; `firing_grade` grades its skip (A.1).
        assert record["source"] in ("runtime_grade", "firing_grade")
        assert record["scored_at_tick"] == record["tick"]
        assert record["prediction"] is None


def test_a_prediction_is_graded_once(brain: Path, workspace: Path):
    """The deferred grader skips a `ref` an outcome already claims."""
    _drive(
        brain, workspace, "task-once",
        rule=stubs.manager_then_dispatch(UNIT_ID),
        responders=_plan_then_execute(_passing_executor),
        ticks=5,
    )
    for node in config.NODE_ORDER:
        refs = [record["ref"] for record in _outcomes(brain, node)]
        assert len(refs) == len(set(refs)), node


def test_one_passing_drive_grades_the_spend_the_dispatch_tier_and_nothing_by_its_own_source(
    brain: Path, workspace: Path
):
    """Three readings of **one** passing three-tick drive, one `_graded` block per node.

    * **homeostasis** matches when the next tick's spend repeats — the grade is the runtime's,
      scored on the following tick, in the node's own units;
    * **the dispatch tier of the cortex** matches when the unit it acted on passes; and
    * **no node grades itself**: every outcome is the runtime's grade — `runtime_grade` for a
      node's own prediction, `firing_grade` for its skip (A.1) — never a node's own source,
      `node` or `firing`.

    The three were three drives of the same scenario, read at three places in the same traces.
    """
    _drive(
        brain, workspace, "task-h1",
        rule=stubs.manager_then_dispatch(UNIT_ID),
        responders=_plan_then_execute(_passing_executor),
        ticks=3,
    )

    spend = _graded(brain, "homeostasis", 1)
    assert spend["source"] == "runtime_grade"
    assert spend["scored_at_tick"] == 2
    assert spend["outcome"]["observed_tokens"] == 0
    assert spend["outcome"]["matched"] is True

    dispatched = _graded(brain, config.CORTEX_NODE, 2, CallType.DISPATCH)
    assert dispatched["tier"] == str(CallType.DISPATCH)
    assert dispatched["outcome"]["verdict_match"] is True
    assert dispatched["outcome"]["matched"] is True

    for node in config.NODE_ORDER:
        assert {record["source"] for record in _outcomes(brain, node)} <= {
            "runtime_grade",
            "firing_grade",
        }
