"""Fixtures for the runtime battery: a throwaway brain root and a hand-driven seat layer.

`the build specification (not in this mirror)` § Deliverable 7. Every test here runs against a **copy** of
the tracked seed tree in a temp directory — the repo's own `brain/` is read-only to this
battery, which is the rule `protean dry` enforces by construction for a scenario run.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest

from protean.runtime import cycle as cycle_module
from protean.runtime.engine import build_context, new_state
from protean.runtime.journal import load as load_journal
from protean.state.enums import CallType, Escalation, ExpectationKind, Tier
from protean.state.primitives import Expectation, WorkUnit
from protean.state.seats import ExecutorSummary, ManagerPlan
from protean.state.primitives import WorkspaceObservation
from tests.runtime import stubs

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The one unit every simple scenario plans, so a test can name it without minting an id.
UNIT_ID = "u1"
EXPECTATION_ID = "e1"

#: A committer that does not depend on the machine's git configuration.
IDENTITY = (
    "-c", "user.name=protean tests",
    "-c", "user.email=tests@protean.invalid",
    "-c", "commit.gpgsign=false",
)


def git(cwd: Path, *arguments: str) -> str:
    """`git` in one work tree, under this battery's own identity rather than the machine's."""
    return subprocess.run(
        ["git", "-C", str(cwd), *IDENTITY, *arguments],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def build_clone(base: Path) -> Path:
    """A clone with one upstream commit on a remote-tracking ref and one commit of its own.

    The upstream commit being on a remote-tracking ref is the whole point: it is what makes
    "the run's own commits" a reading rather than the branch's whole history.
    """
    source = base / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    (source / "README.md").write_text("upstream\n", encoding="utf-8")
    git(source, "add", "-A")
    git(source, "commit", "-qm", "upstream")

    workspace = base / "clone"
    subprocess.run(["git", "clone", "-q", str(source), str(workspace)], check=True)
    git(workspace, "checkout", "-qb", "protean/run")
    (workspace / "answer.txt").write_text("the run wrote this\n", encoding="utf-8")
    git(workspace, "add", "-A")
    git(workspace, "commit", "-qm", "the run's work")
    (workspace / "scratch.txt").write_text("uncommitted\n", encoding="utf-8")
    return workspace


#: A firing threshold no cheap check in this battery can reach, so the node declines. It is
#: written into a throwaway root; nothing in `brain/` or in a fixture carries it.
DECLINE = 99.0


def reopen(brain: Path, task: str, context, workspace: Path):
    """Re-open the task's folders so a weights write this pass made is in force next pass."""
    return build_context(brain, task, context.layer, workspace_path=str(workspace))


def entries_of(context, tick: int):
    """Every journal entry this tick wrote, in the order the file holds them."""
    return load_journal(context.paths.journal(tick))


def call_entries_of(context, tick: int):
    """This tick's journalled **calls**, in the order they were written."""
    return [entry for entry in entries_of(context, tick) if entry.is_call()]


@pytest.fixture()
def clone(tmp_path: Path) -> Path:
    """`build_clone()` for a test that writes inside the work tree."""
    return build_clone(tmp_path)


@pytest.fixture(scope="module")
def shared_clone(tmp_path_factory) -> Path:
    """`build_clone()` once for a module — **read-only** to every consumer.

    The clone is the slowest single call in this battery (four git spawns), and the tests that
    read a run's commits, its status letters or its bundled product never write into the tree. A
    test that does write inside it takes the function-scoped `clone` instead.
    """
    return build_clone(tmp_path_factory.mktemp("clone"))


@pytest.fixture()
def one_reading_per_source(monkeypatch):
    """Freeze the two things a **process** decides rather than a tick: the clock and the uuid.

    The tick's wall seconds land in the checkpoint and in homeostasis's own prediction, and a
    session id is minted from `uuid4` — one per task for the seats and a fresh one per
    session-less call (folded: S-A31). Neither is a fact about a replay, so two runs of one
    fixture would differ on them however correct the restore was, and a byte-identity claim over
    two passes would be a claim about a clock and an id generator.

    **It does not weaken what the comparison can catch**, because a re-made call would return
    the *same scripted answer* and could never have been caught by comparing bytes: that a
    restored call reaches no port is asserted directly, off the port's own record of what it was
    asked. Everything else about the tick is derived — the task id, the goal id, the episode id.
    """
    monkeypatch.setattr(cycle_module.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=0x5EA7CA115EA7CA115EA7CA115EA7CA11))


@pytest.fixture()
def brain(tmp_path: Path) -> Path:
    """A throwaway brain root seeded from the tracked tree."""
    return stubs.seed_brain(REPO_ROOT / "brain", tmp_path / "brain")


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """The task's throwaway workspace — created and destroyed with the test."""
    path = tmp_path / "workspace"
    path.mkdir()
    return path


def plan_then_execute_pair(workspace: Path):
    """A planner that mints one unit with one predicate, and an executor that satisfies it.

    The plain function behind the `plan_then_execute` fixture, so a **module-scoped** fixture
    that owns its own workspace can build the same pair.
    """
    target = "out.txt"

    def _planner(request) -> ManagerPlan:
        return ManagerPlan(
            tick=request.workspace.tick,
            units=[
                WorkUnit(
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
            ],
        )

    def _executor(request) -> ExecutorSummary:
        return ExecutorSummary(
            tick=request.admitted.tick,
            unit_id=request.unit.id,
            narrative="wrote it",
            observations=[
                WorkspaceObservation(
                    path=target, exists=True, size_bytes=11, content_hash="hash-1"
                )
            ],
            cited_ids=[item.admitted_id for item in request.admitted.admitted],
        )

    return _planner, _executor


@pytest.fixture()
def plan_then_execute(workspace: Path):
    """`plan_then_execute_pair()` over the test's own throwaway workspace."""
    return plan_then_execute_pair(workspace)


@pytest.fixture()
def layer(plan_then_execute):
    """The router/port pair the runtime is handed, recording every selection and call."""
    planner, executor = plan_then_execute
    seat = stubs.StubSeat(
        responder=stubs.request_keyed(
            {
                str(Tier.MANAGER): planner,
                str(CallType.DISPATCH): executor,
                str(Tier.DIRECTOR): lambda request: {"tick": request.workspace.tick},
            }
        )
    )
    router = stubs.StubRouter(rule=stubs.manager_then_dispatch(UNIT_ID))
    return stubs.layer(router, seat), router, seat


@pytest.fixture()
def mailbox(brain: Path) -> stubs.StubMailbox:
    """The mailbox's file half, driven by hand until `src/protean/mailbox/` lands."""
    return stubs.StubMailbox(root=brain)


@pytest.fixture()
def started(brain: Path, workspace: Path, layer, mailbox):
    """A task opened at tick 0: its context and its state, before any tick has run."""
    seat_layer, router, seat = layer
    context = build_context(
        brain,
        "task-test",
        seat_layer,
        mailbox=mailbox,
        workspace_path=str(workspace),
    )
    state = new_state("task-test", "write out.txt", context)
    return context, state, router, seat


@pytest.fixture()
def escalation_planner():
    """A planner request always names the rung it was called on."""
    return Escalation.EMPTY_UNIT_STACK
