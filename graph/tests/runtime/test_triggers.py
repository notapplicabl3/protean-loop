"""G1, G2, G3 and G6 — the call policy, the two authored rules shipped off, and their payloads.

`the build specification (not in this mirror)` § Deliverable 1, the build's T3 surface: the mechanism — a
pure call check beside each authored node's `firing_check` and one policy beside `firing.py`;
the plan — one planned set per node per tick, decided before issue, re-derived on a replay; the
payload — the question read verbatim from the node's own `NODE.md` `## Calls`, the context its
projection cut at a named bound; the homeostasis and anterior cingulate rules; and the seed-shape
refusal `engine.build_context()` raises before any tick. Every case is named for its row, so
`-k G1`, `-k G2`, `-k G3` and `-k G6` select them; later orders append their own rows here.

**A plan is never journalled, so it is observed through a spy** on `triggers.plan`, which
`cycle.py` calls through the module attribute. Key-on roots are temporary copies of the shipping
seed (`stubs.seed_brain` and `stubs.set_weight`), never `fixtures/`. A fixture's own `calls:` plan
outranks the policy for a node it names, so a tick that needs the policy to plan uses a temporary
copy of a landed calls fixture with its `calls:` plan removed, written under the test's own temp
directory and handed to `stubs.scripted_layer()` by absolute path.

**Zero model calls.** Every answer is a scripted fixture response through the scripted layer, and
every `protean` subprocess here runs with the recording shim first on `PATH` and asserts its log is
still zero bytes afterwards.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, NamedTuple, get_type_hints

import pytest
import yaml

from protean import cli, config
from protean.brain.folders import load_weights
from protean.cortex.calls import CallConfigurationError, NodeCallDesk
from protean.cortex.layer import SEAT_SCRIPT_ENV
from protean.nodes import anterior_cingulate as monitor_node
from protean.nodes import homeostasis as homeostasis_node
from protean.runtime import cycle as cycle_module
from protean.runtime import engine, firing, triggers
from protean.runtime.cycle import SEAT_CALL_NUMBER, run_tick
from protean.runtime.engine import build_context
from protean.runtime.journal import load as load_journal
from protean.runtime.paths import BrainPaths
from protean.runtime.predictions import input_signature
from protean.runtime.seat import PlannedCall, TickCalls
from protean.sleep.weights import SIGNAL_KEY_MAP, declared_weight_keys
from protean.state.enums import CallType, ExpectationKind, NodeName
from protean.state.errors import CallsDrift
from protean.state.inputs import HomeostasisInput, MonitorInput
from protean.state.primitives import Expectation, WorkUnit
from protean.state.reads import NODE_INPUT_MODELS, READS_HEADING, check_reads
from protean.state.records import OUTPUT_CALL_NUMBER
from protean.state.seats import ExecutorSummary
from tests.conftest import BRAIN_SEED, tagged_show
from tests.dry.conftest import DRY_SCENARIO, SCENARIO_DIR
from tests.nodes.conftest import TASK_ID, cost, overrides
from tests.runtime import stubs
from tests.runtime.conftest import DECLINE, REPO_ROOT, call_entries_of, entries_of
from tests.test_zero_calls import SHIM_DIR

show = tagged_show("W1")

HOMEOSTASIS = str(NodeName.HOMEOSTASIS)
MONITOR = str(NodeName.ANTERIOR_CINGULATE)
AUTHORED = (HOMEOSTASIS, MONITOR)

#: Each authored node's trigger key, as its own module spells it.
TRIGGER = {
    HOMEOSTASIS: homeostasis_node.WEIGHT_THINK_TRIGGER,
    MONITOR: monitor_node.WEIGHT_THINK_TRIGGER,
}

CALLS_FIXTURES = REPO_ROOT / "fixtures" / "calls"
GOAL = "write the note and check it"

#: An on-value no first-tick pressure reaches and every second-tick pressure does: a fresh task's
#: first projection has consumed nothing, and its second has consumed one tick of `max_ticks`.
HOMEOSTASIS_ON = 0.001
#: The monitor's on-value G3 names: one graded predicate reaches it, and zero never does.
MONITOR_ON = 1

#: The five mutations G3 refuses, as written in YAML, and what `safe_load` makes of each.
REFUSED = {"0": 0, "-1": -1, "true": True, "off": False, "'0.5'": "0.5"}
#: The values that load: `null` is off, and `1` and `0.5` are on. The absent key is its own case.
LOADS = {"null": None, "1": 1, "0.5": 0.5}
ABSENT = "<absent>"

#: The `max_ticks` a task opened for G6's resume path is stopped on: its first boundary crosses it.
STOP_AFTER_ONE = 1

#: The real entry point, captured at import, before any spy replaces the module attribute.
REAL_PLAN = triggers.plan


# --------------------------------------------------------------------------------------
# Roots, scripts, the spy and the subprocess
# --------------------------------------------------------------------------------------


def tracked_node_md(node: str) -> str:
    return (config.node_dir(node, BRAIN_SEED) / "NODE.md").read_text(encoding="utf-8")


def calls_line(node_md: str, call_type: str = "think") -> str:
    """The question on a node's `## Calls` line, read here without the policy's own parser."""
    section = node_md.split(f"\n{triggers.CALLS_HEADING}\n", 1)[1]
    prefix = f"- {call_type}: "
    (line,) = [row for row in section.splitlines() if row.startswith(prefix)]
    return line[len(prefix):]


def open_root(tmp_path: Path, name: str = "brain", **on: Any) -> Path:
    """A throwaway copy of the shipping seed, with the named nodes' trigger keys turned on."""
    brain = stubs.seed_brain(REPO_ROOT / "brain", tmp_path / name)
    for node, value in on.items():
        stubs.set_weight(brain, node, **{TRIGGER[node]: value})
    return brain


def write_trigger(brain: Path, node: str, raw: str) -> None:
    """Rewrite the trigger key's line as YAML text — so `off` reaches the loader as `off`."""
    path = config.node_dir(node, brain) / "weights.yaml"
    text = path.read_text(encoding="utf-8")
    line = f"{TRIGGER[node]}: null\n"
    assert text.count(line) == 1, "the throwaway root carries the shipping off line"
    path.write_text(
        text.replace(line, "" if raw == ABSENT else f"{TRIGGER[node]}: {raw}\n"),
        encoding="utf-8",
    )


def drop_calls_line(brain: Path, node: str, call_type: str = "think") -> None:
    """Remove one `## Calls` line from a throwaway root's `NODE.md`."""
    path = config.node_dir(node, brain) / "NODE.md"
    rows = path.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [row for row in rows if not row.startswith(f"- {call_type}: ")]
    assert len(kept) == len(rows) - 1, "exactly one line was the one dropped"
    path.write_text("".join(kept), encoding="utf-8")


def add_calls_line(brain: Path, node: str, line: str) -> None:
    """Append one line to a throwaway root's `## Calls`, which is the file's last section."""
    path = config.node_dir(node, brain) / "NODE.md"
    path.write_text(path.read_text(encoding="utf-8").rstrip("\n") + f"\n{line}\n", encoding="utf-8")


def unplanned(tmp_path: Path, base: str) -> str:
    """A temporary copy of one landed calls fixture, its `calls:` plan removed, a think answer added.

    The think answer is `firing_decline.yaml`'s own — a plain answer with no interrupt — added only
    when the base carries none. Written under the test's temp directory; `fixtures/` is never
    written. `stubs.scripted_layer()` joins it onto its fixture directory, and a join onto an
    absolute path is that path.
    """
    script = yaml.safe_load((CALLS_FIXTURES / f"{base}.yaml").read_text(encoding="utf-8"))
    script.pop("calls", None)
    if not any(row.get("tier") == str(CallType.THINK) for row in script["responses"]):
        donor = yaml.safe_load((CALLS_FIXTURES / "firing_decline.yaml").read_text(encoding="utf-8"))
        script["responses"].extend(
            row for row in donor["responses"] if row.get("tier") == str(CallType.THINK)
        )
    path = tmp_path / f"{base}-unplanned.yaml"
    path.write_text(yaml.safe_dump(script, sort_keys=False), encoding="utf-8")
    return str(path)


def drive(brain: Path, workspace: Path, script: str, *, ticks: int = 2, task: str = "task-w1"):
    """Open a task on a throwaway root and run `ticks` passes, live, through the scripted layer."""
    context, state, port, _seat = stubs.open_task(brain, workspace, script, task, goal=GOAL)
    results = []
    for _ in range(ticks):
        state.tick += 1
        results.append(run_tick(context, state))
    return context, state, port, results


class Seen(NamedTuple):
    """One call of the policy, as the spy saw it: what it was handed and what it returned."""

    node: str
    payload: Any
    node_md: str
    bound: int | None
    delegates: int
    planned: tuple[PlannedCall, ...]


@pytest.fixture()
def spy(monkeypatch) -> list[Seen]:
    """Every call `cycle.py` makes of `triggers.plan`, through the module attribute it calls.

    The projection is copied as the policy saw it: a projection shares its nested models with
    committed state, which the boundary goes on to advance, so a reference kept past the call
    would read a later tick's counters.
    """
    seen: list[Seen] = []
    real = triggers.plan

    def _plan(node, payload, node_md, bound, delegates):
        snapshot = payload.model_copy(deep=True)
        planned = real(node, payload, node_md, bound, delegates)
        seen.append(Seen(str(NodeName(node)), snapshot, node_md, bound, delegates, planned))
        return planned

    monkeypatch.setattr(triggers, "plan", _plan)
    return seen


def of(seen: list[Seen], node: str) -> list[Seen]:
    return [item for item in seen if item.node == node]


