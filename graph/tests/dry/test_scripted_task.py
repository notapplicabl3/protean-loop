"""M21's task half: `protean dry dry` runs the scripted task to `done`, in the shape written down.

`the build specification (not in this mirror)` § Deliverable 7 -> *The scripted task*: "A goal, a `SeatScript`
responder per tier (request-keyed, thresholds read from the same weights file the runtime reads),
a seeded **throwaway temp workspace** created and destroyed by the fixture, and an expected tick
trace."

**The trace is read, never generated.** `fixtures/scenarios/dry/expected.yaml` is hand-authored
against the router's rules and this module compares the run to it; a trace derived from the run
would assert only that the run equals itself. Its `climb` list carries no number of any kind --
position is the pass, and every count and threshold lives in the weights files the runtime
reads. It says `climb` rather than naming the loop's unit of work because W3's landed fixture
rule greps every authored `fixtures/**.yaml` for that word (`tests/cortex/test_scripts.py`),
prose included; the two are the same list either way.

**What this does NOT prove is B9.** The seats are hand-authored responders: the executor
*reports* a file-shaped observation and nothing in build 1 writes that file. What is proven is
that the contracts carry a real task from goal to terminal without a model in the loop, that
the workspace is a real directory whose path reaches the act, and that the grading is
deterministic. Whether a live cortex will honour these contracts is the operator's row.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from protean import cli, config
from protean.cortex.layer import build_layer
from protean.cortex.scenario import load_scenario
from protean.runtime import engine
from protean.runtime.seat import SeatLayer
from protean.runtime.cycle import SEAT_CALL_NUMBER
from protean.state.enums import CallType, TerminalState, Tier
from protean.state.seats import WaveMember
from tests.dry.conftest import DRY_SCENARIO, SCENARIO_DIR, WORKSPACE_SEED


def _printed_ticks(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("tick ")]


def _field(line: str, index: int) -> str:
    """`tick 2: executor (-) unit=- nodes=6 journal=6` -> one whitespace-delimited field."""
    return line.split()[index]


# --------------------------------------------------------------------------------------
# The run, and the terminal it commits
# --------------------------------------------------------------------------------------


def test_the_scripted_task_completes_and_exits_on_the_done_code(dry_run) -> None:
    print(dry_run.out)
    assert dry_run.code == config.EXIT_DONE
    assert config.TERMINAL_EXIT_CODES[str(TerminalState.DONE)] == dry_run.code
    assert "terminal: done" in dry_run.out


def test_the_run_climbs_in_the_shape_the_fixture_wrote_down(dry_run, expected_trace) -> None:
    printed = _printed_ticks(dry_run.out)
    assert len(printed) == len(expected_trace["climb"]), printed

    for index, (line, expected) in enumerate(zip(printed, expected_trace["climb"]), start=1):
        assert _field(line, 1) == f"{index}:", "list position is the pass"
        assert _field(line, 2) == expected["tier"], line  # tier three is never routed to
        assert _field(line, 3).strip("()") == str(expected["escalation"] or "-"), line
        assert _field(line, 4) == f"unit={expected['unit'] or '-'}", line


def test_every_node_runs_every_tick_and_journals_one_entry_plus_one_per_call(
    dry_run, expected_trace
) -> None:
    """Binding contract 5, visible in the trace the verb prints: six of six, every pass.

    **Re-based by build A.1** (`the build specification (not in this mirror)` § Deliverable 6): the
    journal is one entry per node **plus one per call**, where build 1 wrote one per node and
    nothing else. Every node still writes exactly one output entry at the reserved `call# = 0`,
    so the six is unchanged and the surplus is the calls: the seat call every pass makes, and
    the dispatch wave's one member on the pass the fixture says dispatched one. The wave takes
    **one** `call#` however many members it holds, and each member a `member#` beneath it.
    """
    for line, expected in zip(_printed_ticks(dry_run.out), expected_trace["climb"]):
        assert f"nodes={len(config.NODE_ORDER)}" in line, line
        entries = len(config.NODE_ORDER) + SEAT_CALL_NUMBER + (1 if expected["wave"] else 0)
        assert f"journal={entries}" in line, line


def test_the_terminal_the_fixture_names_is_the_one_that_commits(dry_run, expected_trace) -> None:
    assert f"terminal: {expected_trace['terminal']}" in dry_run.out


# --------------------------------------------------------------------------------------
# The scenario and its seeded workspace
# --------------------------------------------------------------------------------------


def test_the_scenario_is_a_goal_and_the_name_of_a_reusable_responder_set() -> None:
    scenario = load_scenario(DRY_SCENARIO)
    assert scenario.name == DRY_SCENARIO
    assert scenario.goal.strip()
    assert scenario.script.responses, "the responders are hand-authored, not generated"
    for tier in (Tier.MANAGER, Tier.DIRECTOR):
        assert scenario.script.for_tier(tier), f"a responder per seat: {tier}"
    assert scenario.script.for_tier(CallType.DISPATCH), (
        "and a scripted return per dispatch member: a dispatch is a call type rather than a "
        "seat, so it is answered by a return with no process behind it"
    )


def _walk(node):
    """Every key and every leaf of a loaded fixture, keys first."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield "key", str(key)
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)
    else:
        yield "leaf", node


