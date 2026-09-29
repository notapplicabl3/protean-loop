"""Row W2: the live layer behind build 1's unchanged port, end to end.

`the build specification (not in this mirror)` § Deliverable 1 and § Directional decisions 2 (the port that
does not change). Order W2's DoD row **W2**, clause by clause:

* `protean.cortex.layer.build()` takes **no argument** and returns a `SeatLayer` whose port
  satisfies `(tier, request) → SeatEnvelope`;
* `decode_seat_result()` is the **only** decode path, proven by one call over the wire and one
  journal restore producing byte-identical result models;
* the seat handles are checkpointed in `BrainState.seat_sessions` and reused across a resume in
  a new process **without minting**;
* a replayed tick restores the journalled envelope and **spawns no process**, proven by a
  recording shim whose log gains no entry.

**Two devices, both recording.** The stand-in binary in `tests/cortex/fake_cli` counts every
invocation in a file beside itself — the scrubbed environment cannot blind it — and build 1's
own `tests/shim/claude` is copied in beside it and put first on `PATH`, so the replay case
carries the receipt row W2 names as well as the one that is proof against the scrub.

**The `live`-marked case at the foot of this module spends real money and is deselected by
default.** It spends it **once**: one executor call under the shipping containment — five
environment names since S-37 ruled `USER` in — and every other clause of row W2's live half is
read off what that one call left on disk. The replay runs in a second interpreter with build
1's recording shim first on its `PATH`, so a second spend is not merely unbudgeted, it is
impossible: anything reaching for the binary gets the shim, which logs and exits 89.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from protean import config
from protean.brain.folders import seed_hashes
from protean.cortex.layer import build, build_live_layer, selected_layer
from protean.cortex.live.config import LAYER_LIVE, LAYER_SCRIPTED
from protean.cortex.live.invoke import LiveSeat
from protean.mailbox.files import build as build_mailbox
from protean.runtime import engine
from protean.runtime.cycle import SEAT_CALL_NUMBER, run_tick
from protean.runtime.journal import journaled_envelope
from protean.runtime.paths import BrainPaths
from protean.runtime.seat import (
    SeatLayer,
    SeatPort,
    SeatSelection,
    build_request,
    calls_of,
    decode_seat_result,
)
from protean.state.enums import (
    CallType,
    Escalation,
    ExpectationKind,
    NodeName,
    Tier,
    UnitStatus,
)
from protean.state.primitives import Expectation, GoalItem, WorkUnit
from protean.state.seats import ManagerPlan, SeatEnvelope
from protean.state.workspace import Workspace
from tests.conftest import tagged_show
from tests.cortex import fake_cli
from tests.cortex.conftest import arm_the_shim, seeded_live_root
from tests.runtime.stubs import seed_brain

GOAL = "land the live seat"
REPO_ROOT = Path(__file__).resolve().parents[2]


show = tagged_show("W2")


@pytest.fixture()
def live_root(tmp_path: Path, monkeypatch):
    """`conftest.seeded_live_root()` per call — this module drives the root, not a seat."""

    def _build(responses):
        return seeded_live_root(tmp_path, monkeypatch, responses)

    return _build


def _plan_response() -> dict:
    return fake_cli.envelope(fake_cli.planner_result("u1", "g1"))


def _acting_response() -> dict:
    """The manager's **acting** answer: it restates the unit and dispatches no wave.

    **No live run completes a dispatch until build A.1.i lands** (`the build specification (not in this mirror)` § Directional decisions 20, folded: S-A82): the live seat's port is addressed by
    a `Tier`, and a wave member is addressed by a call type with a kind process behind it that
    A.1 does not build. The scripted battery is where a wave runs end to end; what this module
    proves is the live seat's own decode and replay, which a wave-less acting answer exercises
    exactly as build 2's did.
    """
    return fake_cli.envelope(fake_cli.planner_result("u1", "g1"))


# --------------------------------------------------------------------------------------
# The port does not change
# --------------------------------------------------------------------------------------


def test_build_takes_no_argument_and_returns_a_seat_layer(monkeypatch) -> None:
    """D7-3, unchanged: the runtime's factory contract is a zero-argument `build()`."""
    import inspect

    assert list(inspect.signature(build).parameters) == []
    monkeypatch.setenv(config.BRAIN_ROOT_ENV, str(REPO_ROOT / "brain"))
    monkeypatch.delenv("PROTEAN_SEAT_SCRIPT", raising=False)
    layer = build()
    show("build() → port", type(layer.port).__name__)
    assert isinstance(layer, SeatLayer)
    assert isinstance(layer.port, SeatPort), "(tier, request) → SeatEnvelope, still"
    assert layer.sessions is not None and layer.calls is not None


