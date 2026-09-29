"""Fixtures for the cortex battery: a throwaway brain root, the ladder's own weights, a layer.

`the build specification (not in this mirror)` § Deliverable 6 and § Deliverable 7. Every test runs against a
**copy** of the tracked seed tree, and every threshold a test needs is read from that copy's own
`weights.yaml` — never restated here, which is the same rule the fixtures under `fixtures/` are
held to and the reason a retuned weights file cannot silently desynchronise the battery from the
runtime.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from protean import config
from protean.brain.folders import load_weights
from protean.cortex.ladder import LadderWeights
from protean.cortex.calls import CallDesks, parse_plan
from protean.cortex.layer import build_layer, build_live_layer
from protean.cortex.scenario import load_scenario, script_path
from protean.cortex.scripts import load_script
from protean.mailbox.files import FileMailbox, build as build_mailbox
from protean.runtime import engine
from protean.runtime.paths import BrainPaths
from protean.state.enums import Escalation, GoalStatus, NodeName, TrapDetector
from protean.state.primitives import GoalItem, TrapScalar
from protean.state.seats import WaveMember
from protean.state.workspace import (
    DirectorRequest,
    LatestOutputs,
    ManagerRequest,
    Workspace,
)
from tests.cortex import fake_cli
from tests.runtime.stubs import seed_brain

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The scenario this battery drives end to end, and the unit its script mints.
STUCK_SCENARIO = "stuck"
STUCK_UNIT_ID = "u-stuck-1"

#: Build 1's own recording shim and the log it writes when `PROTEAN_SHIM_LOG` does **not** point
#: it elsewhere. A module that drives no process at all reads the second directly (`assert_dry()`);
#: a case that wants the shim armed in front of a stand-in takes `arm_the_shim()`, which redirects
#: the log into the test's own tree and leaves the checkout's copy untouched.
SHIM_DIR = REPO_ROOT / "tests" / "shim"
SHIM_LOG = SHIM_DIR / "invocations.log"

#: The kinds `fixtures/calls/kinds/wave_kinds.yaml` defines, named so a case can say which
#: arithmetic it is driving; **the numbers themselves are read off the seed** in every assertion,
#: never off this table. `UNDER` sums to one cent below `spawn_max_wave_usd`, `OVER` to one cent
#: above, and `WIDER` is `UNDER` plus a fifth member the width bound refuses whatever the sum is.
ALPHA, BETA, GAMMA = "fixture_alpha", "fixture_beta", "fixture_gamma"
DELTA, EPSILON, ZETA = "fixture_delta", "fixture_epsilon", "fixture_zeta"
READER = "fixture_reader"
UNDER = (ALPHA, BETA, GAMMA, EPSILON)
OVER = (ALPHA, BETA, GAMMA, DELTA)
WIDER = (ALPHA, BETA, GAMMA, EPSILON, ZETA)


@pytest.fixture()
def brain(tmp_path: Path) -> Path:
    """A throwaway brain root seeded from the tracked tree."""
    return seed_brain(REPO_ROOT / "brain", tmp_path / "brain")


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """The task's throwaway workspace — created and destroyed with the test."""
    path = tmp_path / "workspace"
    path.mkdir()
    return path


@pytest.fixture()
def mailbox(brain: Path) -> FileMailbox:
    """The mailbox layer, so a `stuck` raise has somewhere to land."""
    return build_mailbox(brain)


@pytest.fixture()
def cortex_weights(brain: Path) -> Mapping[str, Any]:
    """`brain/nodes/cortex/weights.yaml` — the ladder's counts, read from the file that owns them."""
    return load_weights(config.node_dir(str(NodeName.CORTEX), brain) / "weights.yaml")


@pytest.fixture()
def monitor_weights(brain: Path) -> Mapping[str, Any]:
    """`brain/nodes/anterior_cingulate/weights.yaml` — the trap and streak thresholds."""
    return load_weights(
        config.node_dir(str(NodeName.ANTERIOR_CINGULATE), brain) / "weights.yaml"
    )


@pytest.fixture()
def ladder_weights(brain: Path) -> LadderWeights:
    """The three counts the router reads, loaded the way the router loads them."""
    return LadderWeights.load(brain)


@pytest.fixture()
def scenario():
    """The hand-authored `stuck` scenario: its goal and its responders."""
    return load_scenario(STUCK_SCENARIO)


@pytest.fixture()
def stuck_layer(brain: Path, scenario):
    """A seat layer over the stuck scenario's responders and this root's ladder counts."""
    return build_layer(root=brain, script=scenario.script)


@pytest.fixture()
def script_for():
    """Load any hand-authored seat script by stem."""

    def _load(stem: str):
        return load_script(script_path(stem))

    return _load


# --------------------------------------------------------------------------------------
# The recording shim: armed in front of a stand-in, or read where it would have written
# --------------------------------------------------------------------------------------


