"""The router: one tier per tick from workspace signals, and the three rungs in their order.

`the build specification (not in this mirror)` § Deliverable 6 → *The seat router* (folded: A1-13) and
*The stuck ladder* (folded: Ruling 16 [B]).

**No threshold is written in this module either.** Every count a case needs is read from the
throwaway root's own `weights.yaml`, so a retuned seed file moves the test and the router
together and neither can drift from the other.

**Ruling 16 (b), the operator's over-firing constraint** — "make sure this isn't over-firing, we don't
want metaphorical 'over thinking' when we haven't actually reached a stuck state yet" — is what
the "one under the count" cases below are for: a rung that fired one short of its own threshold
would be exactly the over-thinking that constraint names.
"""

from __future__ import annotations

import ast
from pathlib import Path

from protean.cortex.ladder import LadderWeights
from protean.cortex.router import LadderRouter
from protean.runtime.seat import TierSelector
from protean.state.enums import (
    CallType,
    Escalation,
    GoalStatus,
    InterruptKind,
    Raiser,
    SelectionDecision,
    Tier,
    TrapDetector,
)
from protean.state.interrupts import ResolvedInterrupt
from protean.state.outputs import MonitorVerdict, SelectionVerdict
from protean.state.primitives import GoalItem, TrapScalar, WorkUnit
from protean.state.seats import ManagerPlan
from protean.state.workspace import LatestOutputs, Workspace
from tests.cortex.conftest import one_goal, one_goal_workspace, trap_scalar

UNIT = "u-stuck-1"


def _goal(**overrides) -> GoalItem:
    return one_goal("task-r-g1", **overrides)


def _plan(tick: int = 1) -> ManagerPlan:
    return ManagerPlan(
        tick=tick,
        units=[WorkUnit(id=UNIT, goal_id="task-r-g1", intent="reconcile the ledger")],
    )


def _traps(*, fired: bool, unit_id: str = UNIT) -> list[TrapScalar]:
    return [trap_scalar(TrapDetector.DISLODGING, fired=fired, unit_id=unit_id)]


def _workspace(*, tick: int = 4, goal: GoalItem | None = None, **latest) -> Workspace:
    return one_goal_workspace("task-r", tick=tick, goal=goal or _goal(), **latest)


def _quiet(**latest) -> dict:
    """The `latest` slots of a tick on which nothing has escalated."""
    base = {
        "manager": _plan(),
        "anterior_cingulate": MonitorVerdict(
            tick=3, unit_id=UNIT, match=False, failed_predicate_ids=["e-1"], streak=1,
            traps=_traps(fired=False),
        ),
    }
    base.update(latest)
    return base


# --------------------------------------------------------------------------------------
# The seam
# --------------------------------------------------------------------------------------


def test_the_router_is_the_selector_protocol_the_runtime_declared(ladder_weights):
    assert isinstance(LadderRouter(weights=ladder_weights), TierSelector)


def test_the_counts_come_from_the_two_weights_files_that_own_them(
    brain, cortex_weights, monitor_weights
):
    """Each threshold has exactly one owner (folded: S-5), and the router reads it there."""
    loaded = LadderWeights.load(brain)
    assert loaded.k_replan == int(cortex_weights["k_replan"])
    assert loaded.k_redirect == int(cortex_weights["k_redirect"])
    assert loaded.mismatch_streak == int(monitor_weights["mismatch_streak"])
    assert "rut_ticks" not in cortex_weights, "rut_ticks lives in exactly one file, not this one"


def test_the_router_answers_on_every_tick_and_records_what_it_chose(ladder_weights):
    """The two skip conditions skip the seat *call*, never the routing (folded: D5-14)."""
    router = LadderRouter(weights=ladder_weights)
    router(_workspace())
    router(_workspace(**_quiet()))
    assert [str(item.tier) for item in router.selections] == [
        str(Tier.MANAGER),
        str(Tier.MANAGER),
    ]


def test_the_router_reports_the_open_task_and_the_selection_before_the_port_is_called(
    ladder_weights,
):
    seen: list[tuple[str, str]] = []
    router = LadderRouter(
        weights=ladder_weights,
        on_tick=lambda task_id, selection: seen.append((task_id, str(selection.tier))),
    )
    router(_workspace(**_quiet()))
    assert seen == [("task-r", str(Tier.MANAGER))]


# --------------------------------------------------------------------------------------
# The rules, in their order
# --------------------------------------------------------------------------------------


def test_an_empty_unit_stack_goes_to_the_planner_naming_no_unit(ladder_weights):
    selection = LadderRouter(weights=ladder_weights).select(_workspace())
    assert selection.tier is Tier.MANAGER
    assert selection.escalation is Escalation.EMPTY_UNIT_STACK
    assert selection.unit_id is None