def test_the_tracked_root_selects_live_and_a_named_script_still_selects_scripted(
    monkeypatch, tmp_path: Path
) -> None:
    """What keeps `protean dry` and the whole default battery at zero model calls."""
    monkeypatch.delenv("PROTEAN_SEAT_SCRIPT", raising=False)
    assert selected_layer(REPO_ROOT / "brain") == LAYER_LIVE
    monkeypatch.setenv("PROTEAN_SEAT_SCRIPT", "plan_and_execute")
    assert selected_layer(REPO_ROOT / "brain") == LAYER_SCRIPTED
    monkeypatch.delenv("PROTEAN_SEAT_SCRIPT", raising=False)
    assert selected_layer(tmp_path) == LAYER_SCRIPTED, "a root with no seats.yaml is scripted"


def test_the_port_answers_with_a_seat_envelope_over_a_real_process(live_root) -> None:
    root, _ = live_root([_plan_response()])
    layer = build_live_layer(root=root)
    layer.sessions.open_task("task-port")
    selection = SeatSelection(tier=Tier.MANAGER, escalation=Escalation.EMPTY_UNIT_STACK)
    workspace = Workspace(
        task_id="task-port",
        tick=1,
        goals=[GoalItem(id="g1", text=GOAL, opened_at_tick=0, last_progress_tick=0)],
    )

    envelope = layer.port(Tier.MANAGER, build_request(selection, workspace=workspace))
    assert isinstance(envelope, SeatEnvelope)
    assert len(calls_of(layer)) == 1, "one invocation, read through the second seam"


# --------------------------------------------------------------------------------------
# One decode path: a call over the wire and a journal restore
# --------------------------------------------------------------------------------------


def test_a_live_call_and_its_journal_restore_decode_to_byte_identical_models(
    live_root,
) -> None:
    """Row W2's decode clause, over a real process and the journal the tick actually wrote."""
    root, binaries = live_root([_plan_response()])
    layer = build_live_layer(root=root)
    outcome = engine.start(root, GOAL, layer, mailbox=build_mailbox(root), max_ticks=1)

    paths = BrainPaths(root=root).task(outcome.task_id)
    restored = journaled_envelope(paths.journal(1), NodeName.CORTEX, SEAT_CALL_NUMBER)
    assert restored is not None, "the tick journalled the envelope it decoded"

    # The live call's decoded model is the one the tick committed to `latest`; the restore's is
    # decoded here, from the journal, through the same `decode_seat_result()`. Byte-identical is
    # the claim, so the comparison is over the serialized models rather than over the objects.
    committed = json.loads(paths.checkpoint.read_text(encoding="utf-8"))
    live_model = committed["state"]["latest"]["manager"]
    replay_model = json.loads(decode_seat_result(Tier.MANAGER, restored, 1).model_dump_json())
    show("live model", json.dumps(live_model)[:90])
    show("replayed model", json.dumps(replay_model)[:90])
    assert live_model == replay_model, "one decode path, two callers, one model"
    assert fake_cli.invocations(binaries) == 1

    # And the journalled envelope is the CLI's own bytes, not an amended copy (folded: S-17).
    sent = json.loads((binaries / "response-1.json").read_text(encoding="utf-8"))
    assert restored.result == sent["result"]
    assert restored.model_extra["session_id"] == sent["session_id"]


def _crash_in_the_last_node(monkeypatch) -> None:
    """Kill the tick in the node that runs *after* the seat, so its envelope is journalled.

    Build 1's own shape (`tests/runtime/test_resume.py`): a crash **inside** the seat call
    leaves no entry and the re-run invokes; a crash after it leaves the envelope on disk, which
    is the only state the replay branch ever sees.
    """
    from protean.runtime import cycle as cycle_module

    def _explode(payload):
        raise RuntimeError("killed mid-tick")

    monkeypatch.setattr(
        cycle_module, "NODES", {**cycle_module.NODES, "anterior_cingulate": _explode}
    )


