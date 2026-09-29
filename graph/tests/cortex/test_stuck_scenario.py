"""M16, end to end: the scripted climb unit → planner → director, and the `stuck` it commits.

`the build specification (not in this mirror)` § Deliverable 3's `stuck` terminal row, § Deliverable 6's
ladder, and § Rulings 16 [B]. The claims are on-disk ones — the escalation sequence the router
recorded, the exit code `protean.config` names, the one open mailbox file with its front matter
and evidence body, the director-tier record in the cortex folder's `trace.jsonl`, and the
post-resolution counters read back from the **checkpoint** rather than from memory.

**B10 is not closed here and cannot be.** Whether the six signals are the right signatures of
the eight traps, and whether the ladder over-fires, is judged on real work — which build 1 does
not have. What is proven below is that the ladder climbs in the shape the SPEC names, ends where
it says it ends, and hands the operator an evidence body they can rule on.

The escalation sequence and the mailbox body are printed as well as asserted, so a `-s` capture
of this module is the artifact B10's gate is handed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protean import cli, config
from protean.brain.jsonl import read_lines
from protean.cortex.ladder import escalation_names
from protean.cortex.layer import SEAT_SCRIPT_ENV
from protean.cortex.scenario import ScenarioError, load_scenario, script_path
from protean.mailbox.files import build as build_mailbox
from protean.mailbox.format import MailboxFormatError, parse
from protean.runtime import engine
from protean.runtime.paths import BrainPaths
from protean.state.enums import (
    CallType,
    Escalation,
    InterruptKind,
    NodeName,
    Raiser,
    TerminalState,
    Tier,
)

from tests.conftest import tagged_show
from tests.cortex.conftest import REPO_ROOT, STUCK_SCENARIO, STUCK_UNIT_ID
from tests.runtime.stubs import seed_brain
from tests.mailbox.answering import answer

TASK_ID = "task-stuck"
ANSWER_TEXT = "the statement is authoritative; reconcile against it and stop there."


show = tagged_show("M16")


def _climb(brain: Path, workspace: Path, layer, mailbox, scenario):
    """The scenario, run until it commits a terminal. The battery's whole subject."""
    outcome = engine.start(
        brain,
        scenario.goal,
        layer,
        mailbox=mailbox,
        workspace_path=str(workspace),
        task_id=TASK_ID,
        max_ticks=60,
    )
    return outcome, layer.router


@pytest.fixture(scope="module")
def climbed(tmp_path_factory: pytest.TempPathFactory):
    """One 60-tick climb for the whole module, and the root it left behind.

    Every consumer of this fixture reads the committed tree — the router's selections, the one
    mailbox file, the cortex trace — and writes nothing, so the climb is paid once rather than
    once per claim. `resolved` below **answers** that item and resumes on top of it, so it drives
    its own climb on its own root instead of consuming this one.
    """
    from protean.cortex.layer import build_layer

    base = tmp_path_factory.mktemp("stuck")
    brain = seed_brain(REPO_ROOT / "brain", base / "brain")
    workspace = base / "workspace"
    workspace.mkdir()
    scenario = load_scenario(STUCK_SCENARIO)
    layer = build_layer(root=brain, script=scenario.script)
    outcome, router = _climb(brain, workspace, layer, build_mailbox(brain), scenario)
    return outcome, router, brain


def _open_files(brain: Path) -> list[str]:
    directory = brain / "mailbox" / "open"
    return sorted(path.name for path in directory.iterdir()) if directory.exists() else []


def _paths(brain: Path):
    return BrainPaths(root=brain).task(TASK_ID)


# --------------------------------------------------------------------------------------
# The climb, and where it ends
# --------------------------------------------------------------------------------------


def test_the_scenario_escalates_unit_then_planner_then_director(climbed):
    outcome, router, _brain = climbed
    sequence = escalation_names(router.selections)
    show("recorded escalation sequence", list(sequence))

    tiers = [str(selection.tier) for selection in router.selections]
    assert tiers[0] == str(Tier.MANAGER), "rung 1 is always the manager"
    assert tiers[-1] == str(Tier.DIRECTOR), "and the climb ends at the director"
    # **Re-based by build A.1**: tier three is not a seat and the router never selects it
    # (`the build specification (not in this mirror)` § Deliverable 3). The pass on which the unit is
    # acted on is the manager's **fall-through** — the one arm that moved, from the deleted
    # executor seat to the manager — and it is the arm that carries no escalation at all. The
    # dispatch itself rides that pass's `ManagerPlan` as its wave.
    assert str(CallType.DISPATCH) not in tiers, "a dispatch is dispatched, never routed to"
    acting = [
        index
        for index, selection in enumerate(router.selections)
        if selection.tier is Tier.MANAGER and selection.escalation is None
    ]
    assert acting, "the unit is acted on before anything escalates"

    first_executor = acting[0]
    first_director = tiers.index(str(Tier.DIRECTOR))
    rung_one = next(
        index
        for index, selection in enumerate(router.selections)
        if selection.escalation is Escalation.TRAP_SIGNAL
    )
    assert first_executor < rung_one < first_director, "unit -> planner -> director, in that order"