def test_a_plan_that_emitted_no_unit_is_also_an_empty_stack(ladder_weights):
    selection = LadderRouter(weights=ladder_weights).select(
        _workspace(manager=ManagerPlan(tick=1))
    )
    assert selection.tier is Tier.MANAGER


def test_a_passed_unit_goes_back_to_the_planner_naming_the_unit_it_passed(ladder_weights):
    """The workspace carries no unit stack; a matching verdict is its signal for "nothing left"."""
    selection = LadderRouter(weights=ladder_weights).select(
        _workspace(
            manager=_plan(),
            anterior_cingulate=MonitorVerdict(
                tick=3, unit_id=UNIT, match=True, traps=_traps(fired=False)
            ),
        )
    )
    assert selection.tier is Tier.MANAGER
    assert selection.escalation is Escalation.EMPTY_UNIT_STACK
    assert selection.unit_id == UNIT


def test_a_matching_verdict_about_no_unit_is_not_a_pass(ladder_weights):
    """A planner or director tick grades no unit; its verdict must not be read as progress."""
    selection = LadderRouter(weights=ladder_weights).select(
        _workspace(
            manager=_plan(),
            anterior_cingulate=MonitorVerdict(
                tick=3, unit_id=None, match=True, traps=_traps(fired=False)
            ),
        )
    )
    assert selection.tier is Tier.MANAGER


def test_nothing_escalated_goes_to_the_manager_and_leaves_the_unit_to_the_runtime(
    ladder_weights,
):
    selection = LadderRouter(weights=ladder_weights).select(_workspace(**_quiet()))
    assert selection.tier is Tier.MANAGER and selection.unit_id is None


def test_rung_one_a_fired_trap_hands_the_unit_to_the_planner_with_its_evidence(
    ladder_weights,
):
    """A signal is never a stop: the first rung is always the planner, a judgment seat."""
    selection = LadderRouter(weights=ladder_weights).select(
        _workspace(
            manager=_plan(),
            anterior_cingulate=MonitorVerdict(
                tick=3, unit_id=None, match=False, traps=_traps(fired=True)
            ),
        )
    )
    assert selection.tier is Tier.MANAGER
    assert selection.escalation is Escalation.TRAP_SIGNAL
    assert selection.unit_id == UNIT, "the unit comes off the scalar, not off the verdict"
    assert [str(scalar.detector) for scalar in selection.trap_evidence] == ["dislodging"]


def test_rung_one_a_veto_hands_the_unit_to_the_planner_directly(ladder_weights):
    """Decision 29: the vetoed unit goes to the planner on the next tick, rung 1 directly."""
    selection = LadderRouter(weights=ladder_weights).select(
        _workspace(
            manager=_plan(),
            basal_ganglia=SelectionVerdict(
                tick=3,
                decision=SelectionDecision.NO_GO,
                unit_id=UNIT,
                veto_reason="irreversible with no allowance",
            ),
            anterior_cingulate=MonitorVerdict(
                tick=3, unit_id=UNIT, match=False, traps=_traps(fired=False)
            ),
        )
    )
    assert selection.tier is Tier.MANAGER and selection.escalation is Escalation.VETO
    assert selection.unit_id == UNIT


def test_rung_one_a_spent_mismatch_streak_hands_the_unit_to_the_planner(
    ladder_weights, monitor_weights
):
    streak = int(monitor_weights["mismatch_streak"])
    selection = LadderRouter(weights=ladder_weights).select(
        _workspace(
            manager=_plan(),
            anterior_cingulate=MonitorVerdict(
                tick=3, unit_id=UNIT, match=False, streak=streak, traps=_traps(fired=False)
            ),
        )
    )
    assert selection.tier is Tier.MANAGER
    assert selection.escalation is Escalation.MISMATCH_STREAK


def test_a_streak_one_under_its_threshold_does_not_escalate(ladder_weights, monitor_weights):
    """Ruling 16 (b): a rung that fired one short of its own count would be over-firing."""
    streak = int(monitor_weights["mismatch_streak"]) - 1
    selection = LadderRouter(weights=ladder_weights).select(
        _workspace(
            manager=_plan(),
            anterior_cingulate=MonitorVerdict(
                tick=3, unit_id=UNIT, match=False, streak=streak, traps=_traps(fired=False)
            ),
        )
    )
    assert selection.tier is Tier.MANAGER


def test_rung_two_spent_replans_climb_to_the_director(ladder_weights, cortex_weights):
    goal = _goal(replan_count=int(cortex_weights["k_replan"]))
    selection = LadderRouter(weights=ladder_weights).select(
        _workspace(goal=goal, **_quiet())
    )
    assert selection.tier is Tier.DIRECTOR
    assert selection.escalation is Escalation.REPLAN_EXHAUSTED


def test_one_replan_under_the_count_stays_below_the_director(ladder_weights, cortex_weights):
    goal = _goal(replan_count=int(cortex_weights["k_replan"]) - 1)
    selection = LadderRouter(weights=ladder_weights).select(
        _workspace(goal=goal, **_quiet())
    )
    assert selection.tier is not Tier.DIRECTOR


