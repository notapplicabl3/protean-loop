"""The three drivers: the resume order, the refusal ladder, and the administrative commits.

`the build specification (not in this mirror)` § Deliverable 3 — the operator surface, one task per brain
root, *Resume, in order*, the three administrative acts — and § Deliverable 5's refusal on an
unanswered item.

Builder-verified rows M13's runtime half, M14's `run`-refusal and `--abandon` clauses, and
M20's `--reseed` / `--extend` clauses.

**The lock comes first on every `resume` form, flags included** (folded: U-5, dispatch ledger
D5-13): the answer check's refusal happens *inside* the lock and releases it, changing no task
state. That ordering is asserted here by driving the engine, and the lock's own mechanics are
`tests/runtime/test_lock.py`'s.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from protean import config
from protean.brain.episodes import read_episodes
from protean.brain.jsonl import read_lines
from protean.runtime import engine
from protean.runtime.cycle import run_tick
from protean.runtime.engine import (
    ABANDONED_ANSWER,
    build_context,
    current_task,
    load_task,
    mint_task_id,
    new_state,
    occupied_task,
    resume,
    start,
    status,
)
from protean.runtime.errors import NoTask, RootOccupied
from protean.runtime.paths import BrainPaths
from protean.state.enums import (
    EventName,
    GoalStatus,
    TerminalState,
    Tier,
)
from protean.state.seats import ManagerPlan
from tests.runtime import stubs


@pytest.fixture(autouse=True)
def no_close_out(monkeypatch):
    """Every terminal in this module is reached **without** its report and archive step.

    `close_out()` runs `build_report()` + `archive_run()` + two `git rev-parse` spawns on every
    terminal, and this module reaches ~30 of them while asserting on neither artifact: what it
    is about is the driver's own ladder — the answer check, the three administrative commits,
    the lock and `status`. The claim that the archive lands on **every** one of the five
    terminals is owned, and asserted, by
    `tests/runtime/test_archive.py::test_the_archive_lands_on_every_one_of_the_five_terminals`.

    **Scoped to this module on purpose.** It is autouse here and nowhere else: a conftest-level
    opt-out would silently disarm the archive for every battery that drives a terminal.
    """
    monkeypatch.setattr(engine, "close_out", lambda *arguments, **keywords: None)


def _interrupted_task(brain: Path, workspace: Path, mailbox, task_id: str = "task-i"):
    """Run one tick that raises a question and commits `interrupted`."""
    layer = stubs.planner_layer(stubs.asking_planner())
    outcome = start(
        brain,
        "keep going",
        layer,
        mailbox=mailbox,
        workspace_path=str(workspace),
        task_id=task_id,
        max_ticks=1,
    )
    assert outcome.terminal is TerminalState.INTERRUPTED
    return layer, outcome


# --------------------------------------------------------------------------------------
# `run` and one task per brain root
# --------------------------------------------------------------------------------------


def test_a_task_id_is_filesystem_safe_and_sortable():
    """One task per brain root, so uniqueness is by time and the id sorts the way time does."""
    earlier = mint_task_id(datetime(2026, 1, 1, tzinfo=timezone.utc))
    later = mint_task_id(datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert earlier.startswith("task-") and later.startswith("task-")
    assert sorted([later, earlier]) == [earlier, later]
    assert not set(earlier) & set("/\\ :")


def test_run_opens_a_task_and_writes_its_start_event(brain: Path, workspace: Path, mailbox):
    outcome = start(
        brain,
        "finish it",
        stubs.planner_layer(lambda request: ManagerPlan(
            tick=request.workspace.tick,
            goals_satisfied=[request.workspace.goals[0].id],
        )),
        mailbox=mailbox,
        workspace_path=str(workspace),
        task_id="task-run",
        max_ticks=1,
    )
    assert outcome.terminal is TerminalState.DONE
    assert outcome.exit_code == config.EXIT_DONE

    events = [item.event_name for item in read_episodes(BrainPaths(root=brain).task("task-run").episodes)]
    assert EventName.TASK_START in events
    assert EventName.TERMINAL in events


def test_run_is_refused_while_a_non_terminal_task_holds_the_root(
    brain: Path, workspace: Path, mailbox
):
    _interrupted_task(brain, workspace, mailbox)
    with pytest.raises(RootOccupied) as raised:
        start(
            brain,
            "another one",
            stubs.planner_layer(stubs.quiet_planner),
            mailbox=mailbox,
            workspace_path=str(workspace),
            max_ticks=1,
        )
    assert "task-i" in str(raised.value)


def test_a_done_task_frees_the_root_for_a_second_run(brain: Path, workspace: Path, mailbox):
    start(
        brain,
        "first",
        stubs.planner_layer(lambda request: ManagerPlan(
            tick=request.workspace.tick, goals_satisfied=[request.workspace.goals[0].id]
        )),
        mailbox=mailbox,
        workspace_path=str(workspace),
        task_id="task-a",
        max_ticks=1,
    )
    assert occupied_task(BrainPaths(root=brain)) is None
    second = start(
        brain,
        "second",
        stubs.planner_layer(lambda request: ManagerPlan(
            tick=request.workspace.tick, goals_satisfied=[request.workspace.goals[0].id]
        )),
        mailbox=mailbox,
        workspace_path=str(workspace),
        task_id="task-b",
        max_ticks=1,
    )
    assert second.terminal is TerminalState.DONE


def test_current_task_refuses_an_empty_root(brain: Path):
    with pytest.raises(NoTask):
        current_task(BrainPaths(root=brain))


# --------------------------------------------------------------------------------------
# The answer check — silence is never assent
# --------------------------------------------------------------------------------------


def test_a_resume_over_an_unanswered_item_refuses_with_its_own_code_and_names_the_file(
    brain: Path, workspace: Path, mailbox
):
    """One refusal, read twice: the code and the committed bytes, and the file the operator has to open."""
    layer, _outcome = _interrupted_task(brain, workspace, mailbox)
    before = BrainPaths(root=brain).task("task-i").checkpoint.read_bytes()

    outcome = resume(brain, layer, mailbox=mailbox, workspace_path=str(workspace))

    assert outcome.refusal == "unanswered_interrupt"
    assert outcome.exit_code == config.EXIT_UNANSWERED_INTERRUPT
    assert outcome.ticks == []
    assert BrainPaths(root=brain).task("task-i").checkpoint.read_bytes() == before

    identifier = mailbox.open_ids()[0]
    assert any(identifier in message for message in outcome.messages)


def test_an_empty_answer_body_is_still_unanswered(brain: Path, workspace: Path, mailbox):
    layer, _outcome = _interrupted_task(brain, workspace, mailbox)
    mailbox.answer(mailbox.open_ids()[0], "   ")
    outcome = resume(brain, layer, mailbox=mailbox, workspace_path=str(workspace))
    assert outcome.refusal == "unanswered_interrupt"


@pytest.fixture()
def answered_resume(brain: Path, workspace: Path, mailbox):
    """One interrupted task, answered, and resumed for one quiet tick.

    The resolution leaves its mark in three places — the checkpoint, the raising folder's trace
    and the task's episodes — and all three are readings of the *same* resume, which was driven
    three times. Returns `(outcome, identifier)`.
    """
    _interrupted_task(brain, workspace, mailbox)
    identifier = mailbox.open_ids()[0]
    mailbox.answer(identifier, "use src/")
    outcome = resume(
        brain,
        stubs.planner_layer(stubs.quiet_planner),
        mailbox=mailbox,
        workspace_path=str(workspace),
        max_ticks=1,
    )
    return outcome, identifier


def test_an_answer_resolves_the_item_and_lands_everywhere_the_resolution_is_recorded(
    brain: Path, mailbox, answered_resume
):
    """Three readings of one answered resume, one block apiece."""
    outcome, identifier = answered_resume

    # The item is resolved before the next tick, and the file is gone.
    assert outcome.refusal is None
    payload = stubs.committed_state(BrainPaths(root=brain).task("task-i"))
    assert payload["state"]["open_interrupts"] == []
    assert [item["id"] for item in payload["state"]["resolved_interrupts"]] == [identifier]
    assert mailbox.deleted == [identifier]

    # The resolution lands as a `operator_answer` outcome on the folder that raised it.
    records = read_lines(config.node_dir(config.CORTEX_NODE, brain) / "trace.jsonl")
    answers = [item for item in records if item["source"] == "operator_answer"]
    assert len(answers) == 1
    assert answers[0]["tier"] == str(Tier.MANAGER)
    assert answers[0]["tick"] == 2, "keyed to the resume tick"
    assert answers[0]["ref"].startswith("task-i:1:cortex:manager")

    # And it writes an `INTERRUPT_RESOLVED` event.
    events = [
        item.event_name
        for item in read_episodes(BrainPaths(root=brain).task("task-i").episodes)
    ]
    assert EventName.INTERRUPT_RESOLVED in events


def test_a_vanished_mailbox_file_is_re_materialized_before_the_answer_check(
    brain: Path, workspace: Path, mailbox
):
    """folded: T-1 — state carries everything the file needs, so a deleted file comes back."""
    layer, _outcome = _interrupted_task(brain, workspace, mailbox)
    identifier = mailbox.open_ids()[0]
    mailbox.path_for(identifier).unlink()
    assert mailbox.open_ids() == []

    outcome = resume(brain, layer, mailbox=mailbox, workspace_path=str(workspace))
    assert mailbox.open_ids() == [identifier]
    assert outcome.refusal == "unanswered_interrupt"
    assert any("re-materialized" in message for message in outcome.messages)


def test_a_file_with_no_committed_entry_is_orphaned_aside(brain: Path, workspace: Path, mailbox):
    layer, _outcome = _interrupted_task(brain, workspace, mailbox)
    stray = mailbox.open_dir / "stray.md"
    stray.write_text("{}\n\n## Answer\n\n", encoding="utf-8")

    outcome = resume(brain, layer, mailbox=mailbox, workspace_path=str(workspace))
    assert "stray" in mailbox.orphaned
    assert (mailbox.orphan_dir / "stray.md").exists()
    assert any("orphaned stray" in message for message in outcome.messages)


# --------------------------------------------------------------------------------------
# The three administrative commits — exempt from the answer check, never from the lock
# --------------------------------------------------------------------------------------


def test_abandon_retires_every_open_item_frees_the_root_and_runs_no_node(
    brain: Path, workspace: Path, mailbox
):
    """One abandon, read twice: what it commits, and that it needed no answer and ran nothing."""
    layer, _outcome = _interrupted_task(brain, workspace, mailbox)
    identifier = mailbox.open_ids()[0]
    seat = layer.port
    calls = len(seat.calls)

    outcome = resume(brain, None, mailbox=mailbox, workspace_path=str(workspace), abandon=True)

    assert outcome.terminal is TerminalState.DONE
    payload = stubs.committed_state(BrainPaths(root=brain).task("task-i"))
    assert payload["state"]["terminal"] == str(TerminalState.DONE)
    assert payload["state"]["open_interrupts"] == []
    assert payload["state"]["resolved_interrupts"][0]["answer"] == ABANDONED_ANSWER
    assert {goal["status"] for goal in payload["state"]["goals"]} == {
        str(GoalStatus.ABANDONED)
    }
    assert mailbox.deleted == [identifier]
    assert occupied_task(BrainPaths(root=brain)) is None

    # It is exempt from the answer check, and it is not a tick: no node ran and no seat was called.
    assert outcome.ticks == []
    assert len(seat.calls) == calls


def test_extend_writes_the_ceiling_overrides_and_increments_the_revision_without_a_tick(
    brain: Path, workspace: Path, mailbox
):
    """`extend` is one administrative commit, read in every way this module reads one.

    * it writes the ceiling overrides — the extra ticks, the tick they were set at, and a
      `terminal` back to `None`;
    * it **increments the revision**, which is the claim every administrative commit is held
      to; and it runs **no node**, so the committed tick is exactly the one it started from; and
    * a duration in minutes is written as seconds.
    """
    _interrupted_task(brain, workspace, mailbox)
    paths = BrainPaths(root=brain).task("task-i")
    before = stubs.committed_state(paths)

    resume(brain, None, mailbox=mailbox, workspace_path=str(workspace), extend="7")
    after = stubs.committed_state(paths)

    overrides = after["state"]["ceiling_overrides"]
    assert overrides["extra_ticks"] == 7
    assert overrides["set_at_tick"] == after["state"]["tick"]
    assert after["state"]["terminal"] is None

    assert after["revision"] == before["revision"] + 1
    assert after["state"]["tick"] == before["state"]["tick"], "no node ran"

    resume(brain, None, mailbox=mailbox, workspace_path=str(workspace), extend="2m")
    minutes = stubs.committed_state(paths)
    assert minutes["state"]["ceiling_overrides"]["extra_seconds"] == 120.0


def test_a_stopped_task_resumed_without_an_extend_stops_again(
    brain: Path, workspace: Path, mailbox
):
    """folded: S-13 — the override is the only thing that moves a ceiling."""
    stubs.set_weight(brain, "homeostasis", max_ticks=1)

    layer = stubs.planner_layer(stubs.quiet_planner)
    first = start(
        brain, "stop me", layer, mailbox=mailbox, workspace_path=str(workspace),
        task_id="task-s", max_ticks=3,
    )
    assert first.terminal is TerminalState.STOPPED

    again = resume(brain, layer, mailbox=mailbox, workspace_path=str(workspace), max_ticks=1)
    assert again.terminal is TerminalState.STOPPED

    resume(brain, None, mailbox=mailbox, workspace_path=str(workspace), extend="5")
    extended = resume(brain, layer, mailbox=mailbox, workspace_path=str(workspace), max_ticks=1)
    assert extended.terminal is None


def test_reseed_prints_every_changed_seed_file_and_re_hashes_it(
    brain: Path, workspace: Path, mailbox
):
    _interrupted_task(brain, workspace, mailbox)
    stubs.set_weight(brain, "thalamus", max_admitted=3)

    outcome = resume(brain, None, mailbox=mailbox, workspace_path=str(workspace), reseed=True)

    assert any("nodes/thalamus/weights.yaml" in message for message in outcome.messages)
    events = [
        item.event_name
        for item in read_episodes(BrainPaths(root=brain).task("task-i").episodes)
    ]
    assert EventName.RESEEDED in events
    load_task(BrainPaths(root=brain).task("task-i"))  # the ladder passes again


def test_a_silent_seed_edit_is_still_refused(brain: Path, workspace: Path, mailbox):
    from protean.state.errors import SeedHashMismatch

    _interrupted_task(brain, workspace, mailbox)
    path = config.node_dir("thalamus", brain) / "weights.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")

    with pytest.raises(SeedHashMismatch):
        load_task(BrainPaths(root=brain).task("task-i"))


def test_reseed_with_nothing_changed_says_so(brain: Path, workspace: Path, mailbox):
    _interrupted_task(brain, workspace, mailbox)
    outcome = resume(brain, None, mailbox=mailbox, workspace_path=str(workspace), reseed=True)
    assert any("no seed file changed" in message for message in outcome.messages)


# --------------------------------------------------------------------------------------
# `status` — read-only
# --------------------------------------------------------------------------------------


def test_status_on_an_empty_root_reports_no_task(brain: Path):
    report = status(brain)
    assert report.task_id is None
    assert "no task" in report.render()


def test_status_reports_the_task_tick_terminal_and_open_items(
    brain: Path, workspace: Path, mailbox
):
    # `status()` takes no seat layer — the signature below is the whole of that claim, which is
    # why the removed `test_status_needs_no_seat_layer` (same `task_id` assertion) is gone: a
    # checkout with no `src/protean/cortex/` still reports, because no node runs on this path.
    _interrupted_task(brain, workspace, mailbox)
    report = status(brain)
    assert report.task_id == "task-i"
    assert report.tick == 1
    assert report.terminal is TerminalState.INTERRUPTED
    assert report.open_interrupts == tuple(mailbox.open_ids())
    rendered = report.render()
    assert "task-i" in rendered and str(TerminalState.INTERRUPTED) in rendered


def test_status_writes_nothing(brain: Path, workspace: Path, mailbox):
    _interrupted_task(brain, workspace, mailbox)
    paths = BrainPaths(root=brain).task("task-i")
    before = paths.checkpoint.read_bytes()
    lock_exists = BrainPaths(root=brain).lock.exists()

    status(brain)

    assert paths.checkpoint.read_bytes() == before
    assert BrainPaths(root=brain).lock.exists() is lock_exists


def test_a_started_task_reports_its_own_goal(brain: Path, workspace: Path, layer):
    seat_layer, _router, _seat = layer
    context = build_context(brain, "task-g", seat_layer, workspace_path=str(workspace))
    state = new_state("task-g", "the goal text", context)
    assert state.goals[0].text == "the goal text"
    state.tick += 1
    run_tick(context, state)
    assert status(brain).open_goals == (state.goals[0].id,)