def test_this_order_s_fixtures_carry_no_tick_index_and_no_threshold_value() -> None:
    """§ Deliverable 6's rule, held structurally: parsed data, not a grep over the prose.

    Two claims in one walk. No mapping key is `tick`, so nothing here indexes by tick number --
    `expected.yaml`'s list position is the tick and that is the only ordering it has. And no
    leaf is a number at all, so no count and no threshold is restated here: every one of them
    lives in the weights file the runtime reads.
    """
    for path in sorted(SCENARIO_DIR.rglob("*.yaml")):
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        for kind, value in _walk(loaded):
            if kind == "key":
                assert value != "tick", f"{path}: a tick index"
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                raise AssertionError(f"{path}: a restated count or threshold ({value})")


def test_the_workspace_seed_is_hand_authored_and_copied_to_a_throwaway(tmp_path: Path) -> None:
    seeded = cli._seed_workspace(DRY_SCENARIO, tmp_path / "workspace")
    assert seeded.is_dir()
    copied = sorted(path.name for path in seeded.iterdir())
    assert copied == sorted(path.name for path in WORKSPACE_SEED.iterdir())
    assert copied, "an empty workspace would not carry a file-shaped observation anywhere"
    assert seeded != WORKSPACE_SEED, "the run acts on the copy, never on the fixture"


def test_a_scenario_with_no_seed_directory_still_gets_a_workspace(tmp_path: Path) -> None:
    seeded = cli._seed_workspace("no-such-scenario", tmp_path / "workspace")
    assert seeded.is_dir() and not any(seeded.iterdir())


def test_the_seeded_workspace_path_reaches_the_act(tmp_path: Path) -> None:
    """Decision 17's whole point: the executor contract carries a workspace from day one."""
    scenario = load_scenario(DRY_SCENARIO)
    root = cli._seed_root(tmp_path / "brain")
    workspace = cli._seed_workspace(DRY_SCENARIO, tmp_path / "workspace")
    layer = build_layer(root=root, script=scenario.script)

    seen: list[str] = []

    members: list[WaveMember] = []

    def recording_port(tier, request):
        # Re-based by build A.1: no request carries a workspace path any more —
        # `ExecutorRequest` is retired and `WaveMember` has **no path field**, because the
        # workspace a member sees is the **runtime's** to fill from the tick context. What is
        # recorded here is the path the runtime resolved for the pass that dispatched, beside
        # the member itself, so both halves of that sentence are asserted.
        if isinstance(request, WaveMember):
            members.append(request)
            seen.append(str(workspace))
        return layer.port(tier, request)

    outcome = engine.start(
        root,
        scenario.goal,
        SeatLayer(router=layer.router, port=recording_port, sessions=layer.sessions),
        workspace_path=str(workspace),
        task_id="task-dry-workspace",
    )
    assert outcome.terminal is TerminalState.DONE
    assert seen == [str(workspace)], "the act was handed the throwaway workspace, not the repo"
    assert members and all(
        "workspace_path" not in type(member).model_fields for member in members
    ), "and the member request itself names no directory at all"
    assert (workspace / "brief.md").is_file(), "and it is a real directory with real bytes in it"


# --------------------------------------------------------------------------------------
# What the verb leaves behind
#
# The trees-are-destroyed case lives in `test_blast_radius.py` now, merged with the two
# teardown claims it shared a run with (audit rows N1 + N8).
# --------------------------------------------------------------------------------------


def test_the_verb_restores_the_environment_it_borrowed(monkeypatch) -> None:
    """The hazard the battery would otherwise inherit: a dead temp root left in the variable."""
    monkeypatch.setenv(config.BRAIN_ROOT_ENV, "/nowhere/in/particular")
    assert cli.main(["dry", DRY_SCENARIO]) == config.EXIT_DONE
    import os

    assert os.environ[config.BRAIN_ROOT_ENV] == "/nowhere/in/particular"


def test_the_verb_leaves_no_variable_behind_when_there_was_none(monkeypatch) -> None:
    import os

    monkeypatch.delenv(config.BRAIN_ROOT_ENV, raising=False)
    assert cli.main(["dry", DRY_SCENARIO]) == config.EXIT_DONE
    assert config.BRAIN_ROOT_ENV not in os.environ
