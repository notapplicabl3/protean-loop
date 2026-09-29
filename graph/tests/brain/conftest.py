"""Fixtures for the brain-folder battery: a throwaway seed tree and one hand-driven task.

`the build specification (not in this mirror)` § Deliverable 4. Every test here runs against a **copy** of
the tracked seed tree in a temp directory — the repo's own `brain/` is read-only to this
battery, which is the rule `protean dry` enforces by construction for a scenario run.

**The seams come from the runtime battery's own stubs** (`tests/runtime/stubs.py`): the seat
port, the router and the mailbox already have exactly one hand-driven implementation each, and
a second one here would be a second thing for a scripted seat to drift from. `src/protean/
cortex/` and `src/protean/mailbox/` are a later order's.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protean import config
from protean.runtime.cycle import run_tick
from protean.runtime.engine import build_context, new_state
from protean.state.enums import CallType, Escalation, ExpectationKind, NodeName, Tier
from protean.state.primitives import Expectation, WorkUnit, WorkspaceObservation
from protean.state.seats import ExecutorSummary, ManagerPlan
from tests.conftest import REPO_ROOT
from tests.runtime import stubs

#: The one unit the scenario plans, and the one predicate it satisfies.
UNIT_ID = "u1"
EXPECTATION_ID = "e1"
TARGET = "out.txt"


@pytest.fixture()
def brain(tmp_path: Path) -> Path:
    """A throwaway brain root seeded from the tracked tree."""
    return stubs.seed_brain(REPO_ROOT / "brain", tmp_path / "brain")


@pytest.fixture()
def trace_root(tmp_path: Path) -> Path:
    """A brain root that is **only** the six trace files — no seed copy, nothing else.

    Every case that exercises the append path touches `node_dir(node, root)/trace.jsonl` and
    nothing else, so copying the whole seeded tree per case bought nothing (audit row N2). The
    claim that the *seeded* tree ships those six files, and ships them empty, keeps its own case
    on the real `brain` fixture at
    `tests/brain/test_trace.py::test_every_folder_starts_with_a_trace_file`.
    """
    root = tmp_path / "trace-root"
    for node in config.NODE_ORDER:
        folder = config.node_dir(node, root)
        folder.mkdir(parents=True)
        (folder / "trace.jsonl").touch()
    return root


def trace_path(brain: Path, node: NodeName | str) -> Path:
    """The one file the runtime appends to, under one node folder.

    One definition (audit row N11): `test_trace.py`, `test_firing_trace.py` and
    `test_prediction_invariant.py` each spelled it out, byte-identically.
    """
    return config.node_dir(str(node), brain) / "trace.jsonl"


def advance(context, state, ticks: int) -> list:
    """Run `ticks` passes of the tick loop, minting the tick number the way the runtime does.

    One definition (audit row N12): `test_prediction_invariant.py`, `test_folders.py` and
    `test_episodes.py` each carried the same three lines. The results are returned for the
    callers that read them and ignored by the ones that do not.
    """
    results = []
    for _ in range(ticks):
        state.tick += 1
        results.append(run_tick(context, state))
    return results


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """The task's throwaway workspace — created and destroyed with the test."""
    path = tmp_path / "workspace"
    path.mkdir()
    return path


def plan_then_execute():
    """A planner that mints one unit with one predicate, and an executor that satisfies it."""

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
                            arguments={"path": TARGET},
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
                    path=TARGET, exists=True, size_bytes=11, content_hash="hash-1"
                )
            ],
            cited_ids=[item.admitted_id for item in request.admitted.admitted],
        )

    return _planner, _executor


@pytest.fixture()
def layer():
    """The router/port pair the runtime is handed, recording every selection and call."""
    planner, executor = plan_then_execute()
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
def director_layer():
    """A router that answers `director` every tick — the tier the `stuck` ladder lands on."""
    seat = stubs.StubSeat(
        responder=stubs.request_keyed(
            {
                str(Tier.DIRECTOR): lambda request: {"tick": request.workspace.tick},
                str(Tier.MANAGER): lambda request: {"tick": request.workspace.tick},
                str(CallType.DISPATCH): lambda request: {
                    "tick": 0, "unit_id": request.unit.id, "narrative": "-"
                },
            }
        )
    )
    router = stubs.StubRouter(
        rule=stubs.always(stubs.SeatSelection(tier=Tier.DIRECTOR))
    )
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
        brain, "task-brain", seat_layer, mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-brain", "write out.txt", context)
    return context, state, router, seat


@pytest.fixture()
def escalation():
    """The rung a planner selection names — `ManagerRequest` refuses one without it."""
    return Escalation.EMPTY_UNIT_STACK
