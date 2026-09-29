"""Decision 22: every task carries a project slug, written at task open and restored on resume.

`the build specification (not in this mirror)` § Deliverable 5 (*The slug is every task's*), § Directional
decisions 22, § Resolutions S-2, and § DoD row L8's last clause.

**The first real user of build 1's extension registry.** `BrainState.extensions` has existed
since build 1 and nothing has ever registered a namespace in it; the slug is the first, which is
why these tests assert the *registry's* shape — a namespaced `ProjectExtension` with its own
version — rather than a bare field. `BrainState` itself is inherited unchanged (§ Directional
decisions 1): no top-level shape change, and `tests/state/test_contracts_frozen.py` still diffs
it against build 1's landed commit.

**Restored on resume is a property of the checkpoint, not of a second code path.** The slug rides
`BrainState`, so `load_checkpoint()`'s own refusal ladder carries it back; the test below drives a
real administrative resume and reads the slug off the checkpoint that commit rewrote.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protean.runtime.engine import (
    PROJECT_EXTENSION,
    PROJECT_EXTENSION_VERSION,
    PROJECT_SLUG_FIELD,
    WORKSPACE_EXTENSION,
    load_task,
    project_slug,
    resume,
    start,
)
from protean.runtime.paths import ROOT_PROJECT_SLUG, BrainPaths
from protean.sleep import evidence as sleep_evidence
from protean.state.enums import TerminalState
from tests.runtime import stubs

SLUG = "workload"


def _run(brain: Path, workspace: Path, mailbox, *, task_id: str, planner, **kwargs):
    return start(
        brain,
        "finish it",
        stubs.planner_layer(planner),
        mailbox=mailbox,
        workspace_path=str(workspace),
        task_id=task_id,
        max_ticks=1,
        **kwargs,
    )


def _state_of(brain: Path, task_id: str):
    """The committed state, through the resume ladder that would refuse a bad registration."""
    return load_task(BrainPaths(root=brain).task(task_id)).state


# --------------------------------------------------------------------------------------
# Written at task open
# --------------------------------------------------------------------------------------


def test_a_task_that_names_no_project_opens_under_the_root_slug(
    brain: Path, workspace: Path, mailbox
) -> None:
    """A projectless root still accumulates evidence — the arm the wet oracle exercises."""
    outcome = _run(brain, workspace, mailbox, task_id="task-root", planner=stubs.finishing_planner)
    assert outcome.terminal is TerminalState.DONE

    state = _state_of(brain, "task-root")
    assert project_slug(state) == ROOT_PROJECT_SLUG
    assert state.extensions[PROJECT_EXTENSION].version == PROJECT_EXTENSION_VERSION


def test_the_named_project_rides_the_extension_registry_and_sleep_reads_it_back(
    brain: Path, workspace: Path, mailbox
) -> None:
    """`BrainState.extensions` under a `project` namespace, and no top-level shape change.

    The runtime→sleep join is the same run read once more (**D10-7, resolved**):
    `ProjectExtension` forbids an extra field, so the slug rides its `payload`, and
    `evidence._project_of()` reads it from there — off the committed checkpoint, not off the
    loaded state.
    """
    _run(
        brain,
        workspace,
        mailbox,
        task_id="task-named",
        planner=stubs.finishing_planner,
        project=SLUG,
    )
    state = _state_of(brain, "task-named")

    extension = state.extensions[PROJECT_EXTENSION]
    assert extension.name == PROJECT_EXTENSION
    assert extension.payload == {PROJECT_SLUG_FIELD: SLUG}
    assert project_slug(state) == SLUG
    # **Re-based by build A.1.i**: the registry gained its second namespace, `workspace`, which
    # `engine.start` writes when a task is handed one (`the build specification (not in this mirror)`
    # § Deliverable 4, row G5 (d), folded: S-i50). `_run` above hands one, so both namespaces are
    # registered here — and the claim this row makes is unchanged: adaptation is data, so a task
    # extends state by registering a namespace and `BrainState` gains no top-level field.
    assert set(state.extensions) == {PROJECT_EXTENSION, WORKSPACE_EXTENSION}

    payload = stubs.committed_state(BrainPaths(root=brain).task("task-named"))
    block = payload["state"]["extensions"][PROJECT_EXTENSION]
    assert block["payload"][PROJECT_SLUG_FIELD] == SLUG
    assert PROJECT_SLUG_FIELD not in block
    assert sleep_evidence._project_of(payload["state"]) == SLUG


def test_the_slug_survives_an_administrative_resume(
    brain: Path, workspace: Path, mailbox
) -> None:
    """Restored on resume: the checkpoint carries it, and `--abandon` rewrites it unchanged."""
    _run(brain, workspace, mailbox, task_id="task-open", planner=stubs.asking_planner("which project?"), project=SLUG)
    assert project_slug(_state_of(brain, "task-open")) == SLUG

    outcome = resume(brain, None, mailbox=mailbox, abandon=True)
    assert outcome.refusal is None
    assert project_slug(_state_of(brain, "task-open")) == SLUG


def test_a_state_registering_no_namespace_reads_as_the_root_slug() -> None:
    """The reader's own fallback, for a checkpoint written before this build."""
    from protean.state.brain_state import BrainState

    assert project_slug(BrainState(task_id="task-x", tick=0)) == ROOT_PROJECT_SLUG


# --------------------------------------------------------------------------------------
# The CLI surface
# --------------------------------------------------------------------------------------


def test_the_run_verb_declares_project_with_the_root_default_and_refuses_a_non_slug() -> None:
    """The flag's parse, both ways: what it defaults to and accepts, and what it will not take.

    A slug names a folder under `brain/projects/`, so it is checked before anything runs.
    """
    from protean.cli import build_parser

    parsed = build_parser().parse_args(["run", "a goal"])
    assert parsed.project == ROOT_PROJECT_SLUG
    assert build_parser().parse_args(["run", "a goal", "--project", SLUG]).project == SLUG

    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "a goal", "--project", "../escape"])


def test_the_run_handler_hands_the_slug_to_the_engine(brain: Path, monkeypatch) -> None:
    """The wire between the flag and the task: a flag the handler dropped would be inert."""
    from protean import cli
    from protean.runtime import engine

    seen: dict[str, object] = {}

    def _capture(root, goal, layer, **kwargs):
        seen.update(kwargs)
        seen["goal"] = goal
        raise SystemExit(0)

    monkeypatch.setattr(engine, "start", _capture)
    with pytest.raises(SystemExit):
        cli.main(["--brain", str(brain), "run", "a goal", "--project", SLUG])

    assert seen["goal"] == "a goal"
    assert seen["project"] == SLUG


# --------------------------------------------------------------------------------------
# The two spellings of one namespace
# --------------------------------------------------------------------------------------


def test_the_runtime_and_sleep_name_the_same_namespace() -> None:
    """`protean.runtime` may not import `protean.sleep`, so the two constants are pinned here."""
    assert PROJECT_EXTENSION == sleep_evidence.PROJECT_EXTENSION
    assert PROJECT_SLUG_FIELD == sleep_evidence.PROJECT_SLUG_FIELD