def test_a_replayed_tick_restores_the_envelope_and_spawns_nothing(
    live_root, tmp_path: Path, monkeypatch
) -> None:
    """Row W2's replay clause, with **both** recording devices watching."""
    root, binaries = live_root([_plan_response(), _acting_response()])
    layer = build_live_layer(root=root)
    mailbox = build_mailbox(root)
    engine.start(root, GOAL, layer, mailbox=mailbox, task_id="task-replay", max_ticks=1)

    # Tick 2: the seat answers and is journalled, then the tick dies before its checkpoint.
    context = engine.build_context(root, "task-replay", layer, mailbox=mailbox)
    from protean.state.checkpoint import load_checkpoint

    paths = BrainPaths(root=root).task("task-replay")
    state = load_checkpoint(
        json.loads(paths.checkpoint.read_text(encoding="utf-8")), seed_reader=None
    ).state
    _crash_in_the_last_node(monkeypatch)
    state.tick += 1
    with pytest.raises(RuntimeError):
        run_tick(context, state)
    monkeypatch.undo()

    # **Re-based by build A.1**: the journal is keyed `(node, call#[, member#])` rather than by
    # a tier, because a tick holds several calls now and the seat's single exception became the
    # rule (§ Deliverable 6, order W4).
    assert (
        journaled_envelope(paths.journal(2), NodeName.CORTEX, SEAT_CALL_NUMBER) is not None
    )
    assert fake_cli.invocations(binaries) == 2, "two ticks, two calls, so far"

    # Build 1's own recording shim, first on PATH for the replay, with its log redirected into
    # the temp tree so an invocation lands there rather than in the checkout.
    shim_log = arm_the_shim(monkeypatch, tmp_path / "invocations.log")

    outcome = engine.resume(root, build_live_layer(root=root), mailbox=mailbox, max_ticks=1)

    show("replay restored", outcome.ticks[0].seat_restored)
    show("invocations after the replay", fake_cli.invocations(binaries))
    show("shim log size", shim_log.stat().st_size)
    assert outcome.ticks[0].tick == 2
    assert outcome.ticks[0].seat_restored is True
    assert fake_cli.invocations(binaries) == 2, "the replay spawned nothing"
    assert shim_log.stat().st_size == 0, "and the recording shim gained no entry"


# --------------------------------------------------------------------------------------
# The seat handles across a resume in a new process
# --------------------------------------------------------------------------------------


def test_every_seat_handle_is_checkpointed_and_reused_without_minting(live_root) -> None:
    root, binaries = live_root([_plan_response(), _acting_response()])
    first = build_live_layer(root=root)
    outcome = engine.start(root, GOAL, first, mailbox=build_mailbox(root), max_ticks=1)

    paths = BrainPaths(root=root).task(outcome.task_id)
    committed = json.loads(paths.checkpoint.read_text(encoding="utf-8"))
    carried = committed["state"]["seat_sessions"]
    show("checkpointed handles", sorted(carried))
    assert sorted(carried) == sorted(str(tier) for tier in Tier)

    # A second process builds its own layer and mints nothing for this task.
    second = build_live_layer(root=root)
    engine.resume(root, second, mailbox=build_mailbox(root), max_ticks=1)

    assert second.sessions.minted_tasks == [], "restored, never re-minted"
    argv = fake_cli.argv_of(binaries, 2)
    show("resumed argv", [argv[0], argv[1], argv[2]])
    assert "--session-id" not in argv
    assert argv[argv.index("--resume") + 1] == carried[str(Tier.MANAGER)]


def test_the_seed_hashes_cover_the_live_configuration(live_root) -> None:
    """The seat's configuration is a seed: editing it mid-task is a drift refusal (S-4, S-11)."""
    root, _ = live_root([_plan_response()])
    hashes = seed_hashes(root)
    show("widened seed keys", sorted(k for k in hashes if not k.startswith("nodes/")))
    assert "seats.yaml" in hashes
    assert {f"seats/{tier}.md" for tier in config.TIERS} <= set(hashes)
    assert "seeds/index" in hashes, "the appearance detector (folded: S-11)"


# --------------------------------------------------------------------------------------
# The live case — one real executor call, and every other clause read off what it left
# --------------------------------------------------------------------------------------

LIVE_TASK = "task-live-w2"
LIVE_UNIT = "u-live-w2"
LIVE_GOAL = "answer once, over the real wire"