def plan_bytes(planned: tuple[PlannedCall, ...]) -> bytes:
    """A plan as bytes: every field of every `PlannedCall`, in order, canonically serialized."""
    return json.dumps(
        [
            {"type": str(call.type), "payload": dict(call.payload), "model": call.payload_model}
            for call in planned
        ],
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")


def types_of(planned: tuple[PlannedCall, ...]) -> list[CallType]:
    return [call.type for call in planned]


def journal_keys(context, tick: int) -> list[tuple[str, int]]:
    """`(node, call#)` for every entry of one tick's journal, in the order the file holds them."""
    return [(str(entry.node), entry.call_number) for entry in entries_of(context, tick)]


def call_entry(context, tick: int, node: str):
    (entry,) = [
        item for item in call_entries_of(context, tick) if str(item.node) == node
    ]
    return entry


@pytest.fixture()
def shim_log(tmp_path: Path) -> Path:
    """An empty log for the recording shim, created first so "zero bytes" is a read."""
    path = tmp_path / "invocations.log"
    path.write_text("", encoding="utf-8")
    return path


def protean(root: Path, *arguments: str, log: Path) -> subprocess.CompletedProcess:
    """`protean --brain <root> ...` in a subprocess, the recording shim first on `PATH`.

    The seat-script variable and the brain-root variable are dropped from the child's
    environment, so the flagged root and its own seed are the only things that choose the layer.
    """
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in (SEAT_SCRIPT_ENV, config.BRAIN_ROOT_ENV)
    }
    environment["PATH"] = f"{SHIM_DIR}{os.pathsep}{os.environ.get('PATH', '')}"
    environment["PROTEAN_SHIM_LOG"] = str(log)
    return subprocess.run(
        [sys.executable, "-m", "protean.cli", "--brain", str(root), *arguments],
        env=environment,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def homeostasis_input(weights: dict, *, ticks: int = 0) -> HomeostasisInput:
    return HomeostasisInput(
        task_id=TASK_ID,
        tick=4,
        weights=weights,
        cost=cost(ticks=ticks),
        ceiling_overrides=overrides(),
    )


def graded_unit(count: int, *, withheld: int = 0, intent: str = "write the files") -> WorkUnit:
    """A unit declaring `count` gradeable predicates and `withheld` repair-(b) ones."""
    expected = [
        Expectation(id=f"e{index}", kind=ExpectationKind.FILE_EXISTS, arguments={"path": f"f{index}"})
        for index in range(1, count + 1)
    ] + [Expectation(id=f"w{index}", kind=ExpectationKind.EXIT_CODE) for index in range(withheld)]
    return WorkUnit(id="u1", goal_id="g1", intent=intent, expected=expected)


def monitor_input(
    weights: dict, unit: WorkUnit | None, *, summary: bool = True, vetoed: bool = False
) -> MonitorInput:
    return MonitorInput(
        task_id=TASK_ID,
        tick=4,
        weights=weights,
        units=[] if unit is None else [unit],
        executor_summary=(
            ExecutorSummary(tick=4, unit_id=unit.id, narrative="did it")
            if summary and unit is not None
            else None
        ),
        vetoed_unit_id=unit.id if vetoed and unit is not None else None,
    )


def shipping_weights(node: str) -> dict:
    return dict(load_weights(config.node_dir(node, BRAIN_SEED) / "weights.yaml"))


# --------------------------------------------------------------------------------------
# G1 — the policy sits beside the firing policy and is pure, deterministic and zero-call
# --------------------------------------------------------------------------------------


def test_G1_the_policy_sits_beside_firing_py_keyed_by_the_two_authored_nodes():
    here, beside = Path(triggers.__file__).resolve(), Path(firing.__file__).resolve()
    show("policy module", here.relative_to(REPO_ROOT), tag="G1")
    show("map keys", sorted(triggers.CALL_CHECKS), tag="G1")
    assert here.parent == beside.parent == REPO_ROOT / "src" / "protean" / "runtime"
    assert set(triggers.CALL_CHECKS) == {HOMEOSTASIS, MONITOR}
    assert set(triggers.CALL_CHECKS) <= set(config.DETERMINISTIC_NODES)
    assert dict(triggers.TRIGGER_KEYS) == TRIGGER
    assert {
        node: tuple(types) for node, types in triggers.RULE_CALL_TYPES.items()
    } == {HOMEOSTASIS: (CallType.THINK,), MONITOR: (CallType.THINK,)}


def test_G1_the_maps_key_set_is_asserted_at_import_against_the_deterministic_nodes(monkeypatch):
    """Re-executing the module with a node missing from the path is an import-time refusal."""
    narrowed = tuple(node for node in config.DETERMINISTIC_NODES if node != HOMEOSTASIS)
    monkeypatch.setattr(config, "DETERMINISTIC_NODES", narrowed)
    try:
        with pytest.raises(ImportError) as raised:
            importlib.reload(triggers)
        show("import-time refusal", str(raised.value), tag="G1")
        assert HOMEOSTASIS in str(raised.value)
    finally:
        monkeypatch.undo()
        importlib.reload(triggers)
    assert set(triggers.CALL_CHECKS) == {HOMEOSTASIS, MONITOR}


@pytest.mark.parametrize("node", AUTHORED)
def test_G1_each_call_check_lives_beside_its_firing_check_on_its_own_input_model(node):
    check = triggers.CALL_CHECKS[node]
    module = inspect.getmodule(check)
    hints = get_type_hints(check)
    show(f"{node} call check", f"{check.__module__}.{check.__name__} -> {hints['return']}", tag="G1")
    assert check.__module__ == f"protean.nodes.{node}"
    assert list(inspect.signature(check).parameters) == ["payload"]
    assert hints["payload"] is NODE_INPUT_MODELS[NodeName(node)][0]
    assert hints["return"] == tuple[CallType, ...]
    firing_line = inspect.getsourcelines(module.firing_check)[1]
    check_line = inspect.getsourcelines(check)[1]
    body_line = inspect.getsourcelines(module.run)[1]
    assert firing_line < check_line < body_line, "beside `firing_check`, before the body"


def test_G1_each_call_check_answers_a_tuple_of_call_types():
    weights = {**shipping_weights(HOMEOSTASIS), TRIGGER[HOMEOSTASIS]: 0.5}
    answer = homeostasis_node.call_check(homeostasis_input(weights, ticks=150))
    monitor_weights = {**shipping_weights(MONITOR), TRIGGER[MONITOR]: MONITOR_ON}
    monitor_answer = monitor_node.call_check(monitor_input(monitor_weights, graded_unit(2)))
    show("answers", (answer, monitor_answer), tag="G1")
    for got in (answer, monitor_answer):
        assert isinstance(got, tuple)
        assert got == (CallType.THINK,)
        assert all(isinstance(item, CallType) for item in got)


def test_G1_two_calls_on_one_input_return_byte_equal_plans_through_the_spy(
    tmp_path: Path, spy, one_reading_per_source
):
    """Determinism, observed where a plan exists at all: at the policy's entry point.

    Each call the tick made is made again with the same `(node, projection, NODE.md, bound,
    count)` and must return the same bytes; and a second root driven through the same fixture
    hands the policy the same inputs and gets the same plans back.
    """
    runs = []
    for index in range(2):
        on = {HOMEOSTASIS: HOMEOSTASIS_ON, MONITOR: MONITOR_ON}
        brain = open_root(tmp_path / f"run-{index}", **on)
        workspace = tmp_path / f"run-{index}" / "workspace"
        workspace.mkdir()
        script = unplanned(tmp_path / f"run-{index}", "dispatch_wave")
        spy.clear()
        drive(brain, workspace, script, task="task-g1")
        runs.append(list(spy))

    for item in runs[0]:
        again = REAL_PLAN(item.node, item.payload, item.node_md, item.bound, item.delegates)
        assert plan_bytes(again) == plan_bytes(item.planned), item.node

    def inputs(item: Seen) -> tuple:
        return (
            item.node,
            input_signature(item.node, item.payload).digest,
            hashlib.sha256(item.node_md.encode("utf-8")).hexdigest(),
            item.bound,
            item.delegates,
        )

    pairs = list(zip(runs[0], runs[1], strict=True))
    for first, second in pairs:
        assert first.node == second.node
        if inputs(first) == inputs(second):
            assert plan_bytes(first.planned) == plan_bytes(second.planned), first.node
    matched = {
        first.node for first, second in pairs if inputs(first) == inputs(second) and first.planned
    }
    show("planned per call, run 0", [(i.node, types_of(i.planned)) for i in runs[0]], tag="G1")
    show("rules planning on byte-equal inputs in both runs", sorted(matched), tag="G1")
    assert matched == {HOMEOSTASIS, MONITOR}, "a plan that is always empty proves nothing"


def test_G1_no_plan_carries_two_calls_of_one_type(monkeypatch):
    """A check that answers a type twice still plans it once — in the order it first answered."""
    node_md = tracked_node_md(HOMEOSTASIS) + "\n- escalate: is the spend worth raising?\n"
    monkeypatch.setattr(
        triggers,
        "CALL_CHECKS",
        {HOMEOSTASIS: lambda payload: (CallType.THINK, CallType.ESCALATE, CallType.THINK)},
    )
    planned = triggers.plan(HOMEOSTASIS, homeostasis_input({}), node_md, None, 0)
    show("planned", types_of(planned), tag="G1")
    assert types_of(planned) == [CallType.THINK, CallType.ESCALATE]
    assert planned[1].payload == {"concern": "is the spend worth raising?"}


def test_G1_a_handed_dispatch_is_refused_by_name_at_the_desk_with_nothing_issued():
    """F18: a `dispatch` handed on the policy's path is refused exactly as a fixture's is."""
    asked: list[str] = []

    def port(addressee, request):  # pragma: no cover - reached only if the refusal failed
        asked.append(str(addressee))
        raise AssertionError("nothing may be issued")

    think = PlannedCall(
        type=CallType.THINK, payload={"question": "q", "context": ""}, payload_model="ThinkPayload"
    )
    dispatch = PlannedCall(type=CallType.DISPATCH)
    for static in ({}, {HOMEOSTASIS: (think,)}):
        desk = NodeCallDesk(port=port, task="task-g1", tick=1, plan=static)
        assert isinstance(desk, TickCalls)
        with pytest.raises(CallConfigurationError) as raised:
            desk.run(NodeName.HOMEOSTASIS, (think, dispatch))
        show("refusal", str(raised.value), tag="G1")
        assert str(CallType.DISPATCH) in str(raised.value)
        assert desk.records == [], "no record: nothing was issued"
        assert asked == [], "and the port saw no call"


@pytest.mark.parametrize("node", AUTHORED)
def test_G1_a_key_on_nodes_call_entry_precedes_its_output_entry(
    tmp_path: Path, workspace: Path, spy, node
):
    brain = open_root(tmp_path, **{node: HOMEOSTASIS_ON if node == HOMEOSTASIS else MONITOR_ON})
    context, _state, _port, _results = drive(brain, workspace, unplanned(tmp_path, "dispatch_wave"))
    keys = journal_keys(context, 2)
    show(f"journal-2 keys for {node}", [key for key in keys if key[0] == node], tag="G1")
    assert (node, 1) in keys, "the key is on and the rule planned its think"
    assert keys.index((node, 1)) < keys.index((node, OUTPUT_CALL_NUMBER))


def test_G1_a_node_whose_firing_check_declined_issues_no_call(
    tmp_path: Path, workspace: Path, spy
):
    """The key is on and its score reaches it — and the firing check, in front of it, declines."""
    brain = open_root(tmp_path, **{HOMEOSTASIS: HOMEOSTASIS_ON})
    stubs.set_weight(brain, HOMEOSTASIS, **{homeostasis_node.WEIGHT_FIRING: DECLINE})
    context, _state, port, results = drive(brain, workspace, unplanned(tmp_path, "dispatch_wave"))
    show("homeostasis decisions", [r.firing[0].fired for r in results], tag="G1")
    show("addressees", port.addressees, tag="G1")
    assert all(result.firing[0].fired is False for result in results)
    assert of(spy, HOMEOSTASIS) == [], "a node that did not fire is never asked for a plan"
    assert str(CallType.THINK) not in port.addressees
    assert all(
        str(entry.node) != HOMEOSTASIS for tick in (1, 2) for entry in call_entries_of(context, tick)
    )


# --------------------------------------------------------------------------------------
# G2 — every trigger ships off, and no learner can move one
# --------------------------------------------------------------------------------------


def test_G2_the_two_authored_seeds_carry_their_key_at_the_off_value_and_no_other_does():
    for node in config.NODE_ORDER:
        weights = shipping_weights(node)
        carried = {key: weights[key] for key in weights if key in TRIGGER.values()}
        show(f"{node} trigger", carried, tag="G2")
        if node in TRIGGER:
            assert TRIGGER[node] in weights and weights[TRIGGER[node]] is None
        else:
            assert not set(weights) & set(TRIGGER.values()), f"{node} gained a trigger key"
    assert shipping_weights(str(NodeName.BASAL_GANGLIA)) == {}


def test_G2_homeostasis_plans_nothing_on_the_shipping_weights_across_its_score():
    weights = shipping_weights(HOMEOSTASIS)
    ceiling = int(weights[homeostasis_node.CEILING_TICKS])
    for ticks in (0, ceiling, 2 * ceiling):
        payload = homeostasis_input(weights, ticks=ticks)
        pressure = homeostasis_node.ceiling_pressure(payload)
        show(f"pressure {pressure}", homeostasis_node.call_check(payload), tag="G2")
        assert homeostasis_node.call_check(payload) == ()
        assert triggers.plan(HOMEOSTASIS, payload, tracked_node_md(HOMEOSTASIS), None, 0) == ()
    assert [
        homeostasis_node.ceiling_pressure(homeostasis_input(weights, ticks=t))
        for t in (0, ceiling, 2 * ceiling)
    ] == [0.0, 1.0, 2.0], "0, at 1, and above 1"
    missing = {key: value for key, value in weights.items() if key != TRIGGER[HOMEOSTASIS]}
    assert homeostasis_node.call_check(homeostasis_input(missing, ticks=2 * ceiling)) == ()


def test_G2_the_monitor_plans_nothing_on_the_shipping_weights_across_its_score():
    weights = shipping_weights(MONITOR)
    cases = {
        0: monitor_input(weights, graded_unit(3), summary=False),
        1: monitor_input(weights, graded_unit(1)),
        3: monitor_input(weights, graded_unit(3)),
    }
    for count, payload in cases.items():
        show(f"graded {count}", monitor_node.call_check(payload), tag="G2")
        assert monitor_node.graded_predicates(payload) == count
        assert monitor_node.call_check(payload) == ()
        assert triggers.plan(MONITOR, payload, tracked_node_md(MONITOR), None, 0) == ()
    missing = {key: value for key, value in weights.items() if key != TRIGGER[MONITOR]}
    assert monitor_node.call_check(monitor_input(missing, graded_unit(3))) == ()


def test_G2_no_learner_names_a_trigger_key_and_the_signals_are_still_nine():
    learnable = {rule.key for rule in SIGNAL_KEY_MAP}
    show("trigger keys a KeyRule names", sorted(learnable & set(TRIGGER.values())), tag="G2")
    assert not learnable & set(TRIGGER.values())
    assert len(config.ADMISSIBLE_SIGNALS) == 9


@pytest.mark.parametrize("node", AUTHORED)
def test_G2_each_nodes_weights_section_lists_its_trigger_key(node):
    node_md = tracked_node_md(node)
    listed = declared_weight_keys(node_md)
    show(f"{node} `## Weights` run", listed, tag="G2")
    assert TRIGGER[node] in listed, "in the leading run sleep's identity reads"
    assert sorted(listed) == sorted(shipping_weights(node))


def test_G2_the_dry_scenario_in_process_journals_no_outer_node_call(monkeypatch):
    """`tests/dry/conftest.py`'s shape, with the journal read before the sandbox is removed (F3)."""
    captured: dict[int, list] = {}
    real_start = engine.start

    def reading_start(root, *arguments, **keywords):
        outcome = real_start(root, *arguments, **keywords)
        paths = BrainPaths(root=root).task(outcome.task_id)
        captured.update({tick: load_journal(paths.journal(tick)) for tick in paths.journal_ticks()})
        return outcome

    monkeypatch.setattr(engine, "start", reading_start)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli.main(["dry", DRY_SCENARIO])
    calls = [
        (tick, str(entry.node), entry.call_number)
        for tick, entries in sorted(captured.items())
        for entry in entries
        if entry.is_call()
    ]
    show("journalled calls", calls, tag="G2")
    assert code == config.EXIT_DONE
    assert captured, "the journal was read before the teardown"
    assert all(node == config.CORTEX_NODE for _tick, node, _number in calls)


def test_G2_a_dry_subprocess_prints_the_landed_journal_counts(shim_log: Path):
    """The per-tick `journal=` totals, against `tests/dry/test_scripted_task.py:72-87`'s formula."""
    environment = {
        name: value for name, value in os.environ.items() if name != SEAT_SCRIPT_ENV
    }
    environment["PATH"] = f"{SHIM_DIR}{os.pathsep}{os.environ.get('PATH', '')}"
    environment["PROTEAN_SHIM_LOG"] = str(shim_log)
    completed = subprocess.run(
        [sys.executable, "-m", "protean.cli", "dry", DRY_SCENARIO],
        env=environment,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    climb = yaml.safe_load((SCENARIO_DIR / "expected.yaml").read_text(encoding="utf-8"))["climb"]
    printed = [
        int(field.split("=", 1)[1])
        for line in completed.stdout.splitlines()
        if line.startswith("tick ")
        for field in line.split()
        if field.startswith("journal=")
    ]
    expected = [
        len(config.NODE_ORDER) + SEAT_CALL_NUMBER + (1 if row["wave"] else 0) for row in climb
    ]
    show("journal= per tick", printed, tag="G2")
    assert completed.returncode == config.EXIT_DONE, completed.stderr
    assert printed == expected
    assert shim_log.stat().st_size == 0


# --------------------------------------------------------------------------------------
# G3 — the two authored rules fire as specified, and replay as specified
# --------------------------------------------------------------------------------------


def test_G3_homeostasis_plans_one_think_exactly_when_its_pressure_reaches_v():
    base = shipping_weights(HOMEOSTASIS)
    ceiling = int(base[homeostasis_node.CEILING_TICKS])
    node_md = tracked_node_md(HOMEOSTASIS)
    for value in (0.25, 0.5, 1):
        weights = {**base, TRIGGER[HOMEOSTASIS]: value}
        for fraction in (0, 0.2, 0.25, 0.5, 0.75, 1, 1.5):
            payload = homeostasis_input(weights, ticks=int(fraction * ceiling))
            pressure = homeostasis_node.ceiling_pressure(payload)
            planned = triggers.plan(HOMEOSTASIS, payload, node_md, None, 0)
            wanted = [CallType.THINK] if pressure >= value else []
            assert homeostasis_node.call_check(payload) == tuple(wanted), (value, pressure)
            assert types_of(planned) == wanted, (value, pressure)
    show("grid", "v in (0.25, 0.5, 1) x pressure in 0..1.5: think iff pressure >= v", tag="G3")


def test_G3_the_monitor_plans_one_think_exactly_when_its_graded_count_reaches_v():
    base = shipping_weights(MONITOR)
    node_md = tracked_node_md(MONITOR)
    for value in (1, 2, 3):
        weights = {**base, TRIGGER[MONITOR]: value}
        for count in range(5):
            payload = monitor_input(weights, graded_unit(count, withheld=1))
            assert monitor_node.graded_predicates(payload) == count, "the withheld one is not graded"
            wanted = [CallType.THINK] if count >= value else []
            assert monitor_node.call_check(payload) == tuple(wanted), (value, count)
            assert types_of(triggers.plan(MONITOR, payload, node_md, None, 0)) == wanted
    show("grid", "v in (1, 2, 3) x graded in 0..4: think iff graded >= v", tag="G3")


def test_G3_the_monitor_never_thinks_with_no_summary_or_a_vetoed_unit():
    weights = {**shipping_weights(MONITOR), TRIGGER[MONITOR]: MONITOR_ON}
    for payload in (
        monitor_input(weights, graded_unit(3), summary=False),
        monitor_input(weights, graded_unit(3), vetoed=True),
        monitor_input(weights, None),
    ):
        answer = (monitor_node.graded_predicates(payload), monitor_node.call_check(payload))
        show("no subject", answer, tag="G3")
        assert monitor_node.graded_predicates(payload) == 0
        assert monitor_node.call_check(payload) == ()


def test_G3_on_a_fixture_root_each_rule_thinks_exactly_on_the_ticks_its_score_reaches_v(
    tmp_path: Path, workspace: Path, spy
):
    brain = open_root(tmp_path, **{HOMEOSTASIS: HOMEOSTASIS_ON, MONITOR: MONITOR_ON})
    context, _state, port, results = drive(brain, workspace, unplanned(tmp_path, "dispatch_wave"))
    scores = {
        HOMEOSTASIS: (homeostasis_node.ceiling_pressure, HOMEOSTASIS_ON),
        MONITOR: (monitor_node.graded_predicates, MONITOR_ON),
    }
    for node, (score, value) in scores.items():
        seen = of(spy, node)
        show(node, [(score(item.payload), types_of(item.planned)) for item in seen], tag="G3")
        assert len(seen) == len(results), "every fired tick asked the policy once"
        for tick, item in enumerate(seen, start=1):
            wanted = [CallType.THINK] if score(item.payload) >= value else []
            assert types_of(item.planned) == wanted
            numbers = [e.call_number for e in call_entries_of(context, tick) if str(e.node) == node]
            assert numbers == ([1] if wanted else [])
        assert [types_of(item.planned) for item in seen] == [[], [CallType.THINK]], (
            "the first tick reaches neither on-value and the second reaches both"
        )
    assert port.addressees.count(str(CallType.THINK)) == 2


@pytest.mark.parametrize("raw", list(REFUSED), ids=list(REFUSED))
@pytest.mark.parametrize("node", AUTHORED)
def test_G3_a_key_outside_its_domain_is_refused_by_name_before_any_tick(
    tmp_path: Path, workspace: Path, node, raw
):
    brain = open_root(tmp_path)
    write_trigger(brain, node, raw)
    assert load_weights(config.node_dir(node, brain) / "weights.yaml")[TRIGGER[node]] == REFUSED[raw]
    layer, port, _seat = stubs.scripted_layer(brain, "torn_tick.yaml")
    with pytest.raises(CallsDrift) as raised:
        build_context(brain, "task-g3", layer, workspace_path=str(workspace))
    show(f"{node} = {raw}", str(raised.value), tag="G3")
    assert raised.value.node == node and raised.value.key == TRIGGER[node]
    assert raised.value.value == REFUSED[raw]
    assert node in str(raised.value) and TRIGGER[node] in str(raised.value)
    assert port.addressees == [], "no tick ran, so the stand-in was never reached"


@pytest.mark.parametrize("raw", [*LOADS, ABSENT], ids=[*LOADS, "absent"])
@pytest.mark.parametrize("node", AUTHORED)
def test_G3_an_off_or_positive_key_loads(tmp_path: Path, workspace: Path, node, raw):
    brain = open_root(tmp_path)
    write_trigger(brain, node, raw)
    layer, _port, _seat = stubs.scripted_layer(brain, "torn_tick.yaml")
    context = build_context(brain, "task-g3", layer, workspace_path=str(workspace))
    loaded = context.folders[NodeName(node)].weights.get(TRIGGER[node])
    show(f"{node} = {raw}", loaded, tag="G3")
    assert loaded == LOADS.get(raw)


@pytest.mark.parametrize("raw", list(REFUSED), ids=list(REFUSED))
@pytest.mark.parametrize("node", AUTHORED)
def test_G3_a_protean_run_on_each_refused_mutation_exits_seed_drift(
    tmp_path: Path, shim_log: Path, node, raw
):
    brain = open_root(tmp_path)
    write_trigger(brain, node, raw)
    completed = protean(brain, "run", "write the note", log=shim_log)
    show(f"{node} = {raw}", f"rc={completed.returncode} · {completed.stderr.strip()[:90]}", tag="G3")
    assert completed.returncode == config.EXIT_SEED_DRIFT == 24
    assert CallsDrift.__name__ in completed.stderr and node in completed.stderr
    assert BrainPaths(root=brain).task_ids() == [], "refused before any tick: no task state"
    assert shim_log.stat().st_size == 0


@pytest.mark.parametrize("node", AUTHORED)
def test_G3_each_think_is_journalled_at_call_one_under_its_node_with_its_calls_line(
    tmp_path: Path, workspace: Path, node
):
    brain = open_root(tmp_path, **{node: HOMEOSTASIS_ON if node == HOMEOSTASIS else MONITOR_ON})
    context, _state, _port, _results = drive(brain, workspace, unplanned(tmp_path, "dispatch_wave"))
    entry = call_entry(context, 2, node)
    question = entry.payload["question"]
    show(f"{node} think entry", (entry.call_number, str(entry.tier), question[:48]), tag="G3")
    assert entry.call_number == 1
    assert entry.tier is CallType.THINK
    assert entry.payload_model == "ThinkPayload"
    assert question.encode("utf-8") == calls_line(tracked_node_md(node)).encode("utf-8")


def test_G3_a_torn_tick_restores_homeostasiss_think_and_re_derives_its_plan(
    tmp_path: Path, workspace: Path, spy
):
    """F11: torn inside the seat call, after homeostasis's think entry was journalled."""
    brain = open_root(tmp_path, **{HOMEOSTASIS: HOMEOSTASIS_ON})
    script = unplanned(tmp_path, "dispatch_wave")
    context, state, port, _seat = stubs.open_task(
        brain, workspace, script, "task-torn", goal=GOAL, crash_on=3
    )
    state.tick += 1
    run_tick(context, state)
    before = state.model_copy(deep=True)
    state.tick += 1
    with pytest.raises(stubs.TornTick):
        run_tick(context, state)
    torn = of(spy, HOMEOSTASIS)[-1]
    torn_entry = call_entry(context, 2, HOMEOSTASIS)
    show("torn pass addressees", port.addressees, tag="G3")
    assert port.addressees == [str(n) for n in ("manager", CallType.THINK, "manager")]
    assert torn_entry.is_restorable() and types_of(torn.planned) == [CallType.THINK]

    replay_layer, replay_port, _seat = stubs.scripted_layer(brain, script)
    replay_context = build_context(brain, "task-torn", replay_layer, workspace_path=str(workspace))
    replayed = before.model_copy(deep=True)
    replayed.tick += 1
    run_tick(replay_context, replayed, replay=True)
    again = of(spy, HOMEOSTASIS)[-1]
    show("replay addressees", replay_port.addressees, tag="G3")
    assert str(CallType.THINK) not in replay_port.addressees, "the think was restored, not re-made"
    assert call_entry(replay_context, 2, HOMEOSTASIS).envelope == torn_entry.envelope
    assert plan_bytes(again.planned) == plan_bytes(torn.planned)


def test_G3_a_torn_tick_restores_the_monitors_think_on_a_wave_that_restored_whole(
    tmp_path: Path, workspace: Path, spy, monkeypatch
):
    """F10 and F11: torn after the monitor's think entry — the monitor is last, so at its body."""
    brain = open_root(tmp_path, **{MONITOR: MONITOR_ON})
    script = unplanned(tmp_path, "dispatch_wave")
    context, state, port, _seat = stubs.open_task(brain, workspace, script, "task-torn", goal=GOAL)
    state.tick += 1
    run_tick(context, state)
    before = state.model_copy(deep=True)

    def torn_body(payload):
        raise stubs.TornTick("killed after the monitor's think was journalled")

    state.tick += 1
    with monkeypatch.context() as patch:
        patch.setattr(cycle_module, "NODES", {**cycle_module.NODES, MONITOR: torn_body})
        with pytest.raises(stubs.TornTick):
            run_tick(context, state)
    torn = of(spy, MONITOR)[-1]
    torn_entry = call_entry(context, 2, MONITOR)
    keys = journal_keys(context, 2)
    show("torn pass journal", keys, tag="G3")
    assert torn_entry.is_restorable() and types_of(torn.planned) == [CallType.THINK]
    assert (MONITOR, OUTPUT_CALL_NUMBER) not in keys, "torn before the monitor's own entry"

    replay_layer, replay_port, _seat = stubs.scripted_layer(brain, script)
    replay_context = build_context(brain, "task-torn", replay_layer, workspace_path=str(workspace))
    replayed = before.model_copy(deep=True)
    replayed.tick += 1
    result = run_tick(replay_context, replayed, replay=True)
    again = of(spy, MONITOR)[-1]
    show("replay addressees", replay_port.addressees, tag="G3")
    assert result.wave_restored is True, "the wave restored whole"
    assert replay_port.addressees == [], "nothing re-made: seat, wave and think all restored"
    assert call_entry(replay_context, 2, MONITOR).envelope == torn_entry.envelope
    assert plan_bytes(again.planned) == plan_bytes(torn.planned)


def test_G3_after_a_crossed_ceiling_no_later_think_is_issued(
    tmp_path: Path, workspace: Path, spy, monkeypatch
):
    """Homeostasis's stop inhibits every later call of its tick; the planned think is withheld."""
    brain = open_root(tmp_path, **{MONITOR: MONITOR_ON})
    stubs.set_weight(brain, HOMEOSTASIS, **{homeostasis_node.CEILING_TICKS: STOP_AFTER_ONE})
    context, _state, port, results = drive(brain, workspace, unplanned(tmp_path, "dispatch_wave"))
    authored = of(spy, MONITOR)[-1]
    assert monitor_node.graded_predicates(authored.payload) == 0, "a stopped tick grades nothing"
    assert authored.planned == ()

    spy.clear()
    brain = open_root(tmp_path, name="injected")
    stubs.set_weight(brain, HOMEOSTASIS, **{homeostasis_node.CEILING_TICKS: STOP_AFTER_ONE})
    monkeypatch.setattr(
        triggers, "CALL_CHECKS", {**triggers.CALL_CHECKS, MONITOR: lambda payload: (CallType.THINK,)}
    )
    injected_workspace = tmp_path / "injected-workspace"
    injected_workspace.mkdir()
    context, _state, port, results = drive(
        brain, injected_workspace, unplanned(tmp_path, "dispatch_wave"), task="task-stop"
    )
    show("committed per tick", [str(result.committed_terminal) for result in results], tag="G3")
    assert types_of(of(spy, MONITOR)[1].planned) == [CallType.THINK], "planned on the stopped tick"
    assert [str(e.node) for e in call_entries_of(context, 1)].count(MONITOR) == 1
    assert [e for e in call_entries_of(context, 2) if str(e.node) == MONITOR] == []
    assert call_entries_of(context, 2) == [], "no call at all after the crossing"


def test_G3_after_a_no_go_a_planned_delegate_is_withheld_while_a_planned_think_is_issued(
    tmp_path: Path, workspace: Path, spy, monkeypatch
):
    brain = open_root(tmp_path)
    add_calls_line(brain, MONITOR, "- delegate reviewer: does the vetoed unit's plan still stand?")
    monkeypatch.setattr(
        triggers,
        "CALL_CHECKS",
        {
            **triggers.CALL_CHECKS,
            MONITOR: lambda payload: (
                (CallType.THINK, CallType.DELEGATE) if payload.vetoed_unit_id else ()
            ),
        },
    )
    context, _state, port, results = drive(brain, workspace, unplanned(tmp_path, "vetoed_wave"))
    vetoed = of(spy, MONITOR)[-1]
    made = [e for e in call_entries_of(context, 2) if str(e.node) == MONITOR]
    show("planned on the vetoed tick", types_of(vetoed.planned), tag="G3")
    show("issued on the vetoed tick", [(e.call_number, str(e.tier)) for e in made], tag="G3")
    assert vetoed.payload.vetoed_unit_id is not None, "the gate said no_go this tick"
    assert types_of(vetoed.planned) == [CallType.THINK, CallType.DELEGATE]
    assert [(e.call_number, e.tier) for e in made] == [(1, CallType.THINK)]
    assert str(CallType.DELEGATE) not in port.addressees


# --------------------------------------------------------------------------------------
# G6 — a payload's text comes from the seed and the projection, and nothing names a kind
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("node", AUTHORED)
def test_G6_a_planned_question_is_the_nodes_calls_line_byte_for_byte(node):
    node_md = tracked_node_md(node)
    if node == HOMEOSTASIS:
        weights = {**shipping_weights(node), TRIGGER[node]: 0.5}
        payload = homeostasis_input(weights, ticks=150)
    else:
        weights = {**shipping_weights(node), TRIGGER[node]: MONITOR_ON}
        payload = monitor_input(weights, graded_unit(2))
    (planned,) = triggers.plan(node, payload, node_md, None, 0)
    show(f"{node} question", planned.payload["question"][:60], tag="G6")
    assert planned.payload["question"].encode("utf-8") == calls_line(node_md).encode("utf-8")
    assert planned.payload_model == "ThinkPayload"


def test_G6_the_context_is_the_projection_on_input_signatures_serialization_cut_at_the_bound():
    weights = {**shipping_weights(MONITOR), TRIGGER[MONITOR]: MONITOR_ON}
    payload = monitor_input(weights, graded_unit(2, intent="x" * (2 * triggers.CONTEXT_BOUND)))
    body = json.dumps(
        payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    (planned,) = triggers.plan(MONITOR, payload, tracked_node_md(MONITOR), None, 0)
    context = planned.payload["context"]
    show("projection / bound / context", (len(body), triggers.CONTEXT_BOUND, len(context)), tag="G6")
    assert len(body) > triggers.CONTEXT_BOUND, "the fixture projection is longer than the bound"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert digest == input_signature(MONITOR, payload).digest, "input_signature's own bytes"
    assert context == body[: triggers.CONTEXT_BOUND]
    assert len(context) == triggers.CONTEXT_BOUND


@pytest.mark.parametrize("node", AUTHORED)
def test_G6_an_on_key_with_no_calls_line_is_refused_by_name_inside_build_context(
    tmp_path: Path, workspace: Path, node
):
    brain = open_root(tmp_path, **{node: 1})
    drop_calls_line(brain, node)
    layer, port, _seat = stubs.scripted_layer(brain, "torn_tick.yaml")
    with pytest.raises(CallsDrift) as raised:
        build_context(brain, "task-g6", layer, workspace_path=str(workspace))
    show(f"{node}", str(raised.value), tag="G6")
    assert raised.value.node == node and raised.value.missing == (str(CallType.THINK),)
    assert CallsDrift.__name__ in str(raised.value)
    assert f"{node}/NODE.md" in str(raised.value) and triggers.CALLS_HEADING in str(raised.value)
    assert port.addressees == [], "the stand-in was never invoked"


@pytest.mark.parametrize("node", AUTHORED)
def test_G6_a_protean_run_on_that_root_exits_seed_drift_naming_the_refusal(
    tmp_path: Path, shim_log: Path, node
):
    brain = open_root(tmp_path, **{node: 1})
    drop_calls_line(brain, node)
    completed = protean(brain, "run", "write the note", log=shim_log)
    show(f"{node}", f"rc={completed.returncode} · {completed.stderr.strip()}", tag="G6")
    assert completed.returncode == config.EXIT_SEED_DRIFT == 24
    assert CallsDrift.__name__ in completed.stderr
    assert f"{node}/NODE.md" in completed.stderr and triggers.CALLS_HEADING in completed.stderr
    assert shim_log.stat().st_size == 0


def test_G6_the_resume_arm_refuses_on_its_own_path(tmp_path: Path, shim_log: Path):
    """F38, F46: a task stopped on a ceiling with no open item, reseeded, then plainly resumed."""
    brain = open_root(tmp_path)
    stubs.set_weight(brain, HOMEOSTASIS, **{homeostasis_node.CEILING_TICKS: STOP_AFTER_ONE})
    started = protean(brain, "run", "write the note", log=shim_log)
    open_items = list(BrainPaths(root=brain).mailbox_open.glob("*"))
    show("run", f"rc={started.returncode} · open items {open_items}", tag="G6")
    assert started.returncode == config.EXIT_STOPPED, started.stderr
    assert open_items == [], "no open mailbox item, so a plain resume reaches build_context()"

    stubs.set_weight(brain, MONITOR, **{TRIGGER[MONITOR]: MONITOR_ON})
    drop_calls_line(brain, MONITOR)
    reseeded = protean(brain, "resume", "--reseed", log=shim_log)
    show("resume --reseed", f"rc={reseeded.returncode} · {reseeded.stdout.strip()[:90]}", tag="G6")
    assert reseeded.returncode == config.EXIT_STOPPED, "administrative: the committed terminal"
    assert f"reseeded nodes/{MONITOR}/NODE.md" in reseeded.stdout, "the seed change is accepted"

    resumed = protean(brain, "resume", log=shim_log)
    show("resume", f"rc={resumed.returncode} · {resumed.stderr.strip()}", tag="G6")
    assert resumed.returncode == config.EXIT_SEED_DRIFT == 24
    assert CallsDrift.__name__ in resumed.stderr
    assert f"{MONITOR}/NODE.md" in resumed.stderr and triggers.CALLS_HEADING in resumed.stderr
    assert shim_log.stat().st_size == 0

    stubs.set_weight(brain, MONITOR, **{TRIGGER[MONITOR]: None})
    task = engine.current_task(BrainPaths(root=brain))
    layer, _port, _seat = stubs.scripted_layer(brain, "torn_tick.yaml")
    assert build_context(brain, task, layer).folders, "the same root with the key off loads"


@pytest.mark.parametrize("raw", ["null", ABSENT], ids=["null", "absent"])
@pytest.mark.parametrize("node", AUTHORED)
def test_G6_the_same_root_with_the_key_off_loads_without_its_calls_line(
    tmp_path: Path, workspace: Path, node, raw
):
    brain = open_root(tmp_path)
    drop_calls_line(brain, node)
    write_trigger(brain, node, raw)
    layer, _port, _seat = stubs.scripted_layer(brain, "torn_tick.yaml")
    context = build_context(brain, "task-g6", layer, workspace_path=str(workspace))
    assert CallType.THINK not in triggers.parse_calls(context.folders[NodeName(node)].node_md)


@pytest.mark.parametrize("node", AUTHORED)
def test_G6_both_authored_node_mds_carry_a_calls_think_line_and_pass_the_reads_check(node):
    node_md = tracked_node_md(node)
    headings = [line for line in node_md.splitlines() if line.startswith("## ")]
    show(f"{node} headings", headings, tag="G6")
    assert CallType.THINK in triggers.parse_calls(node_md)
    assert headings[-1] == triggers.CALLS_HEADING, "`## Calls` is the file's last section"
    assert headings.index(READS_HEADING) + 1 == headings.index("## Writes"), (
        "nothing sits between `## Reads` and `## Writes`"
    )
    check_reads(node, node_md)


# --------------------------------------------------------------------------------------
# G7 — the live layer attaches `node_calls`, and one Protocol line is the only seam that moved
# --------------------------------------------------------------------------------------
#
# Order W2's cases, appended below W1's: the names they need beyond this module's header are
# imported inside each case. A live layer is built on a `fake_cli.seed_live_root()` copy with the
# stand-in first on `PATH`, so no real binary is ever resolved and nothing spends.

W2_TASK = "task-w2"
W2_UNIT = "u-w2-1"
#: The one library kind the shipping seed defines per class — the dispatch one a live wave runs.
W2_EDITOR = "editor"
#: A think's answer, as the stand-in's second ordinal invocation returns it.
W2_THINK_ANSWER = {
    "answer": "the claim matches the observations",
    "confidence": 0.5,
    "cited_ids": [],
}


def w2_live_root(base: Path, monkeypatch, *, monitor_on: Any = None) -> SimpleNamespace:
    """A spliced copy of the shipping seed, the stand-in on `PATH`, and a task workspace.

    `tests/cortex/test_library.py`'s `library_root()` shape: the stand-in answers the manager with
    a plan naming one `editor` member, that member with an `ExecutorSummary`, and — its second
    ordinal invocation — a think. `runtime.spawn_writable` is spliced to `/tmp` and the stand-in's
    own directory, so the spawn can write its recordings under the per-spawn profile.
    """
    from types import SimpleNamespace

    from protean.cortex.live.config import RUNTIME_BLOCK, SPAWN_WRITABLE_KEY
    from tests.cortex import fake_cli

    binaries = fake_cli.install(
        base / "bin",
        [
            fake_cli.wave_plan(W2_UNIT, f"{W2_TASK}-g1", (W2_EDITOR,)),
            fake_cli.envelope(W2_THINK_ANSWER),
        ],
        members=fake_cli.member_answers((W2_EDITOR,), W2_UNIT),
    )
    fake_cli.on_path(monkeypatch, binaries)
    root = fake_cli.seed_live_root(base / "brain")
    seats_file = root / "seats.yaml"
    payload = yaml.safe_load(seats_file.read_text(encoding="utf-8"))
    payload[RUNTIME_BLOCK][SPAWN_WRITABLE_KEY] = [
        fake_cli.FIXTURE_WRITABLE_TREE,
        str(binaries.resolve()),
    ]
    seats_file.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    if monitor_on is not None:
        stubs.set_weight(root, MONITOR, **{TRIGGER[MONITOR]: monitor_on})
    workspace = base / "clone"
    workspace.mkdir()
    return SimpleNamespace(root=root, binaries=binaries, workspace=workspace.resolve())


def w2_answering_port(asked: list[tuple[str, str]]):
    """A port that answers every node call type, recording `(addressee, node)` per call."""

    def port(addressee, request):
        asked.append((str(addressee), str(request.node)))
        if str(addressee) == str(CallType.ESCALATE):
            return stubs.envelope({"answer": "noted"})
        return stubs.envelope({"answer": "an answer"})

    return port


def w2_planned(call_type: CallType, text: str) -> PlannedCall:
    field = "concern" if call_type is CallType.ESCALATE else "question"
    model = triggers.PAYLOAD_MODEL_NAMES[call_type]
    return PlannedCall(type=call_type, payload={field: text}, payload_model=model)


def test_G7_build_live_layer_attaches_call_desks_over_its_one_spawns_and_the_seeds_bound(
    tmp_path: Path, monkeypatch
):
    """`node_calls` is a `CallDesks` with an empty static plan and the seed's delegate bound, its
    `spawns` seam the **same object** as the layer's, and every other field as it was."""
    import dataclasses

    from protean.cortex.calls import CallDesks
    from protean.cortex.layer import build_live_layer
    from protean.cortex.live.invoke import LiveSeat
    from protean.cortex.live.session import LiveSessionBook
    from protean.cortex.live.wave import SpawnDesks
    from protean.cortex.router import LadderRouter
    from tests.cortex import fake_cli

    world = w2_live_root(tmp_path, monkeypatch)
    layer = build_live_layer(root=world.root)
    attached = sorted(
        item.name for item in dataclasses.fields(layer) if getattr(layer, item.name) is not None
    )
    desks = layer.node_calls
    show("attached seams", attached, tag="G7")
    show("node_calls", (type(desks).__name__, dict(desks.plan), desks.delegate_bound), tag="G7")
    assert isinstance(layer.node_calls, CallDesks)
    assert dict(layer.node_calls.plan) == {}, "an empty static plan: the policy hands each node's"
    assert layer.node_calls.delegate_bound == fake_cli.seats_of(world.root).max_tick_delegates == 1
    assert isinstance(layer.spawns, SpawnDesks)
    assert layer.node_calls.spawns is layer.spawns, "one SpawnDesks instance, handed to both seams"
    assert layer.node_calls.port is layer.port, "the one port"
    assert attached == ["calls", "node_calls", "port", "router", "sessions", "spawns"]
    assert isinstance(layer.router, LadderRouter) and isinstance(layer.port, LiveSeat)
    assert isinstance(layer.sessions, LiveSessionBook) and layer.calls == layer.port.calls
    assert layer.habits is None and layer.port.workspace_path == ""


def test_G7_tickcalls_run_and_the_desks_run_carry_one_optional_parameter_beyond_node():
    declared = inspect.signature(TickCalls.run)
    desks = inspect.signature(NodeCallDesk.run)
    show("TickCalls.run", str(declared), tag="G7")
    show("NodeCallDesk.run", str(desks), tag="G7")
    for signature in (declared, desks):
        names = list(signature.parameters)
        assert names[0] == "self" and names[1] == "node"
        beyond = names[2:]
        assert len(beyond) == 1, "exactly one parameter beyond `node`"
        parameter = signature.parameters[beyond[0]]
        assert parameter.default is not inspect.Parameter.empty, "and it is optional"
    assert list(declared.parameters)[2] == list(desks.parameters)[2]
    assert (
        declared.parameters[list(declared.parameters)[2]].default
        == desks.parameters[list(desks.parameters)[2]].default
        == ()
    ), "with the same default: none handed"
    desk = NodeCallDesk(port=w2_answering_port([]), task=W2_TASK, tick=1)
    assert isinstance(desk, TickCalls)


def test_G7_a_static_plan_naming_the_node_is_issued_whatever_the_desk_is_handed():
    """The fixture's plan outranks the policy's for the node it names — so every landed call
    test keeps its tick (their batteries are this row's second capture)."""
    asked: list[tuple[str, str]] = []
    static = {HOMEOSTASIS: (w2_planned(CallType.THINK, "the fixture's question"),)}
    desk = NodeCallDesk(port=w2_answering_port(asked), task=W2_TASK, tick=1, plan=static)
    handed_cases = (
        (),
        (w2_planned(CallType.ESCALATE, "the policy's concern"),),
        (w2_planned(CallType.THINK, "the policy's question"),),
    )
    for handed in handed_cases:
        desk.run(NodeName.HOMEOSTASIS, handed)
    issued = [(str(r.call.type), r.call.payload.get("question")) for r in desk.records]
    show("issued for three different hands", issued, tag="G7")
    assert asked == [(str(CallType.THINK), HOMEOSTASIS)] * 3
    assert issued == [(str(CallType.THINK), "the fixture's question")] * 3


def test_G7_a_static_plan_not_naming_the_node_issues_exactly_the_handed_plan():
    asked: list[tuple[str, str]] = []
    static = {HOMEOSTASIS: (w2_planned(CallType.THINK, "the fixture's question"),)}
    desk = NodeCallDesk(port=w2_answering_port(asked), task=W2_TASK, tick=1, plan=static)
    handed = (
        w2_planned(CallType.THINK, "the policy's question"),
        w2_planned(CallType.ESCALATE, "the policy's concern"),
    )
    desk.run(NodeName.ANTERIOR_CINGULATE, handed)
    desk.run(NodeName.HIPPOCAMPUS, ())
    made = [(str(r.call.node), r.call.call_number, str(r.call.type)) for r in desk.records]
    show("issued", made, tag="G7")
    assert made == [(MONITOR, 1, str(CallType.THINK)), (MONITOR, 2, str(CallType.ESCALATE))]
    assert desk.records[0].call.payload["question"] == "the policy's question"
    assert desk.records[1].call.payload["concern"] == "the policy's concern"
    assert asked == [(str(CallType.THINK), MONITOR), (str(CallType.ESCALATE), MONITOR)]


def test_G7_a_live_tick_with_the_monitors_key_on_makes_one_think_and_writes_one_receipt(
    tmp_path: Path, monkeypatch, spy
):
    """The production layer over a spliced seed, the stand-in answering: one wave, the monitor
    grading one predicate against its summary, and its key at `1` — one think through the port,
    journalled at `call# = 1` and receipted once. The key-off control makes none."""
    from protean.cortex.layer import build_live_layer
    from protean.mailbox.files import build as build_mailbox
    from protean.state.seat_calls import load_seat_calls
    from tests.cortex import fake_cli

    def one_live_tick(base: Path, monitor_on: Any):
        world = w2_live_root(base, monkeypatch, monitor_on=monitor_on)
        outcome = engine.start(
            world.root,
            GOAL,
            build_live_layer(root=world.root),
            mailbox=build_mailbox(world.root),
            workspace_path=str(world.workspace),
            task_id=W2_TASK,
            max_ticks=1,
        )
        paths = BrainPaths(root=world.root).task(W2_TASK)
        calls = [
            (str(entry.node), entry.call_number, str(entry.tier))
            for entry in load_journal(paths.journal(1))
            if entry.is_call()
        ]
        receipts = [
            (str(record.node), record.call_number, str(record.tier))
            for record in load_seat_calls(paths.seat_calls)
        ]
        return world, outcome, calls, receipts

    world, outcome, calls, receipts = one_live_tick(tmp_path / "on", MONITOR_ON)
    thinks = [call for call in calls if call[2] == str(CallType.THINK)]
    think_receipts = [record for record in receipts if record[2] == str(CallType.THINK)]
    show("journalled calls", calls, tag="G7")
    show("receipts", receipts, tag="G7")
    show("calls by type", outcome.ticks[0].calls_by_type, tag="G7")
    assert monitor_node.graded_predicates(of(spy, MONITOR)[-1].payload) == 1
    assert thinks == [(MONITOR, 1, str(CallType.THINK))], "exactly one think, the monitor's"
    assert think_receipts == [(MONITOR, 1, str(CallType.THINK))], "and one SeatCallRecord for it"
    assert outcome.ticks[0].calls_by_type[str(CallType.THINK)] == 1
    assert fake_cli.invocations(world.binaries) == 2, "through the port: the seat call, the think"
    assert {item.bound for item in spy} == {1}, "the policy was handed the seed's bound"

    spy.clear()
    control, outcome, calls, receipts = one_live_tick(tmp_path / "off", None)
    show("key-off control calls", calls, tag="G7")
    assert all(call[2] != str(CallType.THINK) for call in calls)
    assert all(record[2] != str(CallType.THINK) for record in receipts)
    assert fake_cli.invocations(control.binaries) == 1, "the seat call alone"


def test_G7_cycle_py_imports_nothing_from_protean_cortex():
    """Every import statement in the module, nested ones included, read off its syntax tree."""
    import ast

    tree = ast.parse(Path(cycle_module.__file__).read_text(encoding="utf-8"))
    imported = sorted(
        {
            *(
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            ),
            *(node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)),
        }
    )
    show("cycle.py imports", [name for name in imported if name.startswith("protean")], tag="G7")
    assert imported, "the tree was read"
    assert [name for name in imported if name.startswith("protean.cortex")] == []


# --------------------------------------------------------------------------------------
# G8 — the per-tick delegate bound is a required seed key, seeded 1, applied at plan time
# --------------------------------------------------------------------------------------

#: The first two nodes in `NODE_ORDER`, both pre-cortex, each given a delegate by a check map the
#: test injects — so a tick torn inside the seat call has already planned both.
W2_FIRST, W2_SECOND = config.NODE_ORDER[0], config.NODE_ORDER[1]
#: The kind the delegate lines name: the one `three_call_types.yaml`'s scripted delegate answers as.
W2_KIND = "reviewer"
#: The YAML text each refused value is written as, and what `safe_load` makes of it (F8).
W2_REFUSED_BOUNDS = {"1.5": 1.5, "true": True, "-1": -1, "'1'": "1"}
#: The shipping seed's line, as `fake_cli.seed_live_root()`'s `safe_dump` writes it.
W2_BOUND_LINE = "  max_tick_delegates: 1\n"


def w2_seeded_copy(base: Path, monkeypatch, raw: str | None = None) -> Path:
    """A `fake_cli.seed_live_root()` copy, its delegate-bound line rewritten to `raw` YAML text —
    or removed, for `raw=""`. `None` leaves the shipping value."""
    from tests.cortex import fake_cli

    fake_cli.on_path(monkeypatch, fake_cli.install(base / "bin"))
    root = fake_cli.seed_live_root(base / "brain")
    seats_file = root / "seats.yaml"
    text = seats_file.read_text(encoding="utf-8")
    assert text.count(W2_BOUND_LINE) == 1, "the copy carries the shipping bound's line"
    if raw is not None:
        replacement = "" if raw == "" else f"  max_tick_delegates: {raw}\n"
        seats_file.write_text(text.replace(W2_BOUND_LINE, replacement), encoding="utf-8")
    return root


def w2_delegate_root(tmp_path: Path) -> Path:
    """A throwaway seed whose first two nodes each carry a `## Calls` delegate line; keys off."""
    brain = open_root(tmp_path)
    for node in (W2_FIRST, W2_SECOND):
        path = config.node_dir(node, brain) / "NODE.md"
        text = path.read_text(encoding="utf-8").rstrip("\n")
        if f"\n{triggers.CALLS_HEADING}\n" not in f"{text}\n":
            text = f"{text}\n\n{triggers.CALLS_HEADING}\n"
        line = f"- delegate {W2_KIND}: what does {node} need to know this tick?"
        path.write_text(f"{text}\n{line}\n", encoding="utf-8")
        assert triggers.parse_calls(path.read_text(encoding="utf-8"))[CallType.DELEGATE].kind
    return brain


def w2_delegate_script(tmp_path: Path, *, answered: bool = True) -> str:
    """`three_call_types.yaml` with its `calls:` plan removed; `answered=False` also drops its
    delegate answer, so a delegate is refused and leaves an entry with no envelope."""
    path = Path(unplanned(tmp_path, "three_call_types"))
    if not answered:
        script = yaml.safe_load(path.read_text(encoding="utf-8"))
        script["responses"] = [
            row for row in script["responses"] if row.get("tier") != str(CallType.DELEGATE)
        ]
        path = tmp_path / "three_call_types-no-delegate.yaml"
        path.write_text(yaml.safe_dump(script, sort_keys=False), encoding="utf-8")
    return str(path)


def w2_both_delegate(monkeypatch) -> None:
    """The injected check map: the first two nodes each plan one delegate, every tick."""
    monkeypatch.setattr(
        triggers,
        "CALL_CHECKS",
        {
            **triggers.CALL_CHECKS,
            W2_FIRST: lambda payload: (CallType.DELEGATE,),
            W2_SECOND: lambda payload: (CallType.DELEGATE,),
        },
    )


def w2_bounded(brain: Path, script: str, bound: int | None, *, crash_on: int | None = None):
    """`stubs.scripted_layer()`'s layer with its node-call desks publishing `bound` — the one field
    the live layer's desks carry that the scripted layer's do not."""
    import dataclasses

    from protean.cortex.calls import CallDesks

    layer, port, _seat = stubs.scripted_layer(brain, script, crash_on=crash_on)
    desks = CallDesks(port=port, plan=layer.node_calls.plan, delegate_bound=bound)
    return dataclasses.replace(layer, node_calls=desks), port


def w2_tick(brain: Path, workspace: Path, script: str, bound: int | None, *, crash_on=None):
    """Open a task on the bounded layer and run its first tick. A tear is returned, not raised."""
    from types import SimpleNamespace

    from protean.runtime.engine import new_state

    layer, port = w2_bounded(brain, script, bound, crash_on=crash_on)
    context = build_context(brain, W2_TASK, layer, workspace_path=str(workspace))
    state = new_state(W2_TASK, GOAL, context)
    before = state.model_copy(deep=True)
    state.tick += 1
    torn = False
    try:
        run_tick(context, state)
    except stubs.TornTick:
        torn = True
    return SimpleNamespace(
        context=context, layer=layer, port=port, before=before, torn=torn
    )


def w2_calls(context, tick: int = 1) -> list[tuple[str, int, str]]:
    return [(str(e.node), e.call_number, str(e.tier)) for e in call_entries_of(context, tick)]


def test_G8_runtime_keys_carries_the_delegate_bound_and_the_seed_carries_it_at_one():
    from protean.cortex.live.config import (
        DELEGATE_BOUND_KEY,
        RUNTIME_BLOCK,
        RUNTIME_KEYS,
        load_seats,
    )

    seeded = yaml.safe_load((BRAIN_SEED / "seats.yaml").read_text(encoding="utf-8"))
    value = seeded[RUNTIME_BLOCK][DELEGATE_BOUND_KEY]
    show("RUNTIME_KEYS", list(RUNTIME_KEYS), tag="G8")
    show(f"{RUNTIME_BLOCK}.{DELEGATE_BOUND_KEY}", value, tag="G8")
    assert DELEGATE_BOUND_KEY in RUNTIME_KEYS
    assert value == 1 and type(value) is int
    assert load_seats(BRAIN_SEED).max_tick_delegates == 1


def test_G8_a_seed_missing_the_delegate_bound_refuses_at_load_by_name(
    tmp_path: Path, monkeypatch
):
    from protean.cortex.live.config import (
        DELEGATE_BOUND_KEY,
        RUNTIME_BLOCK,
        SeatConfigError,
        load_seats,
    )

    root = w2_seeded_copy(tmp_path, monkeypatch, raw="")
    assert DELEGATE_BOUND_KEY not in (root / "seats.yaml").read_text(encoding="utf-8")
    with pytest.raises(SeatConfigError) as raised:
        load_seats(root)
    show("missing", str(raised.value), tag="G8")
    assert DELEGATE_BOUND_KEY in str(raised.value) and RUNTIME_BLOCK in str(raised.value)


@pytest.mark.parametrize("raw", list(W2_REFUSED_BOUNDS), ids=list(W2_REFUSED_BOUNDS))
def test_G8_a_loaded_copy_carrying_a_bound_outside_its_domain_refuses_by_name(
    tmp_path: Path, monkeypatch, raw
):
    from protean.cortex.live.config import (
        DELEGATE_BOUND_KEY,
        RUNTIME_BLOCK,
        SeatConfigError,
        load_seats,
    )

    root = w2_seeded_copy(tmp_path, monkeypatch, raw=raw)
    loaded = yaml.safe_load((root / "seats.yaml").read_text(encoding="utf-8"))
    assert loaded[RUNTIME_BLOCK][DELEGATE_BOUND_KEY] == W2_REFUSED_BOUNDS[raw]
    assert type(loaded[RUNTIME_BLOCK][DELEGATE_BOUND_KEY]) is type(W2_REFUSED_BOUNDS[raw])
    with pytest.raises(SeatConfigError) as raised:
        load_seats(root)
    show(f"bound = {raw}", str(raised.value), tag="G8")
    assert f"{RUNTIME_BLOCK}.{DELEGATE_BOUND_KEY}" in str(raised.value)


def test_G8_a_bound_of_zero_loads_and_plans_no_delegate(
    tmp_path: Path, workspace: Path, spy, monkeypatch
):
    from protean.cortex.live.config import load_seats

    loaded = load_seats(w2_seeded_copy(tmp_path / "seed", monkeypatch, raw="0"))
    assert loaded is not None and loaded.max_tick_delegates == 0

    w2_both_delegate(monkeypatch)
    brain = w2_delegate_root(tmp_path)
    run = w2_tick(brain, workspace, w2_delegate_script(tmp_path), loaded.max_tick_delegates)
    planned = {item.node: types_of(item.planned) for item in spy}
    show("planned on a desk bound to 0", planned, tag="G8")
    assert planned[W2_FIRST] == [] and planned[W2_SECOND] == []
    assert str(CallType.DELEGATE) not in run.port.addressees
    assert all(call[2] != str(CallType.DELEGATE) for call in w2_calls(run.context))


def test_G8_the_live_call_desks_carries_the_loaded_bound_and_each_ticks_desk_publishes_it(
    tmp_path: Path, monkeypatch
):
    from protean.cortex.layer import build_live_layer
    from protean.runtime.seat import tick_calls_of

    for name, raw, expected in (("shipping", None, 1), ("rewritten", "3", 3)):
        root = w2_seeded_copy(tmp_path / name, monkeypatch, raw=raw)
        layer = build_live_layer(root=root)
        desks = [tick_calls_of(layer, W2_TASK, tick) for tick in (1, 2)]
        show(f"{name} seed", (layer.node_calls.delegate_bound,
                              [desk.delegate_bound for desk in desks]), tag="G8")
        assert layer.node_calls.delegate_bound == expected
        assert desks[0] is not desks[1], "one desk per tick"
        assert [getattr(desk, "delegate_bound", None) for desk in desks] == [expected, expected]


def test_G8_on_a_desk_bound_to_one_the_tick_plans_the_first_node_in_node_order_only(
    tmp_path: Path, workspace: Path, spy, monkeypatch
):
    w2_both_delegate(monkeypatch)
    brain = w2_delegate_root(tmp_path)
    run = w2_tick(brain, workspace, w2_delegate_script(tmp_path), 1)
    first, second = of(spy, W2_FIRST)[-1], of(spy, W2_SECOND)[-1]
    desk = run.layer.node_calls.opened[-1]
    show("planned", [(i.node, i.bound, i.delegates, types_of(i.planned)) for i in spy], tag="G8")
    show("journalled calls", w2_calls(run.context), tag="G8")
    assert (first.bound, first.delegates, types_of(first.planned)) == (1, 0, [CallType.DELEGATE])
    assert (second.bound, second.delegates, types_of(second.planned)) == (1, 1, [])
    assert run.port.addressees.count(str(CallType.DELEGATE)) == 1, "the second is not issued"
    assert (W2_FIRST, 1, str(CallType.DELEGATE)) in w2_calls(run.context)
    assert all(call[0] != W2_SECOND for call in w2_calls(run.context)), "nor journalled"
    assert [str(r.call.node) for r in desk.records] == [W2_FIRST], "nor refused"
    assert all(record.refusal is None for record in desk.records)


@pytest.mark.parametrize("restored", [True, False], ids=["restored", "re-issued"])
def test_G8_a_torn_tick_replays_to_the_same_plan_whether_or_not_the_first_nodes_calls_restored(
    tmp_path: Path, workspace: Path, spy, monkeypatch, restored
):
    """Torn inside the seat call — the tick's second port call — after both pre-cortex nodes were
    planned. Answered, the first node's delegate is restorable and restores on the replay; refused,
    its entry carries no envelope and the replay re-issues it. Either way the count is the same."""
    w2_both_delegate(monkeypatch)
    brain = w2_delegate_root(tmp_path)
    script = w2_delegate_script(tmp_path, answered=restored)
    torn = w2_tick(brain, workspace, script, 1, crash_on=2)
    assert torn.torn
    (entry,) = [e for e in call_entries_of(torn.context, 1) if str(e.node) == W2_FIRST]
    assert entry.is_restorable() is restored
    torn_plans = {node: of(spy, node)[-1] for node in (W2_FIRST, W2_SECOND)}

    spy.clear()
    layer, port = w2_bounded(brain, script, 1)
    context = build_context(brain, W2_TASK, layer, workspace_path=str(workspace))
    replayed = torn.before.model_copy(deep=True)
    replayed.tick += 1
    run_tick(context, replayed, replay=True)
    show("torn pass addressees", torn.port.addressees, tag="G8")
    show("replay addressees", port.addressees, tag="G8")
    for node, before in torn_plans.items():
        again = of(spy, node)[-1]
        assert (again.bound, again.delegates) == (before.bound, before.delegates), node
        assert plan_bytes(again.planned) == plan_bytes(before.planned), node
    assert types_of(torn_plans[W2_SECOND].planned) == [], "the second is past the bound, both times"
    assert port.addressees.count(str(CallType.DELEGATE)) == (0 if restored else 1)
    assert all(call[0] != W2_SECOND for call in w2_calls(context))


def test_G8_a_desk_publishing_no_bound_plans_both(
    tmp_path: Path, workspace: Path, spy, monkeypatch
):
    w2_both_delegate(monkeypatch)
    brain = w2_delegate_root(tmp_path)
    run = w2_tick(brain, workspace, w2_delegate_script(tmp_path), None)
    desk = run.layer.node_calls.opened[-1]
    planned = {node: types_of(of(spy, node)[-1].planned) for node in (W2_FIRST, W2_SECOND)}
    show("planned with no bound", planned, tag="G8")
    assert getattr(desk, "delegate_bound", None) is None, "the scripted layer publishes none"
    assert planned == {W2_FIRST: [CallType.DELEGATE], W2_SECOND: [CallType.DELEGATE]}
    assert run.port.addressees.count(str(CallType.DELEGATE)) == 2
    calls = w2_calls(run.context)
    assert (W2_FIRST, 1, str(CallType.DELEGATE)) in calls
    assert (W2_SECOND, 1, str(CallType.DELEGATE)) in calls


def test_G8_the_four_spawn_bounds_and_their_seed_values_are_unchanged():
    """The bound joins `RUNTIME_KEYS` beside the four and is none of them. The wave arithmetic's
    own receipt is `git diff A2I_BASE -- src/protean/cortex/live/wave.py`, empty."""
    from protean.cortex.live.config import (
        DELEGATE_BOUND_KEY,
        RUNTIME_BLOCK,
        SPAWN_BOUND_KEYS,
        SPAWN_CAP_CEILINGS,
    )

    seeded = yaml.safe_load((BRAIN_SEED / "seats.yaml").read_text(encoding="utf-8"))
    values = {key: seeded[RUNTIME_BLOCK][key] for key in SPAWN_BOUND_KEYS}
    show("the four bounds", values, tag="G8")
    assert SPAWN_BOUND_KEYS == (
        "spawn_max_call_usd",
        "spawn_timeout_seconds",
        "max_wave_members",
        "spawn_max_wave_usd",
    )
    assert DELEGATE_BOUND_KEY not in SPAWN_BOUND_KEYS
    assert values == {
        "spawn_max_call_usd": 5.0,
        "spawn_timeout_seconds": 1800,
        "max_wave_members": 4,
        "spawn_max_wave_usd": 10.0,
    }
    assert dict(SPAWN_CAP_CEILINGS) == {
        "max_call_usd": "spawn_max_call_usd",
        "timeout_seconds": "spawn_timeout_seconds",
    }


# --------------------------------------------------------------------------------------
# G9 — the think answer reaches the body on the input model, and moves no authored output
# --------------------------------------------------------------------------------------
#
# Order W3's cases, appended below W2's, with G6's carrier-unset clause after them; the names they
# need beyond this module's header are imported inside each case. What a body was handed is read
# by wrapping the two authored bodies in `cycle.NODES` — the table `cycle.py` calls them through.

#: The carrier's field name on both input models — the one `## Reads` line each node gained.
W3_CARRIER = "think_answer"
W3_TASK = "task-w3"
#: Each authored node's input model, and its field set as it stood at `A2I_BASE`.
W3_MODELS = {HOMEOSTASIS: HomeostasisInput, MONITOR: MonitorInput}
W3_LANDED_FIELDS = {
    HOMEOSTASIS: {"task_id", "tick", "weights", "cost", "ceiling_overrides", "constraints"},
    MONITOR: {
        "task_id",
        "tick",
        "weights",
        "goals",
        "units",
        "unit_windows",
        "trap_dismissals",
        "executor_summary",
        "vetoed_unit_id",
        "wave_status",
    },
}
#: The answer `unplanned()` gives a think: `firing_decline.yaml`'s, with no interrupt.
W3_DONOR_ANSWER = "nothing in the window is worth ranking"


def w3_bodies(monkeypatch) -> list[tuple[str, int, Any]]:
    """Wrap the two authored bodies in `cycle.NODES`; `(node, tick, payload)` per body run.

    The payload is kept **by reference**, because it is the object `node_inputs` records and the
    boundary digests: a copy taken here would miss what the boundary later does to the state the
    projection shares, and the prediction's signature is over the object, not over a copy.
    """
    seen: list[tuple[str, int, Any]] = []

    def wrap(node: str, body):
        def _body(payload):
            seen.append((node, payload.tick, payload))
            return body(payload)

        return _body

    monkeypatch.setattr(
        cycle_module,
        "NODES",
        {**cycle_module.NODES, **{node: wrap(node, cycle_module.NODES[node]) for node in AUTHORED}},
    )
    return seen


def w3_handed(seen: list[tuple[str, int, Any]], node: str, tick: int):
    """The one input this node's body was handed on this tick."""
    (payload,) = [item for name, at, item in seen if name == node and at == tick]
    return payload


def w3_decoded(entry, tick: int):
    """A journalled think entry's envelope, decoded on the one `decode_seat_result()` path."""
    from protean.runtime.seat import decode_seat_result

    return decode_seat_result(CallType.THINK, entry.envelope, tick)


def w3_on(node: str) -> dict[str, Any]:
    return {node: HOMEOSTASIS_ON if node == HOMEOSTASIS else MONITOR_ON}


def w3_two_thinks_for_one_node(tmp_path: Path) -> str:
    """`two_thinks.yaml` with a second homeostasis think appended to its static plan.

    The landed fixture names one think for homeostasis and one for the hippocampus; `parse_plan`
    lets one node carry two, which is the case "first by `call#`" exists for. Written under the
    test's temp directory; `fixtures/` is read, never written.
    """
    script = yaml.safe_load((CALLS_FIXTURES / "two_thinks.yaml").read_text(encoding="utf-8"))
    script["calls"].append(
        {"node": HOMEOSTASIS, "type": "think", "payload": {"question": "and after this tick?"}}
    )
    path = tmp_path / "two_thinks-two-for-homeostasis.yaml"
    path.write_text(yaml.safe_dump(script, sort_keys=False), encoding="utf-8")
    return str(path)


def w3_numbered(port):
    """The desk's port with each think's scripted answer carrying its own `call#`.

    A scripted think is request-keyed on its addressee alone, so two thinks in one tick get one
    answer; numbering them is what makes "the first by `call#`" observable. Everything else, and
    the recording port's own count, is the scripted layer's as it was.
    """

    def numbered(addressee, request):
        envelope = port(addressee, request)
        if str(addressee) != str(CallType.THINK):
            return envelope
        result = dict(envelope.parsed_result())
        result["answer"] = f"call {request.call_number}: {result['answer']}"
        return envelope.model_copy(update={"result": json.dumps(result)})

    return numbered


def w3_raising_script(tmp_path: Path) -> str:
    """`dispatch_wave.yaml`, its `calls:` plan removed, with `two_thinks.yaml`'s think answer —
    the one that raises rather than guesses — as its only think response."""
    script = yaml.safe_load((CALLS_FIXTURES / "dispatch_wave.yaml").read_text(encoding="utf-8"))
    script.pop("calls", None)
    donor = yaml.safe_load((CALLS_FIXTURES / "two_thinks.yaml").read_text(encoding="utf-8"))
    (think,) = [row for row in donor["responses"] if row.get("tier") == str(CallType.THINK)]
    assert think["result"]["interrupt"], "the donor's think raises"
    assert not any(row.get("tier") == str(CallType.THINK) for row in script["responses"])
    script["responses"].append(think)
    path = tmp_path / "dispatch_wave-raising-think.yaml"
    path.write_text(yaml.safe_dump(script, sort_keys=False), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("node", AUTHORED)
def test_G9_each_authored_input_model_carries_exactly_one_optional_think_result_field(node):
    """One new field, optional, `ThinkResult | None`, default `None`, named in `## Reads`."""
    import typing

    from protean.state.reads import parse_reads_section
    from protean.state.seats import ThinkResult

    model = W3_MODELS[node]
    added = set(model.model_fields) - W3_LANDED_FIELDS[node]
    field = model.model_fields[W3_CARRIER]
    annotation = get_type_hints(model)[W3_CARRIER]
    listed = parse_reads_section(tracked_node_md(node))
    show(f"{model.__name__} added", sorted(added), tag="G9")
    show(f"{model.__name__}.{W3_CARRIER}", (str(annotation), field.default), tag="G9")
    assert W3_LANDED_FIELDS[node] <= set(model.model_fields), "no landed field moved"
    assert added == {W3_CARRIER}, "exactly one new field"
    assert set(typing.get_args(annotation)) == {ThinkResult, type(None)}
    assert not field.is_required() and field.default is None
    assert W3_CARRIER in listed and listed[-1] == W3_CARRIER
    check_reads(node, tracked_node_md(node))


def test_G9_no_other_input_model_gains_the_carrier():
    """The hippocampus's and the gate's rules are deferred (E5, E4), and the thalamus calls not."""
    others = {
        str(node): sorted(models[0].model_fields)
        for node, models in NODE_INPUT_MODELS.items()
        if str(node) not in AUTHORED and node is not NodeName.CORTEX
    }
    show("other input models", {node: len(fields) for node, fields in others.items()}, tag="G9")
    assert sorted(others) == ["basal_ganglia", "hippocampus", "thalamus"]
    assert all(W3_CARRIER not in fields for fields in others.values())


@pytest.mark.parametrize("node", AUTHORED)
def test_G9_on_a_key_on_fixture_tick_the_body_receives_its_thinks_decoded_answer(
    tmp_path: Path, workspace: Path, monkeypatch, node
):
    from protean.state.seats import ThinkResult

    bodies = w3_bodies(monkeypatch)
    brain = open_root(tmp_path, **w3_on(node))
    context, _state, port, _results = drive(
        brain, workspace, unplanned(tmp_path, "dispatch_wave"), task=W3_TASK
    )
    entry = call_entry(context, 2, node)
    received = w3_handed(bodies, node, 2).think_answer
    other = MONITOR if node == HOMEOSTASIS else HOMEOSTASIS
    show(f"{node} body, tick 1 / tick 2", (w3_handed(bodies, node, 1).think_answer, received),
         tag="G9")
    assert w3_handed(bodies, node, 1).think_answer is None, "tick 1 planned no think"
    assert isinstance(received, ThinkResult) and received.answer == W3_DONOR_ANSWER
    assert received == w3_decoded(entry, 2), "equal to the journalled envelope's decode"
    assert w3_handed(bodies, other, 2).think_answer is None, "the other node made no think"
    assert port.addressees.count(str(CallType.THINK)) == 1


def test_G9_on_the_production_layer_against_the_stand_in_the_monitors_body_receives_its_think(
    tmp_path: Path, monkeypatch
):
    """W2's live tick — `build_live_layer()` over a spliced seed, `fake_cli` answering, the
    monitor's key at `1` — with the monitor's body read: the think the stand-in answered is the
    `ThinkResult` its body was handed."""
    from protean.cortex.layer import build_live_layer
    from protean.mailbox.files import build as build_mailbox
    from protean.state.seats import ThinkResult
    from tests.cortex import fake_cli

    bodies = w3_bodies(monkeypatch)
    world = w2_live_root(tmp_path, monkeypatch, monitor_on=MONITOR_ON)
    engine.start(
        world.root,
        GOAL,
        build_live_layer(root=world.root),
        mailbox=build_mailbox(world.root),
        workspace_path=str(world.workspace),
        task_id=W2_TASK,
        max_ticks=1,
    )
    journal = load_journal(BrainPaths(root=world.root).task(W2_TASK).journal(1))
    (entry,) = [e for e in journal if e.is_call() and str(e.node) == MONITOR]
    received = w3_handed(bodies, MONITOR, 1).think_answer
    show("the monitor's body was handed", received, tag="G9")
    assert isinstance(received, ThinkResult)
    assert received == w3_decoded(entry, 1), "equal to the journalled envelope's decode"
    assert received.answer == W2_THINK_ANSWER["answer"]
    assert w3_handed(bodies, HOMEOSTASIS, 1).think_answer is None
    assert fake_cli.invocations(world.binaries) == 2, "the seat call and the think, no more"


def test_G9_with_two_thinks_for_one_node_the_body_receives_the_first_by_call_number(
    tmp_path: Path, workspace: Path, monkeypatch
):
    """`fixtures/calls/two_thinks.yaml`, its static plan naming a second homeostasis think."""
    import dataclasses

    from protean.cortex.calls import CallDesks
    from protean.runtime.engine import new_state

    bodies = w3_bodies(monkeypatch)
    brain = open_root(tmp_path)
    layer, port, _seat = stubs.scripted_layer(brain, w3_two_thinks_for_one_node(tmp_path))
    layer = dataclasses.replace(
        layer, node_calls=CallDesks(port=w3_numbered(port), plan=layer.node_calls.plan)
    )
    context = build_context(brain, W3_TASK, layer, workspace_path=str(workspace))
    state = new_state(W3_TASK, GOAL, context)
    state.tick += 1
    run_tick(context, state)
    thinks = sorted(
        (e for e in call_entries_of(context, 1) if str(e.node) == HOMEOSTASIS),
        key=lambda e: e.call_number,
    )
    first, second = (w3_decoded(entry, 1) for entry in thinks)
    received = w3_handed(bodies, HOMEOSTASIS, 1).think_answer
    show("homeostasis's thinks", [(e.call_number, str(e.tier)) for e in thinks], tag="G9")
    show("the body was handed", received.answer, tag="G9")
    assert [(e.call_number, e.tier) for e in thinks] == [(1, CallType.THINK), (2, CallType.THINK)]
    assert first != second, "the two answers differ"
    assert received == first and received.answer.startswith("call 1: ")


def test_G9_a_replay_that_restored_homeostasiss_think_hands_the_body_the_torn_passs_answer(
    tmp_path: Path, workspace: Path, monkeypatch
):
    """F11: `torn_tick.yaml` torn inside the seat call, after homeostasis's think was journalled."""
    bodies = w3_bodies(monkeypatch)
    brain = open_root(tmp_path)
    context, state, port, _seat = stubs.open_task(
        brain, workspace, "torn_tick.yaml", W3_TASK, goal=GOAL, crash_on=3
    )
    before = state.model_copy(deep=True)
    state.tick += 1
    with pytest.raises(stubs.TornTick):
        run_tick(context, state)
    torn_entry = call_entry(context, 1, HOMEOSTASIS)
    torn = w3_handed(bodies, HOMEOSTASIS, 1).think_answer

    bodies.clear()
    replay_layer, replay_port, _seat = stubs.scripted_layer(brain, "torn_tick.yaml")
    replay_context = build_context(brain, W3_TASK, replay_layer, workspace_path=str(workspace))
    replayed = before.model_copy(deep=True)
    replayed.tick += 1
    run_tick(replay_context, replayed, replay=True)
    restored = w3_handed(bodies, HOMEOSTASIS, 1).think_answer
    show("torn / replay addressees", (port.addressees, replay_port.addressees), tag="G9")
    show("torn / restored answer", (torn.answer, restored.answer), tag="G9")
    assert port.addressees == [str(CallType.THINK), str(CallType.DELEGATE), "manager"]
    assert torn_entry.is_restorable()
    assert str(CallType.THINK) not in replay_port.addressees, "restored, not re-made"
    assert restored == torn == w3_decoded(torn_entry, 1)


def test_G9_a_replay_that_restored_the_monitors_think_hands_the_body_the_torn_passs_answer(
    tmp_path: Path, workspace: Path, monkeypatch
):
    """F11 at the monitor, torn in its body after its think was journalled (E37's injection)."""
    brain = open_root(tmp_path, **w3_on(MONITOR))
    script = unplanned(tmp_path, "dispatch_wave")
    context, state, _port, _seat = stubs.open_task(brain, workspace, script, W3_TASK, goal=GOAL)
    state.tick += 1
    run_tick(context, state)
    before = state.model_copy(deep=True)
    handed: list[Any] = []

    def torn_body(payload):
        handed.append(payload)
        raise stubs.TornTick("killed in the monitor's body, after its think was journalled")

    state.tick += 1
    with monkeypatch.context() as patch:
        patch.setattr(cycle_module, "NODES", {**cycle_module.NODES, MONITOR: torn_body})
        with pytest.raises(stubs.TornTick):
            run_tick(context, state)
    torn_entry = call_entry(context, 2, MONITOR)
    (torn_input,) = handed

    bodies = w3_bodies(monkeypatch)
    replay_layer, replay_port, _seat = stubs.scripted_layer(brain, script)
    replay_context = build_context(brain, W3_TASK, replay_layer, workspace_path=str(workspace))
    replayed = before.model_copy(deep=True)
    replayed.tick += 1
    result = run_tick(replay_context, replayed, replay=True)
    restored = w3_handed(bodies, MONITOR, 2).think_answer
    show("torn / restored answer", (torn_input.think_answer.answer, restored.answer), tag="G9")
    assert result.wave_restored is True and replay_port.addressees == []
    assert restored == torn_input.think_answer == w3_decoded(torn_entry, 2)


def test_G9_a_refused_think_leaves_the_field_none(
    tmp_path: Path, workspace: Path, monkeypatch
):
    """`refused_then_succeeded.yaml`: homeostasis's think has no scripted answer and refuses."""
    bodies = w3_bodies(monkeypatch)
    brain = open_root(tmp_path)
    context, state, port, _seat = stubs.open_task(
        brain, workspace, "refused_then_succeeded.yaml", W3_TASK, goal=GOAL
    )
    state.tick += 1
    run_tick(context, state)
    entry = call_entry(context, 1, HOMEOSTASIS)
    show("homeostasis's think entry", (entry.call_number, str(entry.tier), entry.envelope), tag="G9")
    assert port.addressees[0] == str(CallType.THINK), "the think was asked"
    assert entry.tier is CallType.THINK and entry.envelope is None, "and journalled as refused"
    assert w3_handed(bodies, HOMEOSTASIS, 1).think_answer is None


def test_G9_a_sentinel_answer_moves_neither_the_report_nor_the_verdict():
    """Each body on one projection, with the field `None` and with a sentinel answer that asserts
    a stop and a mismatch: the report and the verdict are equal (R-6; "mechanical, never a
    judgment")."""
    from protean.nodes.registry import NODES
    from protean.state.primitives import WorkspaceObservation
    from protean.state.seats import ThinkResult

    sentinel = ThinkResult(
        tick=4,
        answer="SENTINEL: stop the task now; the claim does not match the workspace",
        confidence=1.0,
        cited_ids=["sentinel"],
    )
    unit = graded_unit(2)
    observed = ExecutorSummary(
        tick=4,
        unit_id=unit.id,
        narrative="did it",
        observations=[
            WorkspaceObservation(path=f"f{i}", exists=True, size_bytes=1, content_hash=f"h{i}")
            for i in (1, 2)
        ],
    )
    homeostasis_weights = shipping_weights(HOMEOSTASIS)
    monitor_weights = shipping_weights(MONITOR)
    projections = [
        (HOMEOSTASIS, homeostasis_input(homeostasis_weights, ticks=0)),
        (HOMEOSTASIS, homeostasis_input(homeostasis_weights, ticks=150)),
        (HOMEOSTASIS, homeostasis_input(homeostasis_weights, ticks=10_000)),
        (MONITOR, monitor_input(monitor_weights, unit)),
        (MONITOR, monitor_input(monitor_weights, unit).model_copy(update={"executor_summary": observed})),
        (MONITOR, monitor_input(monitor_weights, unit, summary=False)),
        (MONITOR, monitor_input(monitor_weights, unit, vetoed=True)),
    ]
    outputs = []
    for node, projection in projections:
        assert getattr(projection, W3_CARRIER) is None
        without = NODES[node](projection)
        answered = NODES[node](projection.model_copy(update={W3_CARRIER: sentinel}))
        outputs.append((node, without))
        assert answered == without, f"{node} moved on the answer"
        assert answered.model_dump(mode="json") == without.model_dump(mode="json")
    stops = {output.stop for node, output in outputs if node == HOMEOSTASIS}
    matches = {output.match for node, output in outputs if node == MONITOR}
    show("homeostasis stop over the projections", sorted(stops), tag="G9")
    show("monitor match over the projections", sorted(matches), tag="G9")
    assert stops == {False, True} and matches == {False, True}, "both outcomes were exercised"


@pytest.mark.parametrize("node", AUTHORED)
def test_G9_the_nodes_prediction_input_signature_digests_the_filled_input(
    tmp_path: Path, workspace: Path, monkeypatch, node
):
    from protean.brain.jsonl import read_lines

    bodies = w3_bodies(monkeypatch)
    brain = open_root(tmp_path, **w3_on(node))
    context, _state, _port, _results = drive(
        brain, workspace, unplanned(tmp_path, "dispatch_wave"), task=W3_TASK
    )
    filled = w3_handed(bodies, node, 2)
    (record,) = [
        row
        for row in read_lines(context.paths.trace(node))
        if row["task"] == W3_TASK and row["tick"] == 2
        and row["kind"] == "prediction" and row["source"] == "node"
    ]
    recorded = record["input_signature"]
    unfilled = filled.model_copy(update={W3_CARRIER: None})
    show(f"{node} tick-2 signature", recorded, tag="G9")
    assert filled.think_answer is not None
    assert recorded["model"] == W3_MODELS[node].__name__
    assert recorded["digest"] == input_signature(node, filled).digest, "the filled input"
    assert recorded["digest"] != input_signature(node, unfilled).digest, "the field is in it"


def test_G9_an_interrupting_think_on_a_key_on_root_writes_one_item_and_pauses_the_run(
    tmp_path: Path, workspace: Path
):
    """F26 (E25): a raise is a pause, not a note. Homeostasis's key on, its think answered with an
    `interrupt`: one mailbox item under the call-bearing raiser's id, the tick commits
    `interrupted`, and the stand-in is not invoked again until the item is answered and resumed."""
    from protean.mailbox.files import build as build_mailbox
    from protean.state.enums import Raiser, TerminalState
    from protean.state.interrupts import ANSWER_HEADING, interrupt_id

    brain = open_root(tmp_path, **w3_on(HOMEOSTASIS))
    layer, port, _seat = stubs.scripted_layer(brain, w3_raising_script(tmp_path))
    mailbox = build_mailbox(brain)
    outcome = engine.start(
        brain,
        GOAL,
        layer,
        mailbox=mailbox,
        workspace_path=str(workspace),
        task_id=W3_TASK,
        max_ticks=5,
    )
    open_dir = BrainPaths(root=brain).mailbox_open
    items = sorted(path.stem for path in open_dir.glob("*.md"))
    expected = interrupt_id(W3_TASK, 2, str(Raiser.THINK), node=HOMEOSTASIS, call_number=1)
    invoked = list(port.addressees)
    show("committed per tick", [str(tick.committed_terminal) for tick in outcome.ticks], tag="G9")
    show("mailbox/open", items, tag="G9")
    assert [tick.committed_terminal for tick in outcome.ticks] == [None, TerminalState.INTERRUPTED]
    assert outcome.terminal is TerminalState.INTERRUPTED, "paused at tick 2 of five allowed"
    assert items == [expected], "one item, under the calling node's widened id"
    assert mailbox.read(expected).raised_by is Raiser.THINK
    assert invoked.count(str(CallType.THINK)) == 1

    unanswered = engine.resume(brain, layer, mailbox=mailbox, max_ticks=1)
    show("resume with the item open", unanswered.refusal, tag="G9")
    assert unanswered.refusal == "unanswered_interrupt"
    assert port.addressees == invoked, "the stand-in is not invoked while the item is open"

    item = open_dir / f"{expected}.md"
    item.write_text(
        item.read_text(encoding="utf-8").replace(
            ANSWER_HEADING, f"{ANSWER_HEADING}\n\nthe primary ledger"
        ),
        encoding="utf-8",
    )
    resumed = engine.resume(brain, layer, mailbox=mailbox, max_ticks=1)
    show("resumed", (str(resumed.terminal), port.addressees[len(invoked):]), tag="G9")
    assert len(port.addressees) > len(invoked), "resume invokes the stand-in again"


# --------------------------------------------------------------------------------------
# G6 (part) — a planned call's context is the projection with the carrier unset
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("node", AUTHORED)
def test_G6_the_handed_context_is_the_projection_with_the_carrier_unset(
    tmp_path: Path, workspace: Path, spy, monkeypatch, node
):
    """On a key-on tick whose think fills the carrier, the handed payload's `context` parses to
    the projection with the carrier present at `null`, and the firing check and the call check
    both read it unset; only the body is handed it filled."""
    decided: list[tuple[str, Any]] = []
    real_decide = firing.decide

    def _decide(name, payload):
        decided.append((str(NodeName(name)), payload.tick, getattr(payload, W3_CARRIER, None)))
        return real_decide(name, payload)

    monkeypatch.setattr(firing, "decide", _decide)
    bodies = w3_bodies(monkeypatch)
    brain = open_root(tmp_path, **w3_on(node))
    context, _state, _port, _results = drive(
        brain, workspace, unplanned(tmp_path, "dispatch_wave"), task=W3_TASK
    )
    seen = of(spy, node)[-1]
    (planned,) = seen.planned
    entry = call_entry(context, 2, node)
    text = entry.payload["context"]
    handed = json.loads(text)
    show(f"{node} context length / bound", (len(text), triggers.CONTEXT_BOUND), tag="G6")
    show(f"{node} context[{W3_CARRIER!r}]", handed.get(W3_CARRIER, "<absent>"), tag="G6")
    assert len(text) < triggers.CONTEXT_BOUND, "uncut, so it parses whole"
    assert text == planned.payload["context"], "the journalled payload is the handed one"
    assert W3_CARRIER in handed and handed[W3_CARRIER] is None
    assert handed == seen.payload.model_dump(mode="json"), "the projection, as the policy saw it"
    assert [carrier for name, tick, carrier in decided if name == node and tick == 2] == [None]
    assert w3_handed(bodies, node, 2).think_answer is not None, "only the body gets it filled"


# --------------------------------------------------------------------------------------
# G14 — the unrun trigger probe: never collected, one call addressed `think`, one delegate
# --------------------------------------------------------------------------------------
#
# Order W6's collected clauses (§ Deliverable 7, row B69), on `tests/cortex/test_library.py`'s
# row-G7 shape: these cases read the probe's name and parse its source, and neither import nor
# run it. Every other G14 clause closes on captured command output alone.

#: A.2.i's one live receipt, landed and never run (row B69, behind B42).
W6_PROBE = REPO_ROOT / "tests" / "wet" / "probe_triggers.py"
#: What binds a name to one tick's node-call desk: the runtime's accessor, or the layer's seam.
W6_OPENERS = ("tick_calls_of", "node_calls")
#: Every desk method that issues a call — the two arms the probe uses and the four it must not.
W6_ISSUERS = ("think", "escalate", "delegate", "run", "issue", "call")
W6_ARMS = (str(CallType.THINK), str(CallType.DELEGATE))
#: The probe's two calls and its desk's binding as they are written — the anchors each control
#: below rewrites.
W6_THINK_CALL = "= desk.think("
W6_DELEGATE_CALL = "= desk.delegate("
W6_DESK_BINDING = "desk = tick_calls_of(layer, TASK_ID, tick)"


def w6_calls_named(tree, name: str) -> list:
    """Every `Call` in `tree` whose function is `name` itself or an attribute named `name`."""
    import ast

    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == name)
            or (isinstance(node.func, ast.Name) and node.func.id == name)
        )
    ]