def test_rung_one_carries_the_trap_that_fired_and_the_unit_it_measured(climbed):
    _outcome, router, _brain = climbed
    escalated = [
        selection
        for selection in router.selections
        if selection.escalation is Escalation.TRAP_SIGNAL
    ]
    assert escalated, "a trap signal is what hands the unit to the planner"
    for selection in escalated:
        assert selection.unit_id == STUCK_UNIT_ID
        assert selection.trap_evidence, "the evidence rides the escalation"
        assert all(scalar.fired for scalar in selection.trap_evidence)


def test_rung_two_is_reached_only_after_the_replan_count_is_spent(climbed, cortex_weights):
    _outcome, router, _brain = climbed
    replans = sum(
        1
        for selection in router.selections
        if selection.tier is Tier.MANAGER and selection.unit_id is not None
    )
    show("re-plans before the director", replans)
    assert replans >= int(cortex_weights["k_replan"]), "the director is not reached early"


def test_the_run_ends_stuck_with_its_own_exit_code(climbed):
    outcome, _router, _brain = climbed
    show("terminal", str(outcome.terminal))
    show("exit code", f"{outcome.exit_code} (config.EXIT_STUCK={config.EXIT_STUCK})")
    assert outcome.terminal is TerminalState.STUCK
    assert outcome.exit_code == config.EXIT_STUCK
    assert config.EXIT_STUCK not in {
        code for name, code in config.EXIT_CODES.items() if name != "stuck"
    }


def test_the_operator_surface_exits_with_the_stuck_code(
    brain: Path, monkeypatch, scenario
):
    """The same run through `protean run`, resolving both layers by dotted path as a shell would."""
    monkeypatch.setenv(config.BRAIN_ROOT_ENV, str(brain))
    monkeypatch.setenv(SEAT_SCRIPT_ENV, "stuck_ladder")
    code = cli.main(["run", scenario.goal])
    show("`protean run` exit code", code)
    assert code == config.EXIT_STUCK


# --------------------------------------------------------------------------------------
# The one mailbox file the runtime raised
# --------------------------------------------------------------------------------------


def test_exactly_one_open_file_of_kind_stuck_raised_by_the_runtime(climbed):
    _outcome, _router, brain = climbed
    files = _open_files(brain)
    show("mailbox/open/ listing", files)
    assert len(files) == 1, "the runtime writes ONE mailbox interrupt at a `stuck` raise"

    text = (brain / "mailbox" / "open" / files[0]).read_text(encoding="utf-8")
    show("mailbox file", "\n" + text)
    item = parse(text)
    assert item.kind is InterruptKind.STUCK
    assert item.raised_by is Raiser.RUNTIME
    assert item.task == TASK_ID
    assert item.is_answered() is False, "it blocks close until the operator answers it"


def test_the_evidence_body_names_which_signals_fired_on_which_units_and_for_how_long(climbed):
    """B10's artifact: the evidence has to be enough to rule on without opening another file."""
    _outcome, _router, brain = climbed
    item = parse((brain / "mailbox" / "open" / _open_files(brain)[0]).read_text("utf-8"))
    show("evidence", json.dumps(item.evidence, indent=2, sort_keys=True))

    assert item.evidence["goal_id"] == f"{TASK_ID}-g1"
    assert item.evidence["redirect_count"] >= 1
    assert item.evidence["replan_count"] >= 1
    assert item.evidence["no_progress_ticks"] >= 1
    fired = item.evidence["fired"]
    assert fired, "which signals fired"
    for scalar in fired:
        assert scalar["unit_id"] == STUCK_UNIT_ID, "on which units"
        assert scalar["fired"] is True
        assert scalar["value"] >= scalar["threshold"]
        assert scalar["weight_key"], "against which threshold, by the key that scored it"


def test_the_kind_set_is_closed_at_two(climbed):
    """`kind` accepts only `question` and `stuck` — a third value is refused, not tolerated."""
    _outcome, _router, brain = climbed
    assert [member.value for member in InterruptKind] == ["question", "stuck"]
    with pytest.raises(ValueError):
        InterruptKind("escalate")

    path = brain / "mailbox" / "open" / _open_files(brain)[0]
    with pytest.raises(MailboxFormatError):
        parse(path.read_text("utf-8").replace("kind: stuck", "kind: escalate"))


def test_the_synthetic_director_prediction_is_minted_only_when_none_exists(climbed):
    """Folded U-6: the raise tick's director ran, so no synthetic record is added beside it."""
    outcome, _router, brain = climbed
    raise_tick = outcome.ticks[-1].tick
    records = [
        record
        for record in read_lines(_paths(brain).trace(str(NodeName.CORTEX)))
        if record["tick"] == raise_tick
        and record["kind"] == "prediction"
        and record["tier"] == str(Tier.DIRECTOR)
    ]
    show("director-tier predictions at the raise tick", len(records))
    assert len(records) == 1, "exactly one prediction per (folder, tier) per tick"