#: The child that carries the resume and the replay into a **second interpreter**.
REPLAY_CHILD = Path(__file__).resolve().parent / "live_replay_child.py"

#: A predicate the executor cannot satisfy, whatever it answers: `SUMMARY_FIELD_EQUALS` reads
#: the summary's own dumped payload and `ExecutorSummary` forbids extras, so a name that is not
#: one of its fields can never be present. That is the point — the unit stays `PENDING`, so the
#: **replayed** tick routes to the executor exactly as the live tick did, and the replay is a
#: restore of the journalled envelope rather than a second call to some other tier.
UNSATISFIABLE = Expectation(
    id="e-live-w2",
    kind=ExpectationKind.SUMMARY_FIELD_EQUALS,
    arguments={"field": "not_a_summary_field", "value": True},
)

#: Tiny on purpose. The stable prefix is the real one and the CLI injects its own harness
#: prompt on top (~40k cache-creation tokens, dispatch-5 ledger D5-9); the volatile half is the
#: only part this row controls, so it asks for the smallest well-formed answer there is.
LIVE_INTENT = (
    "Answer only. Use no tool, read and write nothing, and change nothing in the workspace. "
    "Reply with an ExecutorSummary whose narrative is the single word noop, exit_code 0, and "
    "empty observations, expectation_values and cited_ids. Raise no interrupt."
)


def _tracked_live_root(destination: Path) -> Path:
    """A throwaway root carrying the tracked seeds **verbatim** — the shipping containment.

    `fake_cli.seed_live_root` rewrites three keys to point a root at the stand-in binary; this
    rewrites none. The binary is `claude`, the `PATH` list is the seed's, `env_passthrough` is
    the five names S-37 ruled, and `brain/nodes/cortex/NODE.md` + `brain/seats/executor.md` are
    the tracked bytes — so the prefix this call sends is the prefix a real run sends.
    """
    seed_brain(REPO_ROOT / "brain", destination)
    shutil.copytree(REPO_ROOT / "brain" / "seats", destination / "seats")
    shutil.copy2(REPO_ROOT / "brain" / "seats.yaml", destination / "seats.yaml")
    return destination