def w6_desk_names(tree) -> set[str]:
    """Every name assigned from a call that opens a tick's node-call desk."""
    import ast

    return {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
        for opener in [node.value.func]
        if (isinstance(opener, ast.Name) and opener.id in W6_OPENERS)
        or (isinstance(opener, ast.Attribute) and opener.attr in W6_OPENERS)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def w6_findings(source: str) -> list[str]:
    """G14's static clause: every way `source` fails it, or nothing.

    Parsed with `ast`, never imported or run. Exactly one `Call` is addressed `think` and exactly
    one goes through the `delegate` arm; each is made on a name bound to a tick's node-call desk;
    and that desk issues nothing else — no `run`, `issue`, `call` or `escalate` beside the two.
    """
    import ast

    tree = ast.parse(source)
    desks = w6_desk_names(tree)
    if not desks:
        return ["no name is bound to a tick's node-call desk"]
    findings: list[str] = []
    for arm in W6_ARMS:
        calls = w6_calls_named(tree, arm)
        if len(calls) != 1:
            findings.append(f"{len(calls)} `{arm}` calls, not exactly one")
            continue
        receiver = getattr(calls[0].func, "value", None)
        if not (isinstance(receiver, ast.Name) and receiver.id in desks):
            findings.append(f"the `{arm}` call is not made on the desk")
    issued = sorted(
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in desks
        and node.func.attr in W6_ISSUERS
    )
    if issued != sorted(W6_ARMS):
        findings.append(f"the desk issues {issued}, not exactly one think and one delegate")
    return findings


def w6_rewrite(anchor: str, replacement: str):
    """A control: the probe's source with its one `anchor` rewritten to `replacement`."""

    def rewritten(source: str) -> str:
        assert source.count(anchor) == 1, "the control rewrites the probe's one anchor"
        return source.replace(anchor, replacement)

    return rewritten


def w6_appended(line: str):
    """A control: the probe's source with one more statement appended."""

    def appended(source: str) -> str:
        return source + f"\n\n{line}\n"

    return appended


def test_G14_the_probe_exists_and_its_name_matches_no_python_files_pattern(pytestconfig):
    """G14's collection clause, read off pytest's own effective `python_files` rather than assumed:
    the probe's name matches none of them, so no collection imports it — while this module's name
    matches one, so a pattern list that matched nothing would not pass."""
    patterns = pytestconfig.getini("python_files")
    show("python_files · the probe", f"{patterns} · {W6_PROBE.name}", tag="G14")
    assert W6_PROBE.is_file(), "the probe is landed"
    assert not any(Path(W6_PROBE.name).match(pattern) for pattern in patterns)
    assert any(Path(Path(__file__).name).match(pattern) for pattern in patterns), "the control"


def test_G14_parsed_never_run_the_probe_makes_one_think_and_one_delegate_on_the_desk():
    """G14's static clause: the probe's source, parsed and never imported, addresses exactly one
    call `think` and sends exactly one through the delegate arm, both on the tick's desk."""
    findings = w6_findings(W6_PROBE.read_text(encoding="utf-8"))
    show("findings over the probe", findings, tag="G14")
    assert findings == []


@pytest.mark.parametrize(
    ("mutate", "passes"),
    [
        pytest.param(
            w6_rewrite(W6_DESK_BINDING, "desk = layer.node_calls(TASK_ID, tick)"),
            True,
            id="desk_opened_off_the_layers_seam",
        ),
        pytest.param(
            w6_appended("desk.think(NODE, question=question)"), False, id="a_second_think"
        ),
        pytest.param(
            w6_rewrite(W6_THINK_CALL, "= desk.run("), False, id="the_think_through_run"
        ),
        pytest.param(
            w6_rewrite(W6_DELEGATE_CALL, "= print("), False, id="no_delegate_at_all"
        ),
        pytest.param(
            w6_rewrite(W6_DELEGATE_CALL, "= spawn_desk.delegate("),
            False,
            id="the_delegate_past_the_desk",
        ),
        pytest.param(
            w6_rewrite(W6_THINK_CALL, "= layer.port.think("), False, id="the_think_past_the_desk"
        ),
        pytest.param(
            w6_appended("desk.issue(NODE, think)"), False, id="a_further_call_on_the_desk"
        ),
        pytest.param(
            w6_rewrite(W6_DESK_BINDING, "desk = object()"), False, id="no_desk_bound"
        ),
    ],
)
def test_G14_the_static_check_tells_the_probe_from_every_other_shape(mutate, passes):
    """The control, on the probe's own source: the seam-opened desk passes, and each shape that
    breaks a clause — a second think, the think through `run`, no delegate, a delegate or a think
    past the desk, a further call on the desk, no desk at all — is found, so an empty finding list
    over the probe is not a vacuous one."""
    findings = w6_findings(mutate(W6_PROBE.read_text(encoding="utf-8")))
    show("findings over the rewritten probe", findings, tag="G14")
    assert (findings == []) is passes, findings


# --------------------------------------------------------------------------------------
# G11 — the edge rule is a rule, a sentence and a check, and no edge exists
# --------------------------------------------------------------------------------------
#
# Order W7's cases (§ Deliverable 4, rows G11 and B70), on `tests/nodes/test_firing_checks.py`'s
# M4 `## Reads` shape: each outer node's input-model field set against a literal. A new field
# projecting another outer node's output fails here until it is declared — edited in the literal
# under a Resolution of the SPEC that adds it. No loader refuses an edge; this row is the check.

#: The ring's hand-offs (§ Deliverable 4, rule 2): the landed cross-node fields, frozen — "the
#: ring" means this list, not "adjacent only". The last is the monitor's read of the gate's veto
#: across the cortex step (A1-17), a hand-off since build 1.
W7_RING_HAND_OFFS = (
    "ThalamusInput.retrieval",
    "BasalGangliaInput.admitted",
    "MonitorInput.executor_summary",
    "MonitorInput.wave_status",
    "MonitorInput.vetoed_unit_id",
)
#: Each outer node's input-model field set, as a literal. `hand_offs` are its cross-node fields;
#: `own` is every other field — committed state, the node's own weights and, on the two authored
#: nodes, W3's `think_answer` carrier, which is the node's own think and not another node's output.
W7_FIELDS: dict[str, dict[str, frozenset[str]]] = {
    HOMEOSTASIS: {
        "hand_offs": frozenset(),
        "own": frozenset(
            {"task_id", "tick", "weights", "cost", "ceiling_overrides", "constraints", "think_answer"}
        ),
    },
    str(NodeName.HIPPOCAMPUS): {
        "hand_offs": frozenset(),
        "own": frozenset({"task_id", "tick", "weights", "goals", "units", "candidates", "semantic"}),
    },
    str(NodeName.THALAMUS): {
        "hand_offs": frozenset({"retrieval"}),
        "own": frozenset({"task_id", "tick", "weights", "goals", "units"}),
    },
    str(NodeName.BASAL_GANGLIA): {
        "hand_offs": frozenset({"admitted"}),
        "own": frozenset(
            {"task_id", "tick", "weights", "pending_unit", "constraints", "workspace_root"}
        ),
    },
    MONITOR: {
        "hand_offs": frozenset({"executor_summary", "wave_status", "vetoed_unit_id"}),
        "own": frozenset(
            {
                "task_id",
                "tick",
                "weights",
                "goals",
                "units",
                "unit_windows",
                "trap_dismissals",
                "think_answer",
            }
        ),
    },
}
#: § Deliverable 4's one sentence in the seed that describes the ring for the whole graph.
W7_EDGE_SENTENCE = (
    "An off-ring edge is a declared, justified, forward-only input field that projects another "
    "outer node's current-tick output beyond the ring's hand-offs, and none exists."
)
W7_CORTEX_NODE_MD = config.node_dir(config.CORTEX_NODE, BRAIN_SEED) / "NODE.md"


def w7_model(node: str):
    """The outer node's one input model, as the `## Reads` check maps it."""
    (model,) = NODE_INPUT_MODELS[NodeName(node)]
    return model


def w7_edge_findings(model, node: str) -> list[str]:
    """G11's comparison: every way `model`'s field set departs from `node`'s literal, or nothing."""
    declared = W7_FIELDS[node]["hand_offs"] | W7_FIELDS[node]["own"]
    fields = set(model.model_fields)
    return [
        *(
            f"`{model.__name__}.{name}` is in no literal — an undeclared edge"
            for name in sorted(fields - declared)
        ),
        *(
            f"`{model.__name__}.{name}` is in the literal but not on the model"
            for name in sorted(declared - fields)
        ),
    ]


def test_G11_the_literal_covers_exactly_the_five_outer_nodes():
    """Every outer node's input model is compared, so a node cannot sit outside the row."""
    show("literal nodes", sorted(W7_FIELDS), tag="G11")
    assert set(W7_FIELDS) == set(config.DETERMINISTIC_NODES)


@pytest.mark.parametrize("node", list(config.DETERMINISTIC_NODES))
def test_G11_each_outer_nodes_input_model_field_set_equals_its_literal(node):
    """No input model carries a field the literal does not declare, and none has lost one."""
    model = w7_model(node)
    findings = w7_edge_findings(model, node)
    show(f"{model.__name__} findings", findings, tag="G11")
    assert findings == []


def test_G11_the_literals_cross_node_entries_are_exactly_the_rings_hand_offs():
    """The literal's cross-node entries are the frozen hand-off list, the gate's veto included."""
    cross_node = {
        f"{w7_model(node).__name__}.{name}"
        for node, literal in W7_FIELDS.items()
        for name in literal["hand_offs"]
    }
    show("cross-node entries", sorted(cross_node), tag="G11")
    assert cross_node == set(W7_RING_HAND_OFFS)
    assert "MonitorInput.vetoed_unit_id" in cross_node, "the veto read is a hand-off (A1-17)"


def test_G11_the_literal_carries_w3s_carriers_and_they_are_not_cross_node():
    """W3's two `think_answer` fields are in the literal, as each authored node's own field."""
    carried = {node for node, literal in W7_FIELDS.items() if W3_CARRIER in literal["own"]}
    crossing = {node for node, literal in W7_FIELDS.items() if W3_CARRIER in literal["hand_offs"]}
    show("carrier in own · in hand_offs", f"{sorted(carried)} · {sorted(crossing)}", tag="G11")
    assert carried == set(AUTHORED)
    assert crossing == set()


@pytest.mark.parametrize("node", list(config.DETERMINISTIC_NODES))
def test_G11_a_mutated_model_gaining_a_field_fails_the_comparison(node):
    """The control: the same model plus one field — say another outer node's output — is found."""
    from pydantic import create_model

    model = w7_model(node)
    mutated = create_model(
        f"Mutated{model.__name__}", __base__=model, off_ring_edge=(dict | None, None)
    )
    findings = w7_edge_findings(mutated, node)
    show(f"{mutated.__name__} findings", findings, tag="G11")
    assert findings == [
        f"`{mutated.__name__}.off_ring_edge` is in no literal — an undeclared edge"
    ]


def test_G11_the_cortex_node_md_carries_the_edge_rules_sentence():
    """§ Deliverable 4's sentence, as a literal body string over the seed's prose (soft line breaks
    collapsed, `tests/cortex/test_library.py`'s `_prose()` reading); it names and declares no edge."""
    prose = " ".join(W7_CORTEX_NODE_MD.read_text(encoding="utf-8").split())
    show("edge sentence in cortex NODE.md", W7_EDGE_SENTENCE in prose, tag="G11")
    assert W7_EDGE_SENTENCE in prose
    assert "A.2.i's" not in prose, "the file routes no trigger to A.2.i (R16)"