def assert_dry() -> None:
    """The shim's log stays zero bytes, which is what "dry throughout" means physically.

    Read at the shim's own default path, where an un-redirected invocation would have landed.
    """
    size = SHIM_LOG.stat().st_size if SHIM_LOG.exists() else 0
    assert size == 0, f"the recording shim must never fire, and it logged {size} bytes"


def arm_the_shim(patch, log: Path) -> Path:
    """The recording shim **first** on `PATH`, its log created empty before the run.

    So "zero bytes" is a read and not an absence — and the control that fires it on purpose is
    what makes the read mean anything (row G5). The shim goes in front of whatever a fixture has
    already put on `PATH`, so a spawn that should never happen lands in this log rather than in a
    stand-in's recording; the log is the test's own file, so the checkout's copy stays untouched.
    """
    log.write_text("", encoding="utf-8")
    patch.setenv("PROTEAN_SHIM_LOG", str(log))
    patch.setenv("PATH", f"{SHIM_DIR}{os.pathsep}{os.environ.get('PATH', '')}")
    return log


@pytest.fixture()
def shim_log(tmp_path: Path, monkeypatch) -> Path:
    """`arm_the_shim()` as a fixture, on a log of this test's own."""
    return arm_the_shim(monkeypatch, tmp_path / "shim-invocations.txt")


# --------------------------------------------------------------------------------------
# Shared builders — one open goal, and the shapes built around it
#
# Five cortex modules each carried the same three-line `Workspace` around one open goal, and four
# of them the same request, member and trap scalar on top of it. They are here once so a contract
# change lands in one place; every value a copy varied is a keyword, so nothing here is narrower
# than the copy it replaced.
# --------------------------------------------------------------------------------------


def one_goal(goal_id: str, *, text: str = "reconcile", **overrides: Any) -> GoalItem:
    """One open goal, opened at tick zero and with no progress since."""
    payload: dict[str, Any] = {
        "id": goal_id,
        "text": text,
        "status": GoalStatus.OPEN,
        "opened_at_tick": 0,
        "last_progress_tick": 0,
    }
    payload.update(overrides)
    return GoalItem(**payload)


def one_goal_workspace(
    task_id: str,
    *,
    tick: int = 4,
    text: str = "reconcile",
    goal: GoalItem | None = None,
    **latest: Any,
) -> Workspace:
    """A `Workspace` carrying exactly one open goal, `<task_id>-g1` unless one is handed in.

    Keyword arguments beyond those are the `latest` slots, which is how a router case names the
    outputs a tick has already produced.
    """
    return Workspace(
        task_id=task_id,
        tick=tick,
        goals=[goal if goal is not None else one_goal(f"{task_id}-g1", text=text)],
        latest=LatestOutputs(**latest),
    )


def manager_request(workspace: Workspace, **overrides: Any) -> ManagerRequest:
    """The manager's request over that workspace; `escalation` defaults to the empty unit stack."""
    payload: dict[str, Any] = {
        "workspace": workspace,
        "escalation": Escalation.EMPTY_UNIT_STACK,
    }
    payload.update(overrides)
    return ManagerRequest(**payload)


def director_request(workspace: Workspace) -> DirectorRequest:
    """The director's request: the workspace and nothing else (§ Deliverable 2, folded: S-11)."""
    return DirectorRequest(workspace=workspace)


def wave_member(
    kind: str = "surgeon",
    unit_id: str = STUCK_UNIT_ID,
    admitted_ref: str = "admitted:e-1",
) -> WaveMember:
    """What replaced `ExecutorRequest` — kind, unit id, admitted reference, and **no path**.

    No workspace either, and it is not a seat request.
    """
    return WaveMember(kind=kind, unit_id=unit_id, admitted_ref=admitted_ref)


def trap_scalar(
    detector: TrapDetector,
    *,
    unit_id: str = STUCK_UNIT_ID,
    fired: bool = True,
    value: float | None = None,
    threshold: float = 2.0,
    weight_key: str = "rut_ticks",
) -> TrapScalar:
    """One trap scalar. `value` defaults to one side or the other of `threshold`, per `fired`."""
    return TrapScalar(
        detector=detector,
        value=(3.0 if fired else 0.0) if value is None else value,
        threshold=threshold,
        weight_key=weight_key,
        fired=fired,
        unit_id=unit_id,
    )


# --------------------------------------------------------------------------------------
# The seat root — the stand-in on `PATH` and the tracked seed pointed at it
# --------------------------------------------------------------------------------------


def seeded_live_root(base: Path, patch, responses=(), **install_keys) -> tuple[Path, Path]:
    """A brain root whose seat binary is the stand-in, and the directory it records into.

    The smaller half of what the seat batteries need: `test_live_seat.py` drives the **root**
    through the engine and wants nothing else, while `test_live_invoke.py` builds a `LiveSeat` on
    top of this and opens its task. `install_keys` are `fake_cli.install()`'s own levers.
    """
    binaries = fake_cli.install(base / "bin", responses, **install_keys)
    fake_cli.on_path(patch, binaries)
    return fake_cli.seed_live_root(base / "brain"), binaries


