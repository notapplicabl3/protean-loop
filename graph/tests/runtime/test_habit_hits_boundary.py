"""The boundary write: one `HabitHit` per habit-answered tick, zero `SeatCallRecord`s, and the
identity "calls drop" resolves to.

`the build specification (not in this mirror)` § Deliverable 4 (seam contract P3), § Directional decisions
3, 13, 14, 21, § Resolutions S-1, S-5, S-18. DoD row **L7** whole, plus builder rows **N4**'s
runtime half (the fall-back to a live call after a withdrawal) and **N5** (the optional seam and
the replayed tick). The record half is `tests/state/test_habit_hits.py`; the matcher's is
`tests/cortex/test_habits.py`.

**Every assertion is on disk or on the layer's own record**, never on the runtime's report of
itself: the file's lines, the cortex folder's `trace.jsonl`, the two files' sha256 across a
replay, and — for the identity's left-hand side — the port's own list of invocations, which is
the only independent witness of "a model was invoked".

**The zero-call half runs in a subprocess with the recording shim first on `PATH`**, in the
shape `tests/test_zero_calls.py` fixed: a run in which a procedure *matches* has to prove it
spawned nothing, and an empty log proves that only when a real invocation would have filled it
— which is that module's own control. Nothing here names the binary.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest
import yaml

from protean import config
from protean.brain.jsonl import read_lines
from protean.runtime.commit import WRITE_SEAT_CALL
from protean.runtime.cycle import SEAT_CALL_NUMBER, run_tick
from protean.runtime.engine import build_context, new_state
from protean.runtime.journal import journaled_envelope
from protean.runtime.paths import ROOT_PROJECT_SLUG, BrainPaths
from protean.runtime.seat import SeatLayer, decode_seat_result
from protean.state.enums import CallType, Escalation, NodeName, Tier
from protean.state.habit_hits import load_habit_hits
from protean.state.records import TraceRecord
from protean.state.seat_calls import load_seat_calls
from protean.state.sleep import Procedure, ProcedureResponse
from protean.cortex.scripts import goal_digest_of
from tests.runtime import stubs
from tests.runtime.conftest import (
    EXPECTATION_ID,
    REPO_ROOT,
    UNIT_ID,
    plan_then_execute_pair,
)

#: The goal every task in this module opens with — the one the conftest's planner plans for.
GOAL = "write out.txt"
DIGEST = goal_digest_of(GOAL)
PROCEDURE_ID = f"habit-manager-{DIGEST}"

#: The recording shim's directory, and the environment variable it writes its receipt to. Both
#: are `tests/test_zero_calls.py`'s; naming them again here would be a second thing to drift.
SHIM_DIR = REPO_ROOT / "tests" / "shim"
SHIM_LOG_ENV = "PROTEAN_SHIM_LOG"

ARGV = ("--output-format", "json")


def planner_habit() -> Procedure:
    """The compiled habit this module plants, in the shape `protean.sleep.habits` writes one.

    Its response is the plan the conftest's scripted planner returns, so a habit-answered tick
    and a called one leave the workspace in the same state and the run continues identically —
    which is what makes the two paths comparable at all. `$goal` is the compiler's placeholder
    (ledger `D16-3`) and the matcher resolves it from the request.
    """
    result = {
        "emitter": "manager",
        "units": [
            {
                "id": UNIT_ID,
                "goal_id": "$goal",
                "intent": "write the file",
                "expected": [
                    {
                        "id": EXPECTATION_ID,
                        "kind": "file_exists",
                        "arguments": {"path": "out.txt"},
                    }
                ],
            }
        ],
    }
    return Procedure(
        procedure_id=PROCEDURE_ID,
        name=PROCEDURE_ID,
        hits_required=3,
        responses=[
            # **Re-based by build A.1**: the manager now answers the acting pass as well as the
            # planning one (§ Deliverable 3), so a condition on the goal digest alone would
            # match every pass of the run and the seat would never be called at all. The
            # opening rung is named beside it — `escalation` is one of build 1's own five
            # condition keys — so the habit answers the pass it was compiled from and the
            # later ones call, which is what makes the two paths comparable.
            ProcedureResponse(
                tier=Tier.MANAGER,
                when={"goal_digest": DIGEST, "escalation": str(Escalation.EMPTY_UNIT_STACK)},
                result=result,
            )
        ],
    )


def plant(brain: Path, procedure: Procedure, *, project: str | None = None) -> Path:
    """Write one compiled habit where the next sleep run would have left it."""
    paths = BrainPaths(root=brain)
    directory = (
        paths.node_procedures(config.CORTEX_NODE)
        if project is None
        else paths.project_procedures(project)
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{procedure.procedure_id}.yaml"
    path.write_text(
        yaml.safe_dump(procedure.script_payload(), sort_keys=False), encoding="utf-8"
    )
    return path


@pytest.fixture()
def counting(plan_then_execute):
    """The conftest's router/port pair, with the `calls()` seam and an invocation log.

    `record_ticks` is what this module needs beyond the shared recording port: the **tick** each
    invocation answered, read off the request the way `protean.cortex.scripts.facts_of()` reads
    it. That list is the identity's independent left-hand side — it is the layer's own account
    of what it invoked, and it is derived from neither file the identity is checked against.
    """
    planner, executor = plan_then_execute
    seat = stubs.RecordingSeat(
        argv=ARGV,
        usage={"cache_read_input_tokens": 0, "output_tokens": 1},
        record_ticks=True,
        responder=stubs.request_keyed(
            {
                str(Tier.MANAGER): planner,
                str(CallType.DISPATCH): executor,
                str(Tier.DIRECTOR): lambda request: {"tick": request.workspace.tick},
            }
        )
    )
    router = stubs.StubRouter(rule=stubs.manager_then_dispatch(UNIT_ID))
    return SeatLayer(router=router, port=seat, calls=seat.calls), router, seat


@pytest.fixture()
def opened(brain: Path, workspace: Path, counting, mailbox):
    """A task opened against a root carrying one compiled habit for its goal."""
    layer, router, seat = counting
    plant(brain, planner_habit())
    context = build_context(
        brain,
        "task-habit",
        layer,
        mailbox=mailbox,
        workspace_path=str(workspace),
        project=ROOT_PROJECT_SLUG,
    )
    state = new_state("task-habit", GOAL, context)
    return context, state, router, seat


@pytest.fixture(scope="module")
def answered_tick(tmp_path_factory):
    """**One** habit-answered tick, run once and read by every consumer that only reads it.

    Row L7's clauses — one line per matched tick, its fields, the `ref` that resolves into the
    cortex trace, the prediction the tick still mints (row N5's grading claim), the zero
    `seat_calls` lines, the decode path and the nil spend — are seven readings of the *same*
    tick, and not one of them writes into the root or runs a second pass. The two that do — the
    idempotency re-run of tick 1, and the retry/skip sequence — drive their own.
    """
    base = tmp_path_factory.mktemp("habit")
    brain = stubs.seed_brain(REPO_ROOT / "brain", base / "brain")
    workspace = base / "workspace"
    workspace.mkdir()
    planner, executor = plan_then_execute_pair(workspace)
    seat = stubs.RecordingSeat(
        argv=ARGV,
        usage={"cache_read_input_tokens": 0, "output_tokens": 1},
        record_ticks=True,
        responder=stubs.request_keyed(
            {
                str(Tier.MANAGER): planner,
                str(CallType.DISPATCH): executor,
                str(Tier.DIRECTOR): lambda request: {"tick": request.workspace.tick},
            }
        ),
    )
    router = stubs.StubRouter(rule=stubs.manager_then_dispatch(UNIT_ID))
    layer = SeatLayer(router=router, port=seat, calls=seat.calls)
    plant(brain, planner_habit())
    context = build_context(
        brain,
        "task-habit",
        layer,
        mailbox=stubs.StubMailbox(root=brain),
        workspace_path=str(workspace),
        project=ROOT_PROJECT_SLUG,
    )
    state = new_state("task-habit", GOAL, context)
    state.tick += 1
    result = run_tick(context, state)
    return context, state, seat, result


def committed_prediction_keys(context) -> set[str]:
    """Every prediction key on the cortex folder's own trace file, read back off disk."""
    keys: set[str] = set()
    for payload in read_lines(context.paths.trace(config.CORTEX_NODE)):
        record = TraceRecord.model_validate(payload)
        if record.prediction is not None:
            keys.add(record.prediction_key())
    return keys


def keys_on_disk(context) -> dict[str, set[int]]:
    """`tier → distinct ticks` across BOTH files — the identity's right-hand side."""
    per_tier: dict[str, set[int]] = defaultdict(set)
    for path in (context.paths.seat_calls, context.paths.habit_hits):
        for line in read_lines(path):
            per_tier[str(line["tier"])].add(int(line["tick"]))
    return dict(per_tier)


def keys_from_the_run(results, seat: CountingSeat) -> dict[str, set[int]]:
    """`tier → distinct ticks` the seat step invoked a model or matched a procedure.

    The left-hand side, and it reads neither file: invocations come off the port's own log and
    matches off each tick's own result.
    """
    per_tier: dict[str, set[int]] = defaultdict(set)
    for tick, tier in seat.invoked:
        per_tier[tier].add(tick)
    for result in results:
        if result.habit_hit is not None:
            per_tier[str(result.habit_hit.tier)].add(result.habit_hit.tick)
    return dict(per_tier)


# --------------------------------------------------------------------------------------
# Row L7: a habit answers, and the line it writes
# --------------------------------------------------------------------------------------


def test_a_matched_tick_writes_exactly_one_line(answered_tick) -> None:
    context, _state, seat, result = answered_tick

    lines = read_lines(context.paths.habit_hits)
    assert len(lines) == 1
    assert result.habit_hit is not None
    assert lines[0]["procedure_id"] == PROCEDURE_ID
    assert seat.invoked == [], "the consult came before the port, so nothing was invoked"


def test_the_line_lands_under_the_tasks_own_state_directory(opened) -> None:
    """Pure path algebra: where the file lands is a fact about `BrainPaths`, not about a tick."""
    context, _state, _router, _seat = opened

    assert context.paths.habit_hits.parent == context.paths.state_dir
    assert context.paths.habit_hits.name == "habit_hits.jsonl"
    assert context.paths.habit_hits.parent.name == "task-habit"


def test_the_line_reads_back_field_by_field(answered_tick) -> None:
    context, _state, _seat, _result = answered_tick

    hit = load_habit_hits(context.paths.habit_hits)[0]
    assert hit.schema_version == config.HABIT_HIT_SCHEMA_VERSION
    assert hit.task == "task-habit" and hit.tick == 1
    assert hit.tier is Tier.MANAGER
    assert hit.procedure_id == PROCEDURE_ID
    assert hit.matched_condition == {
        "goal_digest": DIGEST,
        "escalation": str(Escalation.EMPTY_UNIT_STACK),
    }
    assert hit.avoided_model == "", "a scripted root configures no model to avoid"


def test_the_ref_names_a_prediction_committed_in_the_cortex_trace(answered_tick) -> None:
    context, _state, _seat, _result = answered_tick

    hit = load_habit_hits(context.paths.habit_hits)[0]
    committed = committed_prediction_keys(context)
    assert hit.ref in committed
    assert hit.ref == f"task-habit:1:{config.CORTEX_NODE}:{Tier.MANAGER}:prediction"


def test_the_tick_still_writes_that_tiers_cortex_prediction(answered_tick) -> None:
    """"A habit-answered tick is graded exactly like a model-answered one" — the whole reason a
    bad habit can be un-learned."""
    context, _state, _seat, result = answered_tick

    minted = [
        record
        for record in result.predictions
        if str(record.node) == config.CORTEX_NODE and record.tier is Tier.MANAGER
    ]
    assert len(minted) == 1
    assert minted[0].prediction is not None
    assert minted[0].prediction_key() in committed_prediction_keys(context)


def test_a_matched_tick_appends_zero_lines_to_seat_calls(answered_tick) -> None:
    """S2 is not widened and build 2's row W3 is not falsified."""
    context, _state, _seat, result = answered_tick

    assert not context.paths.seat_calls.exists()
    assert result.receipt.count(WRITE_SEAT_CALL) == 0


def test_the_answer_decodes_on_the_single_decode_seat_result_path(answered_tick) -> None:
    context, _state, _seat, _result = answered_tick

    envelope = journaled_envelope(context.paths.journal(1), NodeName.CORTEX, SEAT_CALL_NUMBER)
    assert envelope is not None, "a habit's envelope is journalled like any other"
    decoded = decode_seat_result(Tier.MANAGER, envelope, 1)
    assert decoded.tick == 1 and decoded.units[0].id == UNIT_ID


def test_the_habit_answered_tick_spends_nothing(answered_tick) -> None:
    _context, state, _seat, _result = answered_tick
    assert state.cost.tokens == 0


def test_a_second_run_of_the_same_tick_does_not_double_the_line(opened) -> None:
    context, state, _router, _seat = opened
    state.tick += 1
    run_tick(context, state)
    before = context.paths.habit_hits.read_bytes()

    state.tick = 1
    run_tick(context, state)
    assert context.paths.habit_hits.read_bytes() == before


# --------------------------------------------------------------------------------------
# Row L7's identity, over a whole run, per tier
# --------------------------------------------------------------------------------------


def test_the_identity_holds_over_a_run_with_a_retry_and_a_skipped_tick(opened) -> None:
    """`ticks at which the seat step invoked a model or matched a procedure ==
    distinct (tick, tier) keys in seat_calls.jsonl + habit_hits.jsonl` (folded: S-1).

    Tick 1 is answered by the habit, tick 2 is a decode retry (two `seat_calls` lines, one
    tick), tick 3's seat call is skipped by homeostasis, tick 4 is an ordinary call.
    """
    context, state, _router, seat = opened
    results = []

    state.tick += 1
    results.append(run_tick(context, state))  # 1: the habit

    seat.plan = {str(Tier.MANAGER): ("decode_retry", "ok")}
    state.tick += 1
    results.append(run_tick(context, state))  # 2: a retried pair

    seat.plan = {}
    spent = state.cost.tokens
    state.cost.tokens = 10**9  # homeostasis stops, which skips the seat call
    state.tick += 1
    results.append(run_tick(context, state))  # 3: skipped
    state.cost.tokens = spent

    state.tick += 1
    results.append(run_tick(context, state))  # 4: an ordinary call

    left = keys_from_the_run(results, seat)
    right = keys_on_disk(context)
    print(f"invoked or matched: {left}")
    print(f"seat_calls + habit_hits: {right}")
    assert left == right

    # **Re-based by build A.1**: every seat call is the director's or the manager's — the
    # acting tick moved onto the manager's own plan and a dispatch is not a seat (§ Deliverable
    # 3), so all three passes key on `manager`.
    assert left == {str(Tier.MANAGER): {1, 2, 4}}
    assert results[2].seat_skipped
    assert 3 not in left[str(Tier.MANAGER)], "a skipped tick counts on neither side"
    assert len(load_seat_calls(context.paths.seat_calls)) == 3, "the retry is two lines"
    assert len(load_habit_hits(context.paths.habit_hits)) == 1


def test_the_retried_pair_collapses_to_one_key(opened) -> None:
    context, state, _router, seat = opened
    seat.plan = {str(Tier.MANAGER): ("decode_retry", "ok")}
    state.tick += 1
    run_tick(context, state)  # the habit answers, so the plan never fires

    seat.plan = {str(Tier.MANAGER): ("decode_retry", "ok")}
    state.tick += 1
    run_tick(context, state)

    written = load_seat_calls(context.paths.seat_calls)
    assert [call.outcome for call in written] == ["decode_retry", "ok"]
    # Pass 1 is the habit's `HabitHit` and pass 2 the retried pair's two receipt lines: both
    # key on `manager` now, because the manager answers the opening pass and the acting one.
    assert keys_on_disk(context)[str(Tier.MANAGER)] == {1, 2}


# --------------------------------------------------------------------------------------
# Row N5: the seam is optional, and a replay appends neither record
# --------------------------------------------------------------------------------------


def test_a_layer_without_the_seam_writes_no_habit_hits(
    brain: Path, workspace: Path, counting, mailbox
) -> None:
    layer, _router, _seat = counting
    plant(brain, planner_habit())
    context = build_context(
        brain, "task-noseam", layer, mailbox=mailbox, workspace_path=str(workspace)
    )
    # The runtime attached the seam at task open; a layer that never gets one behaves as
    # build 2's did — the field is optional exactly as `sessions` and `calls` are.
    stripped = context.__class__(
        paths=context.paths,
        root=context.root,
        folders=context.folders,
        layer=layer,
        seed_hashes=context.seed_hashes,
        workspace_path=context.workspace_path,
        mailbox=context.mailbox,
    )
    state = new_state("task-noseam", GOAL, stripped)
    state.tick += 1
    result = run_tick(stripped, state)

    assert stripped.layer.habits is None
    assert result.habit_hit is None
    assert not stripped.paths.habit_hits.exists()
    assert len(load_seat_calls(stripped.paths.seat_calls)) == 1, "it called instead"


def test_a_replayed_tick_restores_the_envelope_and_appends_neither_record(opened) -> None:
    context, state, _router, seat = opened
    state.tick += 1
    before_state = state.model_copy(deep=True)
    run_tick(context, state)

    hits_digest = hashlib.sha256(context.paths.habit_hits.read_bytes()).hexdigest()
    print(f"habit_hits.jsonl sha256 after the habit-answered tick: {hits_digest}")

    replayed = before_state.model_copy(deep=True)
    result = run_tick(context, replayed, replay=True)

    assert result.seat_restored, "the journalled envelope answered"
    assert result.habit_hit is None, "a replay consults nothing"
    assert seat.invoked == [], "and calls nothing"
    after = hashlib.sha256(context.paths.habit_hits.read_bytes()).hexdigest()
    print(f"habit_hits.jsonl sha256 after the replay:               {after}")
    assert after == hits_digest
    assert len(read_lines(context.paths.habit_hits)) == 1, "no second `HabitHit`"
    # **The named residual, recorded rather than asserted away** (builder's ledger D7-3, queued to
    # the operator beside B39): from order W4 the boundary writes one `SeatCallRecord` per **journalled
    # call** of the committing pass, and the journal carries no "a habit answered" field — so a
    # *replayed* habit-answered pass writes a receipt where the live pass wrote a `HabitHit`.
    # P3 is untouched by A.1, which is why the residual is left standing and named here.
    replayed_lines = load_seat_calls(context.paths.seat_calls)
    assert [line.outcome for line in replayed_lines] == ["ok"]
    assert [line.call_number for line in replayed_lines] == [SEAT_CALL_NUMBER]


def test_a_replayed_call_tick_appends_neither_record_either(opened) -> None:
    """The other half of N5's clause: the tick that *called* replays the same way."""
    context, state, _router, _seat = opened
    state.tick += 1
    run_tick(context, state)
    state.tick += 1
    before_state = state.model_copy(deep=True)
    run_tick(context, state)

    digests = tuple(
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (context.paths.seat_calls, context.paths.habit_hits)
    )
    run_tick(context, before_state.model_copy(deep=True), replay=True)
    assert digests == tuple(
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (context.paths.seat_calls, context.paths.habit_hits)
    )


# --------------------------------------------------------------------------------------
# Row N4's runtime half: the fall-back after a withdrawal
# --------------------------------------------------------------------------------------


def test_the_seat_step_falls_back_to_a_live_call_after_a_withdrawal(
    brain: Path, workspace: Path, counting, mailbox
) -> None:
    """A withdrawn habit is a deleted file, so the next task open loads a set without it."""
    layer, _router, seat = counting
    path = plant(brain, planner_habit())

    context = build_context(
        brain, "task-before", layer, mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-before", GOAL, context)
    state.tick += 1
    run_tick(context, state)
    assert seat.invoked == [] and context.paths.habit_hits.exists()

    path.unlink()  # what `protean sleep`'s withdrawal does to the file

    after = build_context(
        brain, "task-after", layer, mailbox=mailbox, workspace_path=str(workspace)
    )
    later = new_state("task-after", GOAL, after)
    later.tick += 1
    result = run_tick(after, later)

    assert after.layer.habits is None, "the set is empty, so the layer carries no seam"
    assert seat.invoked == [(1, str(Tier.MANAGER))], "the planner tick called instead"
    assert result.habit_hit is None
    assert not after.paths.habit_hits.exists()
    assert len(load_seat_calls(after.paths.seat_calls)) == 1


def test_a_task_under_another_project_does_not_match_that_projects_habit(
    brain: Path, workspace: Path, counting, mailbox
) -> None:
    """The slug decides which project's procedures a task opens with (decision 22, S-18)."""
    layer, _router, seat = counting
    plant(brain, planner_habit(), project="workload")

    context = build_context(
        brain, "task-other", layer, mailbox=mailbox, workspace_path=str(workspace),
        project="other",
    )
    state = new_state("task-other", GOAL, context, project="other")
    state.tick += 1
    assert run_tick(context, state).habit_hit is None
    assert seat.invoked == [(1, str(Tier.MANAGER))]


def test_the_same_task_under_that_project_does_match_it(
    brain: Path, workspace: Path, counting, mailbox
) -> None:
    layer, _router, seat = counting
    plant(brain, planner_habit(), project="workload")

    context = build_context(
        brain, "task-workload", layer, mailbox=mailbox, workspace_path=str(workspace),
        project="workload",
    )
    state = new_state("task-workload", GOAL, context, project="workload")
    state.tick += 1
    assert run_tick(context, state).habit_hit is not None
    assert seat.invoked == []


# --------------------------------------------------------------------------------------
# Row L7's first clause: a matched tick spawns no process
# --------------------------------------------------------------------------------------

#: A whole scripted run on a throwaway root carrying one compiled habit, driven in a subprocess
#: so the shim's `PATH` is the run's own. It prints one JSON line of evidence and writes nothing
#: the parent has to trust: every number below is read off the temp root's own files.
DRIVER = '''
import json, shutil, sys
from pathlib import Path

import yaml

from protean import config
from protean.brain.jsonl import read_lines
from protean.cortex.layer import build_layer
from protean.cortex.scenario import load_scenario
from protean.cortex.scripts import goal_digest_of
from protean.mailbox.files import build as build_mailbox
from protean.runtime import engine
from protean.runtime.paths import BrainPaths
from protean.state.records import TraceRecord

repo, sandbox = Path(sys.argv[1]), Path(sys.argv[2])
brain = sandbox / "brain"
shutil.copytree(repo / "brain" / "nodes", brain / "nodes")
for node in config.NODE_ORDER:
    (config.node_dir(node, brain) / "trace.jsonl").write_text("", encoding="utf-8")
for relative in config.GENERATED_BRAIN_DIRS:
    (brain / relative).mkdir(parents=True, exist_ok=True)
workspace = sandbox / "workspace"
workspace.mkdir()

scenario = load_scenario("dry")
digest = goal_digest_of(scenario.goal)
paths = BrainPaths(root=brain)
procedures = paths.node_procedures(config.CORTEX_NODE)
procedures.mkdir(parents=True, exist_ok=True)
identifier = "habit-manager-" + digest
(procedures / (identifier + ".yaml")).write_text(
    yaml.safe_dump(
        {
            "schema_version": config.CHECKPOINT_SCHEMA_VERSION,
            "procedure_id": identifier,
            "name": identifier,
            "seed": False,
            "hits_required": 3,
            "compiled_from": {"refs": [], "tasks": []},
            "responses": [
                {
                    "tier": "manager",
                    "when": {"goal_digest": digest},
                    "result": {"emitter": "manager", "goals_satisfied": ["$goal"]},
                    "usage": {},
                }
            ],
        },
        sort_keys=False,
    ),
    encoding="utf-8",
)

outcome = engine.start(
    brain,
    scenario.goal,
    build_layer(root=brain, script=scenario.script),
    mailbox=build_mailbox(brain),
    workspace_path=str(workspace),
)
task = paths.task(outcome.task_id)
committed = [
    TraceRecord.model_validate(row).prediction_key()
    for row in read_lines(task.trace(config.CORTEX_NODE))
    if row.get("prediction") is not None
]
print(
    json.dumps(
        {
            "terminal": str(outcome.terminal),
            "ticks": len(outcome.ticks),
            "habit_hits": read_lines(task.habit_hits),
            "seat_calls": len(read_lines(task.seat_calls)),
            "seat_calls_exists": task.seat_calls.exists(),
            "committed_predictions": committed,
            "procedure": str(procedures / (identifier + ".yaml")),
        }
    )
)
'''


@pytest.fixture(scope="module")
def shim_log(tmp_path_factory) -> Path:
    """An empty log, created before the run so `zero bytes` is a read and not an absence."""
    path = tmp_path_factory.mktemp("shim") / "invocations.log"
    path.write_text("", encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def habit_run(tmp_path_factory, shim_log: Path) -> dict:
    """One scripted run in which a procedure matches, with the shim first on `PATH`.

    **The log and the run are one fixture instance**: the log is what the run's own `PATH` shim
    would write to, so a second materialisation of either would make "zero bytes" a reading of a
    log no run was pointed at. One subprocess for the module, and the evidence below is read off
    its single JSON line.

    `PROTEAN_BRAIN` is exported at the root the driver seeds: the child runs with `cwd` at the
    checkout, and `config.brain_root()` falls back to `<repo>/brain` when nothing names one — so
    without this the repo's own brain tree is one missing argument away from being the run's.
    """
    base = tmp_path_factory.mktemp("habit_run")
    driver = base / "drive_habit.py"
    driver.write_text(DRIVER, encoding="utf-8")
    sandbox = base / "sandbox"
    sandbox.mkdir()
    environment = dict(os.environ)
    environment["PATH"] = f"{SHIM_DIR}{os.pathsep}{environment.get('PATH', '')}"
    environment[SHIM_LOG_ENV] = str(shim_log)
    environment["PROTEAN_BRAIN"] = str(sandbox / "brain")
    completed = subprocess.run(
        [sys.executable, str(driver), str(REPO_ROOT), str(sandbox)],
        env=environment,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    print(completed.stdout)
    return json.loads(completed.stdout.splitlines()[-1])


def test_the_whole_run_spawned_no_process_and_a_habit_answered_its_one_tick(
    habit_run: dict, shim_log: Path
) -> None:
    """Row L7 end to end, in the order the run produces it, off **one** driven run.

    * the shim's log is **zero bytes**, so no process was spawned — the control that makes an
      empty log mean something is
      `tests/test_zero_calls.py::test_the_shim_records_and_fails_loudly_when_it_is_invoked`;
    * the run that proves it is one a habit **actually answered** — it reached `done` in the one
      tick the habit closed the goal on, and wrote exactly one `habit_hits` line, keyed to the
      manager on tick 1; and
    * that run wrote **no** `seat_call` at all — the file does not exist — and the line's `ref`
      resolves into the cortex trace's committed predictions.
    """
    assert shim_log.stat().st_size == 0, shim_log.read_text(encoding="utf-8")
    assert habit_run["habit_hits"], "and a procedure did answer a tick"

    assert habit_run["terminal"] == "done"
    assert habit_run["ticks"] == 1, "the habit closed the goal on the tick it answered"
    assert len(habit_run["habit_hits"]) == 1
    line = habit_run["habit_hits"][0]
    assert line["procedure_id"].startswith("habit-manager-")
    assert line["tier"] == str(Tier.MANAGER) and line["tick"] == 1

    assert habit_run["seat_calls"] == 0 and habit_run["seat_calls_exists"] is False
    assert habit_run["habit_hits"][0]["ref"] in habit_run["committed_predictions"]
