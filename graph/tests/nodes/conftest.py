"""Fixtures for the five deterministic nodes: the real seed weights, and typed inputs.

`the build specification (not in this mirror)` § Deliverable 4. A node is a **pure callable from a typed
input model to a typed output model** (decision 25), so this battery needs no brain root, no
temp directory and no seat: it constructs the input model and calls the function.

**The weights come from the tracked seed tree, read-only.** That is deliberate rather than
convenient: § Deliverable 4 puts every threshold in `brain/nodes/<node>/weights.yaml` and
nowhere else, so a battery that invented its own numbers would pass against a node that had
quietly hardcoded a different one. Nothing here writes under `brain/`.
"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from protean import config
from protean.brain.folders import load_weights
from protean.state.enums import ExpectationKind, GoalStatus
from protean.state.primitives import (
    CeilingOverrides,
    CostCounters,
    Expectation,
    GoalItem,
    UnitObservation,
    WorkUnit,
)
from tests.conftest import BRAIN_SEED

TASK_ID = "task-n"
UNIT_ID = "u1"
GOAL_ID = "g1"


@pytest.fixture(scope="session")
def seed_weights() -> Mapping[str, Mapping[str, Any]]:
    """Every folder's `weights.yaml` as the runtime projects it. Read-only."""
    return {
        node: load_weights(config.node_dir(node, BRAIN_SEED) / "weights.yaml")
        for node in config.NODE_ORDER
    }


@pytest.fixture()
def monitor_weights(seed_weights) -> dict[str, Any]:
    """The anterior cingulate's file — every trap threshold and the streak threshold."""
    return dict(seed_weights["anterior_cingulate"])


@pytest.fixture()
def homeostasis_weights(seed_weights) -> dict[str, Any]:
    return dict(seed_weights["homeostasis"])


@pytest.fixture()
def hippocampus_weights(seed_weights) -> dict[str, Any]:
    return dict(seed_weights["hippocampus"])


@pytest.fixture()
def thalamus_weights(seed_weights) -> dict[str, Any]:
    return dict(seed_weights["thalamus"])


@pytest.fixture()
def gate_weights(seed_weights) -> dict[str, Any]:
    """The gate's file is the empty mapping, deliberately."""
    return dict(seed_weights["basal_ganglia"])


def goal(goal_id: str = GOAL_ID, *, status: GoalStatus = GoalStatus.OPEN) -> GoalItem:
    return GoalItem(
        id=goal_id, text="do the thing", status=status, opened_at_tick=0, last_progress_tick=0
    )


def unit(
    unit_id: str = UNIT_ID,
    *,
    irreversible: bool = False,
    paths: tuple[str, ...] = ("out.txt",),
    intent: str = "write the file",
) -> WorkUnit:
    return WorkUnit(
        id=unit_id,
        goal_id=GOAL_ID,
        intent=intent,
        irreversible=irreversible,
        expected=[
            Expectation(
                id=f"e{index}", kind=ExpectationKind.FILE_EXISTS, arguments={"path": path}
            )
            for index, path in enumerate(paths, start=1)
        ],
    )


def observation(
    tick: int,
    *,
    failed: tuple[str, ...] = (),
    passed: tuple[str, ...] = (),
    change: int = 0,
    vetoed: bool = False,
    abandoned: bool = False,
    uncited: float = 0.0,
    redirect_by: str | None = None,
) -> UnitObservation:
    """One committed row of a unit's window — the six detectors' only input."""
    return UnitObservation(
        tick=tick,
        unit_revision=0,
        failed_predicate_ids=list(failed),
        passed_predicate_ids=list(passed),
        change_bytes={"out.txt": change} if change else {},
        change_bytes_total=change,
        abandoned=abandoned,
        vetoed=vetoed,
        uncited_ratio=uncited,
        redirect_by=redirect_by,
    )


def cost(**overrides: Any) -> CostCounters:
    return CostCounters(**overrides)


def overrides(**kwargs: Any) -> CeilingOverrides:
    return CeilingOverrides(**kwargs)