def test_rung_three_spent_redirects_keep_the_tick_with_the_director(
    ladder_weights, cortex_weights
):
    """A spent ladder must not un-climb itself back to the act while the window is still open."""
    goal = _goal(
        replan_count=int(cortex_weights["k_replan"]),
        redirect_count=int(cortex_weights["k_redirect"]),
    )
    selection = LadderRouter(weights=ladder_weights).select(
        _workspace(goal=goal, **_quiet())
    )
    assert selection.tier is Tier.DIRECTOR
    assert selection.escalation is Escalation.REDIRECT_EXHAUSTED


def test_rung_three_outranks_rung_two_and_both_outrank_rung_one(
    ladder_weights, cortex_weights
):
    goal = _goal(
        replan_count=int(cortex_weights["k_replan"]),
        redirect_count=int(cortex_weights["k_redirect"]),
    )
    with_traps = _workspace(
        goal=goal,
        manager=_plan(),
        anterior_cingulate=MonitorVerdict(
            tick=3, unit_id=UNIT, match=False, traps=_traps(fired=True)
        ),
    )
    assert LadderRouter(weights=ladder_weights).select(with_traps).escalation is (
        Escalation.REDIRECT_EXHAUSTED
    )


def test_a_stuck_answer_that_landed_this_tick_outranks_every_rung(
    ladder_weights, cortex_weights
):
    """The answer's landing place is what lets it change what the brain does next."""
    goal = _goal(redirect_count=int(cortex_weights["k_redirect"]))
    workspace = _workspace(tick=10, goal=goal, **_quiet())
    workspace = workspace.model_copy(
        update={
            "resolved_interrupts": [
                ResolvedInterrupt(
                    id="task-r-t9-runtime",
                    kind=InterruptKind.STUCK,
                    raised_by=Raiser.RUNTIME,
                    raised_at_tick=9,
                    resolved_at_tick=10,
                    question="how should it proceed?",
                    answer="treat the statement as authoritative",
                )
            ]
        }
    )
    selection = LadderRouter(weights=ladder_weights).select(workspace)
    assert selection.tier is Tier.MANAGER
    assert selection.escalation is Escalation.REDIRECT_EXHAUSTED


def test_an_answer_resolved_on_an_earlier_tick_no_longer_routes(
    ladder_weights, cortex_weights
):
    """The signal is true exactly once; a run does not re-route on an answer it already acted on."""
    goal = _goal(redirect_count=int(cortex_weights["k_redirect"]))
    workspace = _workspace(tick=12, goal=goal, **_quiet()).model_copy(
        update={
            "resolved_interrupts": [
                ResolvedInterrupt(
                    id="task-r-t9-runtime",
                    kind=InterruptKind.STUCK,
                    raised_by=Raiser.RUNTIME,
                    raised_at_tick=9,
                    resolved_at_tick=10,
                    question="how should it proceed?",
                    answer="treat the statement as authoritative",
                )
            ]
        }
    )
    selection = LadderRouter(weights=ladder_weights).select(workspace)
    assert selection.tier is Tier.DIRECTOR


# --------------------------------------------------------------------------------------
# M17's literal clause, as a property of the source
# --------------------------------------------------------------------------------------


PACKAGE = Path(__file__).resolve().parents[2] / "src" / "protean" / "cortex"


def _code_constants(source: str) -> tuple[set[float], set[str]]:
    """Every numeric and string constant in a module, excluding its docstrings."""
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    numbers: set[float] = set()
    strings: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or id(node) in docstrings:
            continue
        if isinstance(node.value, bool):
            continue
        if isinstance(node.value, (int, float)):
            numbers.add(float(node.value))
        elif isinstance(node.value, str):
            strings.add(node.value)
    return numbers, strings


def test_no_threshold_or_ladder_count_literal_exists_in_the_cortex_package(
    cortex_weights, monitor_weights
):
    """M17's static half: the numbers live in the weights files, and only there."""
    owned = {**cortex_weights, **monitor_weights}
    #: Constants that carry no threshold meaning: an index, an empty default, a unit step — the
    #: same exclusion `tests/nodes/test_purity.py` carries; A.1 seeds `firing_threshold` at 0.0.
    trivial = {0, 1}
    # A.2.i's trigger key ships off as `null`; skip non-numeric values as `test_purity.py` does (E33).
    owned_values = {
        float(value)
        for value in owned.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    } - {float(t) for t in trivial}
    for path in sorted(PACKAGE.glob("*.py")):
        numbers, strings = _code_constants(path.read_text(encoding="utf-8"))
        assert numbers.isdisjoint(owned_values), f"{path} holds a threshold value"
        assert strings.isdisjoint(set(owned)), f"{path} holds a weights key as a literal"
