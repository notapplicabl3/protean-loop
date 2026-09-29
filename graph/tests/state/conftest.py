"""Fixtures and helpers shared by more than one module of the state battery.

Nothing here constructs a claim. What lands here is what two or more modules were each holding
their own copy of, and only where the copy was the *same* thing: the `git -C <checkout>` wrapper
(`test_contracts_frozen.py` and `test_brain_tree.py` both read the index rather than the working
tree), the tracked-and-seeded weights maps the brain-tree cases read, and `populated_state()` —
which `test_checkpoint.py` used to import out of `test_brain_state.py`, a shared fixture wearing
a test module's name, so that renaming one module broke the collection of the other.

`a planning record (not in this mirror)` § Slice: tests/state, rows T6 and T13.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from protean import config
from protean.state import (
    BrainState,
    CeilingOverrides,
    Constraint,
    ConstraintKind,
    CostCounters,
    GoalItem,
    LatestOutputs,
    Modulators,
    NodeName,
    OpenInterrupt,
    PathBaseline,
    ProjectExtension,
    ResolvedInterrupt,
    UnitObservation,
    WorkUnit,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every node folder's name, in the enum's order.
NODES = tuple(str(n) for n in NodeName)


def git(*arguments: str) -> str:
    """`git -C <checkout> …`, captured, raising on a non-zero exit.

    One wrapper for the two modules that read the repository itself: `test_contracts_frozen.py`
    diffs against build 1's landed commit, and the brain-tree cases read the *index* rather than
    the working tree. A command that stopped seeing the tree must fail here, never pass on an
    empty read, which is why `check=True`.
    """
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *arguments],
        capture_output=True, text=True, check=True,
    ).stdout


@pytest.fixture(scope="session")
def tracked_files() -> list[str]:
    """`git ls-files -- brain/` — the seed as the repository carries it, not as the disk holds it.

    **Why the index and not the working tree** (folded: S-62, ruling on dispatch-24 ledger D24-9,
    option 2). A live run opens on the repo's own brain root by design, and it writes its
    journals, checkpoints and mailbox there; every one of those paths is gitignored, so a walk of
    the working tree reads a run's state and a walk of the *index* cannot. What "the seed carries
    no history" has always meant is what git tracks, and this is that claim measured directly —
    the same re-basing S-20 applied to build 1's M24 grep in
    `tests/intake/test_policy_home_license.py`.

    One listing for the whole session: the pathspec narrowings the cases want (`brain/projects/`)
    are prefixes of this one, so they are filtered in-process rather than paid for as another
    subprocess.
    """
    return sorted(line for line in git("ls-files", "--", "brain/").splitlines() if line.strip())


@pytest.fixture(scope="session")
def seed_weights(brain_seed_root: Path) -> dict[str, dict]:
    """node → the parsed `weights.yaml` **on disk**, every node's file read and parsed once.

    Read-only to every consumer: the seed tree is the checkout's own, and `protean dry` is what
    copies it before anything writes.
    """
    return {
        node: yaml.safe_load(
            (brain_seed_root / "nodes" / node / "weights.yaml").read_text()
        )
        or {}
        for node in NODES
    }


@pytest.fixture(scope="session")
def tracked_weights() -> dict[str, dict]:
    """node → `git show :brain/nodes/<node>/weights.yaml`, the **staged blob** rather than the
    file on disk.

    The same re-basing as `tracked_files` and for the same reason (folded: S-62, folded: A1-12):
    from build 3 the offline sleep graph re-values keys in the working tree, so a claim about
    *the seed* is a claim about what the repository carries. `:<path>` is stage 0 of the index,
    which is what `git ls-files` lists.

    Its own map, deliberately kept apart from `seed_weights`: the index/working-tree distinction
    is the whole of what the `rut_ticks` case asserts, and one merged map would erase it.
    """
    return {
        node: yaml.safe_load(git("show", f":brain/nodes/{node}/weights.yaml")) or {}
        for node in NODES
    }


def populated_state() -> BrainState:
    """A state with every group non-empty — what the round-trip and the checkpoint tests use."""
    return BrainState(
        task_id="task-round-trip",
        tick=7,
        goals=[GoalItem(id="g-1", text="write the note", opened_at_tick=0, last_progress_tick=5)],
        units=[WorkUnit(id="u-1", goal_id="g-1", intent="create notes.md")],
        latest=LatestOutputs(),
        unit_windows={"u-1": [UnitObservation(tick=6, unit_revision=0, change_bytes_total=12)]},
        path_baselines={
            "u-1": {"notes.md": PathBaseline(size_bytes=12, content_hash="ab", tick=6)}
        },
        window_len=13,
        trap_dismissals={"u-1": {"forming": 6}},
        open_interrupts=[
            OpenInterrupt(
                id="task-round-trip-t7-manager",
                kind="question",
                raised_by="manager",
                raised_at_tick=7,
                raised_at="tick 7",
                path="mailbox/open/task-round-trip-t7-manager.md",
                question="which of the two shapes did you mean?",
            )
        ],
        resolved_interrupts=[
            ResolvedInterrupt(
                id="task-round-trip-t3-thalamus",
                kind="question",
                raised_by="thalamus",
                raised_at_tick=3,
                resolved_at_tick=5,
                question="admit the older episode?",
                answer="yes",
            )
        ],
        seat_sessions={t: f"session-{t}" for t in config.TIERS},
        cost=CostCounters(tokens=1200, wall_seconds=31.5, errors=0, ticks=7),
        ceiling_overrides=CeilingOverrides(extra_ticks=20, set_at_tick=6),
        modulators=Modulators(reward_error=-0.5, arousal=0.25, confidence=0.75),
        constraints=[
            Constraint(kind=ConstraintKind.PATH_SCOPE, arguments={"root": "ws"}, set_at_tick=1)
        ],
        terminal=None,
        extensions={"workload": ProjectExtension(name="workload", version=1, payload={"board": "us"})},
    )