@pytest.mark.live
def test_one_real_call_then_the_restore_the_resume_and_the_replay(
    tmp_path: Path, monkeypatch
) -> None:
    """Row W2's live clause, whole, on a budget of exactly one executor call.

    * **the call** — `build()` with no argument, the tracked seed's live layer, the real
      containment, one `claude-opus-5` executor invocation through `LiveSeat`;
    * **the restore** — the journal holds the CLI's own bytes, and the model decoded from them
      is byte-identical to the one the live tick committed, through `decode_seat_result()`;
    * **the resume** — a second interpreter builds its own layer and reuses the checkpoint's
      the seat handles without minting;
    * **the replay** — that second interpreter replays the tick with `tests/shim/claude` first
      on its `PATH`, restores the journalled envelope, spawns nothing, and leaves the shim log
      at zero bytes.

    **One call.** `decode_retries` is set to zero for this case: a retry is a second live
    invocation (S-8), and this row's budget does not carry one — a failure is recorded, not
    retried.
    """
    root = _tracked_live_root(tmp_path / "brain")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv(config.BRAIN_ROOT_ENV, str(root))
    monkeypatch.delenv("PROTEAN_SEAT_SCRIPT", raising=False)

    layer = build()
    assert isinstance(layer.port, LiveSeat), "the tracked seed selects the live layer"
    layer.port.decode_retries = 0

    context = engine.build_context(
        root, LIVE_TASK, layer, mailbox=build_mailbox(root), workspace_path=str(workspace)
    )
    state = engine.new_state(LIVE_TASK, LIVE_GOAL, context)
    unit = WorkUnit(
        id=LIVE_UNIT,
        goal_id=state.goals[0].id,
        intent=LIVE_INTENT,
        expected=[UNSATISFIABLE],
    )
    # The state a planner tick would have left: the unit on the stack **and** on the plan the
    # router reads (`unit_stack_is_empty` asks the plan, not the stack), so this tick belongs
    # to the executor. Seeding it is what buys the one-call budget — a real planner tick first
    # would be a second live call.
    state.units = [unit]
    state.latest.manager = ManagerPlan(tick=0, units=[unit])
    state.tick = 1
    snapshot = tmp_path / "pre-tick-state.json"
    snapshot.write_text(state.model_dump_json(), encoding="utf-8")

    # ---- the one call ----------------------------------------------------------------
    result = run_tick(context, state)

    facts = calls_of(layer)
    show("invocations", [(item.tier, item.outcome, item.num_turns) for item in facts])
    assert result.seat_refusal is None, (
        f"the shipping containment could not answer: {result.seat_refusal}"
    )
    assert len(facts) == 1, "one live call, and no retry"
    fact = facts[0]
    show("model · effort · cli_version", (fact.model, fact.effort, fact.cli_version))
    show("usage", fact.usage)
    show("wall seconds", fact.wall_seconds)
    assert fact.outcome == "ok"
    assert fact.model == "claude-opus-5" and fact.tier == str(CallType.DISPATCH)
    assert fact.argv[fact.argv.index("--add-dir") + 1] == str(workspace)
    assert "--session-id" in fact.argv, "the first call of a task mints its handle"
    assert isinstance(fact.num_turns, int), "`num_turns` recorded, never bounded (S-38)"
    assert result.seat_restored is False, "a live tick calls; it does not restore"

    # ---- the restore: one decode path, two callers ------------------------------------
    paths = BrainPaths(root=root).task(LIVE_TASK)
    restored = journaled_envelope(paths.journal(1), CallType.DISPATCH)
    assert restored is not None, "the tick journalled the envelope it decoded"
    sent = json.loads(layer.port.last_stdout.decode("utf-8"))
    assert restored.result == sent["result"], "the journal holds the CLI's own bytes (S-17)"
    assert isinstance(restored, SeatEnvelope)

    committed = json.loads(paths.checkpoint.read_text(encoding="utf-8"))
    live_model = committed["state"]["latest"]["dispatch"]
    replay_model = json.loads(decode_seat_result(CallType.DISPATCH, restored, 1).model_dump_json())
    show("live model", json.dumps(live_model)[:110])
    show("restored model", json.dumps(replay_model)[:110])
    assert live_model == replay_model, "one decode path, two callers, one model"

    carried = committed["state"]["seat_sessions"]
    show("checkpointed handles", sorted(carried))
    assert sorted(carried) == sorted(str(tier) for tier in Tier)
    assert carried[str(CallType.DISPATCH)] == fact.session_handle
    assert state.units[0].status is UnitStatus.PENDING, (
        "the unit must not pass, or the replayed tick would route to another tier"
    )

    # ---- the resume and the replay, in a new process, behind the recording shim --------
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shutil.copy2(REPO_ROOT / "tests" / "shim" / "claude", shim_dir / "claude")
    shim_log = shim_dir / "invocations.log"
    shim_log.write_text("", encoding="utf-8")

    destination = tmp_path / "replay.json"
    child_environment = {
        **os.environ,
        "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}",
        "PROTEAN_SHIM_LOG": str(shim_log),
        config.BRAIN_ROOT_ENV: str(root),
        "PYTHONPATH": str(REPO_ROOT),
    }
    child_environment.pop("PROTEAN_SEAT_SCRIPT", None)
    child = subprocess.run(
        [
            sys.executable,
            str(REPLAY_CHILD),
            str(root),
            LIVE_TASK,
            str(snapshot),
            str(destination),
            "1",
            str(workspace),
        ],
        cwd=str(REPO_ROOT),
        env=child_environment,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert child.returncode == 0, f"the replay process failed:\n{child.stderr}"

    payload = json.loads(destination.read_text(encoding="utf-8"))
    show("child's `claude`", payload["which_claude"])
    show("handles reused in the new process", payload["reused_handles"])
    show("tier the replayed tick routed to", payload["selected_tier"])
    show("shim log size", shim_log.stat().st_size)

    assert payload["which_claude"] is not None
    assert Path(payload["which_claude"]).parent == shim_dir, "the shim really was first"
    assert payload["minted_before_restore"] == [], "a fresh book has minted nothing"
    assert payload["minted_tasks"] == [], "restored, never re-minted"
    assert payload["reused_handles"] == carried
    assert payload["selected_tier"] == str(CallType.DISPATCH)
    assert payload["seat_restored"] is True
    assert payload["journalled_result"] == sent["result"]
    assert json.loads(payload["decoded_model"]) == live_model
    assert shim_log.stat().st_size == 0, "the replay spawned nothing"