# --------------------------------------------------------------------------------------
# Resolution: the record, the reset, and what the resumed run does with the answer
# --------------------------------------------------------------------------------------


@pytest.fixture()
def resolved(brain: Path, workspace: Path, stuck_layer, mailbox, scenario):
    """the operator answers the item; a **new** layer resumes the task, as a second process would.

    Its own climb, on its own root: answering the item and resuming writes the tree the
    module-scoped `climbed` hands its readers, so this half cannot share it.
    """
    outcome, _router = _climb(brain, workspace, stuck_layer, mailbox, scenario)
    raised = _open_files(brain)[0]
    answer(brain / "mailbox" / "open" / raised, ANSWER_TEXT)

    from protean.cortex.layer import build_layer

    resumed_layer = build_layer(root=brain, script=scenario.script)
    second = engine.resume(
        brain,
        resumed_layer,
        mailbox=build_mailbox(brain),
        workspace_path=str(workspace),
        max_ticks=60,
    )
    return outcome, second, raised.removesuffix(".md"), resumed_layer.router


def test_the_resolution_record_lands_on_the_cortex_folder_under_the_director_tier(
    resolved, brain: Path
):
    first, second, raised, _router = resolved
    records = [
        record
        for record in read_lines(_paths(brain).trace(str(NodeName.CORTEX)))
        if record.get("source") == "operator_answer"
    ]
    assert len(records) == 1
    landed = records[0]
    show("operator_answer trace line", json.dumps(landed, sort_keys=True))

    assert landed["node"] == str(NodeName.CORTEX)
    assert landed["tier"] == str(Tier.DIRECTOR), "the exhausted rung is the director's"
    assert landed["kind"] == "outcome"
    assert landed["outcome"]["answer"] == ANSWER_TEXT
    assert landed["ref"] == f"{TASK_ID}:{first.ticks[-1].tick}:cortex:director:prediction"
    assert landed["tick"] == second.ticks[0].tick, "keyed to the resume tick"


def test_resolving_it_resets_the_counters_and_the_windows_in_the_checkpoint(
    resolved, brain: Path
):
    """Read back from disk, not from memory: without the reset the run re-exhausts at once."""
    _first, second, raised, _router = resolved
    committed = json.loads(_paths(brain).checkpoint.read_text(encoding="utf-8"))["state"]
    goal = committed["goals"][0]
    show("goal after resolution", json.dumps(goal, sort_keys=True))
    show("unit windows after resolution", {k: len(v) for k, v in committed["unit_windows"].items()})

    assert goal["replan_count"] == 0
    assert goal["redirect_count"] == 0
    assert goal["last_progress_tick"] >= second.ticks[0].tick
    assert all(not rows for rows in committed["unit_windows"].values())
    assert [item["id"] for item in committed["resolved_interrupts"]] == [raised]
    assert committed["open_interrupts"] == []


def test_the_file_is_deleted_and_the_answered_run_closes_the_goal(resolved, brain: Path):
    _first, second, _raised, router = resolved
    show("mailbox/open/ after resolution", _open_files(brain))
    show("resumed escalation sequence", list(escalation_names(router.selections)))
    assert _open_files(brain) == []
    assert second.terminal is TerminalState.DONE
    assert second.exit_code == config.EXIT_DONE
    assert router.selections[0].escalation is Escalation.REDIRECT_EXHAUSTED


def test_the_interrupt_resolved_event_lands_beside_it(resolved, brain: Path):
    _first, second, raised, _router = resolved
    events = [
        record
        for record in read_lines(_paths(brain).episodes)
        if record.get("event_name") == "interrupt_resolved"
    ]
    assert len(events) == 1
    show("interrupt_resolved episode line", json.dumps(events[0], sort_keys=True))
    assert events[0]["detail"]["id"] == raised
    assert events[0]["detail"]["answer"] == ANSWER_TEXT


# --------------------------------------------------------------------------------------
# The scenario file itself
# --------------------------------------------------------------------------------------


def test_the_scenario_names_a_goal_and_a_script_that_exists(scenario):
    assert scenario.name == STUCK_SCENARIO
    assert scenario.goal.strip()
    assert scenario.script.responses


def test_a_scenario_missing_its_goal_or_its_script_is_refused(tmp_path: Path):
    root = tmp_path / "fixtures" / "scenarios" / "broken"
    root.mkdir(parents=True)
    (root / "scenario.yaml").write_text("name: broken\n", encoding="utf-8")
    with pytest.raises(ScenarioError, match="goal"):
        load_scenario("broken", tmp_path)


def test_a_scenario_resolves_its_script_by_stem_under_the_fixture_tree():
    assert script_path("stuck_ladder").exists()
    assert script_path("stuck_ladder").parent.name == "seat_scripts"