# --------------------------------------------------------------------------------------
# The wave root — one factory for both spawn batteries
# --------------------------------------------------------------------------------------


def wave_root(
    base: Path,
    patch,
    kinds=UNDER,
    *,
    task: str,
    unit: str,
    plans: int = 1,
    container: str = fake_cli.KINDS_WAVE,
    narrative: str | None = None,
    denials=(),
    delegate_answer: str | None = None,
    member_sleeps=(),
    writes_in_cwd: str | None = None,
    spawn_child_seconds: float | None = None,
    detached_child_seconds: float | None = None,
    workspace: Path | str | None = None,
) -> SimpleNamespace:
    """A fixture-kind brain root, its stand-in, and the task workspace a spawn is granted.

    The union of what `test_wave.py` and `test_spawn_audit.py` each built for themselves: the
    plan the manager answers with, one scripted return per member, the stand-in's levers, and the
    root the loader really resolves the container off.

    `evidence=` names the stand-in's own directory as a `runtime.spawn_writable` entry (D5-5,
    folded: S-i37) — which is also what makes it the tree `wrote_outside_workspace` is read on:
    under the inverted per-spawn profile the stand-in writes its argv, its stdin, its cwd and its
    environment beside `$0` on every invocation, so a row that closes on those files would
    otherwise be closing on files the kernel refused to let it write, and a spawn that ran really
    did write under a granted tree that is not the workspace.

    `delegate_answer` names the **delegate kind** whose answer the stand-in should carry as its
    keyless fallback, which is how a case drives a delegate beside the wave.
    """
    extra = {"permission_denials": list(denials)} if denials else {}
    answer = (
        fake_cli.envelope(
            {
                "kind": delegate_answer,
                "information": narrative if narrative is not None else "read it",
                "cited_ids": [],
            },
            **extra,
        )
        if delegate_answer is not None
        else None
    )
    binaries = fake_cli.install(
        base / "bin",
        [fake_cli.wave_plan(unit, f"{task}-g1", kinds)] * plans,
        members=fake_cli.member_answers(kinds, unit, narrative=narrative, denials=denials),
        answer=answer,
        member_sleeps=member_sleeps,
        writes_in_cwd=writes_in_cwd,
        spawn_child_seconds=spawn_child_seconds,
        detached_child_seconds=detached_child_seconds,
    )
    fake_cli.on_path(patch, binaries)
    root = fake_cli.seed_kinds_root(base / "brain", container, evidence=binaries)
    granted = base / "clone" if workspace is None else Path(workspace)
    if workspace is None:
        granted.mkdir(exist_ok=True)
    return SimpleNamespace(
        root=root,
        binaries=binaries,
        workspace=granted.resolve() if granted.exists() else granted,
        seats=fake_cli.seats_of(root),
        kinds=tuple(kinds),
    )


# --------------------------------------------------------------------------------------
# Driving one of those roots: the layer, the tick, and the paths it writes
# --------------------------------------------------------------------------------------


def delegate_plan(kind: str = READER, *, question: str = "what does the clone hold?"):
    """One delegate call planned for one outer node, through the loader a fixture plan is read by.

    `hippocampus` is **pre-cortex** — second in `NODE_ORDER` — so its delegate's journal entry
    precedes the wave's members', which is the case the landed FIFO match gets wrong.
    """
    return parse_plan(
        [
            {
                "node": str(NodeName.HIPPOCAMPUS),
                "type": "delegate",
                "payload": {"kind": kind, "question": question},
            }
        ]
    )


def live_layer_for(world, *, plan=None):
    """The production layer, with `node_calls` attached where a case needs the delegate arm.

    Since A.2.i, `build_live_layer()` attaches `node_calls` too, over the same `spawns` seam
    (`the build specification (not in this mirror)` § Deliverable 1) — this helper predates it and still
    attaches a desk explicitly, so a case that needs a **delegate beside a member** keeps its own
    plan in hand rather than the shipping policy's.
    """
    layer = build_live_layer(root=world.root)
    if plan is None:
        return layer
    return dataclasses.replace(
        layer,
        node_calls=CallDesks(port=layer.port, plan=plan, spawns=layer.spawns),
    )


def drive(world, *, goal: str, task: str, plan=None, workspace=None, max_ticks: int = 1):
    """One live tick through the production layer — `build_live_layer()`'s own, seams and all."""
    layer = live_layer_for(world, plan=plan)
    named = world.workspace if workspace is None else workspace
    outcome = engine.start(
        world.root,
        goal,
        layer,
        mailbox=build_mailbox(world.root),
        workspace_path="" if named is None else str(named),
        task_id=task,
        max_ticks=max_ticks,
    )
    return layer, outcome


def task_paths(root, task: str):
    """The task's own paths, off a brain root handed either bare or inside a wave-root namespace."""
    return BrainPaths(root=root if isinstance(root, Path) else root.root).task(task)
