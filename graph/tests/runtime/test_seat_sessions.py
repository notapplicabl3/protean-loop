"""The seat session handles across a boundary, a resume, and a new task — and `--brain`'s reach.

`the build specification (not in this mirror)` § Deliverable 6 → *Fresh per task, cached within task*: "each
tier's adapter owns one session handle for the life of a task ... checkpointed in
`BrainState.seat_sessions` so a resume in a new process reuses them". W3 built the in-process
half and could not build the persisted half — every writer of `BrainState` is the runtime's
(`plans/deltas/build1-foundation-dispatch-7.md`, D7-7). This battery is the persisted half's
claim, made on **on-disk** evidence: the handles are read back out of the checkpoint file rather
than off the layer that minted them.

**The resume is a stand-in for a new process, not for a new tick.** Each resume below is handed
a `SeatLayer` built fresh from `protean.cortex.layer.build_layer()`, whose session book has
never seen the task; the only thing that can carry the three handles into it is the checkpoint.
`SessionBook.minted_tasks` is the discriminator — a restored book minted nothing.

The last test is D7-3's known divergence closed: `protean run --brain PATH` resolved the task's
root from the flag while the cortex layer read `$PROTEAN_BRAIN`, so a flagged run could read its
ladder counts from a different tree than the one it wrote its checkpoints into.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protean import cli, config
from protean.cortex import layer as cortex_layer
from protean.cortex.layer import DEFAULT_SCRIPT_STEM, build_layer
from protean.cortex.scenario import script_path
from protean.cortex.scripts import load_script
from protean.runtime import engine
from protean.runtime.paths import BrainPaths
from tests.runtime import stubs
from tests.runtime.conftest import REPO_ROOT

#: The goal the packaged default script plans, does and closes.
GOAL = "write notes.md"
TASK_ID = "task-sessions"


def scripted_layer(root: Path):
    """A real cortex layer over the packaged default script — the form a scenario runner uses.

    The script is passed explicitly rather than resolved from `$PROTEAN_SEAT_SCRIPT`, so this
    battery cannot be steered by the environment.
    """
    return build_layer(root=root, script=load_script(script_path(DEFAULT_SCRIPT_STEM)))


def checkpointed_handles(root: Path, task_id: str) -> dict[str, str]:
    """`BrainState.seat_sessions` as the checkpoint file on disk carries it."""
    payload = json.loads(
        BrainPaths(root=root).task(task_id).checkpoint.read_text(encoding="utf-8")
    )
    return payload["state"]["seat_sessions"]


@pytest.fixture()
def ticked(brain: Path, workspace: Path, mailbox):
    """One tick of a real scripted layer, committed. The battery's subject."""
    first = scripted_layer(brain)
    engine.start(
        brain,
        GOAL,
        first,
        mailbox=mailbox,
        workspace_path=str(workspace),
        task_id=TASK_ID,
        max_ticks=1,
    )
    return first


# --------------------------------------------------------------------------------------
# (a) the boundary carries them
# --------------------------------------------------------------------------------------


def test_one_tick_checkpoints_one_handle_per_tier(brain: Path, ticked):
    """Three handles, keyed by tier, on disk — not three keys the validator would refuse."""
    handles = checkpointed_handles(brain, TASK_ID)
    print(f"    [D7-7] checkpointed handles: {json.dumps(handles, sort_keys=True)}")
    assert sorted(handles) == sorted(config.TIERS)
    assert len(set(handles.values())) == len(config.TIERS), (
        "one session per tier, never one shared — and the tiers are the two A.1 left"
    )
    assert handles == ticked.sessions.for_task(TASK_ID), "the layer's own three, not a copy"


# --------------------------------------------------------------------------------------
# (b) a resume in a fresh layer reuses them
# --------------------------------------------------------------------------------------


def test_a_resume_in_a_fresh_layer_reuses_the_checkpointed_handles(
    brain: Path, workspace: Path, mailbox, ticked
):
    """A new process's layer minted nothing: it ran the tick on the three the checkpoint held."""
    before = checkpointed_handles(brain, TASK_ID)

    fresh = scripted_layer(brain)
    assert fresh.sessions.for_task(TASK_ID) == {}, "a fresh book has never seen this task"

    engine.resume(
        brain, fresh, mailbox=mailbox, workspace_path=str(workspace), max_ticks=1
    )

    after = checkpointed_handles(brain, TASK_ID)
    # **The seat calls only** (`the build specification (not in this mirror)` § Deliverable 2,
    # folded: S-A31): a think, escalate, delegate or **dispatch member** is session-less — it
    # mints a fresh `--session-id` per invocation and writes no `seat_sessions` entry — so the
    # handles a resume is asserted to have carried are the two tiers' and no others.
    used = sorted(
        {handle for addressee, handle in fresh.port.calls if addressee in config.TIERS}
    )
    print(f"    [D7-7] handles the resumed layer called on: {used}")
    assert after == before, "the resumed run carried the three rather than minting three"
    assert fresh.sessions.minted_tasks == [], "a restored book mints nothing"
    assert used, "the resumed tick called the seat at all"
    assert set(used) <= set(before.values())


# --------------------------------------------------------------------------------------
# (c) a new task gets three new ones
# --------------------------------------------------------------------------------------


def test_a_new_task_mints_three_handles_of_its_own(
    brain: Path, workspace: Path, tmp_path: Path, mailbox, ticked
):
    """Per task, not per layer: the same layer opening a second task shares nothing with the first.

    One task per brain root, so the second task runs against its own copy of the same seed tree.
    """
    first = checkpointed_handles(brain, TASK_ID)

    second_root = stubs.seed_brain(REPO_ROOT / "brain", tmp_path / "brain-second")
    engine.start(
        second_root,
        GOAL,
        ticked,
        mailbox=stubs.StubMailbox(root=second_root),
        workspace_path=str(workspace),
        task_id="task-sessions-2",
        max_ticks=1,
    )

    second = checkpointed_handles(second_root, "task-sessions-2")
    print(f"    [D7-7] second task's handles: {json.dumps(second, sort_keys=True)}")
    assert sorted(second) == sorted(config.TIERS)
    assert set(second.values()).isdisjoint(first.values()), "a new task discards all three"
    assert ticked.sessions.minted_tasks == [TASK_ID, "task-sessions-2"]


# --------------------------------------------------------------------------------------
# D7-3: `--brain` and the cortex layer read one tree
# --------------------------------------------------------------------------------------


def test_run_points_the_cortex_layer_at_the_root_the_flag_named(
    brain: Path, tmp_path: Path, monkeypatch
):
    """`protean run --brain PATH` and a zero-argument `build()` resolve the same brain root."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv(config.BRAIN_ROOT_ENV, str(elsewhere))

    seen: list[Path] = []

    def _recording_build():
        seen.append(config.brain_root())
        return scripted_layer(config.brain_root())

    monkeypatch.setattr(cortex_layer, "build", _recording_build)
    code = cli.main(["--brain", str(brain), "run", GOAL])

    print(f"    [D7-3] root the layer resolved: {seen} (flag named {brain}); exit {code}")
    assert seen == [Path(str(brain)).resolve()], "the layer read the flagged root, not $PROTEAN_BRAIN"
    assert Path(str(elsewhere)).resolve() not in seen
