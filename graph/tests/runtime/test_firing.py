"""G2 — conditional firing works and never skips an inhibition.

`the build specification (not in this mirror)` § Deliverable 1 (the cheap check, the gate's stated
exemption, who may skip and who may not, the one stamp-test mechanism, the skip as a recorded
prediction), § Directional decisions 3, 14 and 15, § Rulings 4, § Resolutions A1-5 and A1-9.

**The row's clauses, one test apiece.** A declining hippocampus runs no body, issues none of the
calls planned for it and writes its `FiringDecision` at `call# = 0`; its `LatestOutputs` slot
still holds last tick's output under last tick's stamp, **byte for byte**, while
`projections.thalamus_input()` hands the consumer `None` in its place; the same again for
`basal_ganglia_input()`/`admitted`; the gate and the monitor each run on their defined empty
input; a tick with a pending unit always records a gate verdict and a tick with none is build 3's
`NO_SUBJECT` case; homeostasis's think call skips while its full `HomeostasisReport` and its stop
do not; and a crossed ceiling suppresses every further model call while the remaining nodes run.

**Thresholds are written into the throwaway root, never into a fixture.** `firing_threshold` is a
`weights.yaml` key like `max_tokens`, so the battery raises it in the temp brain root it runs
against and the fixtures under `fixtures/calls/` name no number. The context is rebuilt after each
write because the boundary loader reads a node's weights when the task's folders are opened.

**Zero model calls.** Every answer is `fixtures/calls/*.yaml` through the scripted transport, and
no fixture here creates a tier-three process at all (row G12). The receipt is the recording shim's
log at zero bytes across the module, captured from the command line.

**What this module does not assert.** The firing prediction's trace record, its `:firing` key and
its grade are order W7's; the wave a `no_go` inhibits is order W8's. This module stops at the
`FiringDecision` and the journal entry that carries it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protean import config
from protean.nodes import anterior_cingulate as monitor_node
from protean.nodes import basal_ganglia as gate_node
from protean.nodes import hippocampus as hippocampus_node
from protean.nodes import homeostasis as homeostasis_node
from protean.nodes import thalamus as thalamus_node
from protean.runtime import firing, projections
from protean.runtime.cycle import run_tick
from protean.runtime.predictions import NO_SUBJECT
from protean.sleep.evidence import _vacuity
from protean.state.enums import NodeName, SelectionDecision, TerminalState, TraceKind, TraceSource
from protean.state.records import OUTPUT_CALL_NUMBER, BasalGangliaPrediction, TraceRecord
from protean.state.seat_calls import spend_tokens
from tests.conftest import tagged_show
from tests.runtime import stubs
from tests.runtime.conftest import (
    DECLINE,
    REPO_ROOT,
    call_entries_of,
    entries_of,
    reopen,
)

GOAL = "write the note the goal names"

#: `fixtures/calls/firing_ceiling.yaml`'s declared counters, as spend: a think is 7 + 1 + 1 and an
#: escalate is 9 + 1 + 1, with `cache_read_input_tokens` left out of both. Hand-computed here and
#: asserted against the fixture's own envelopes below, so the mirror cannot drift.
THINK_SPEND = 9
ESCALATE_SPEND = 11
#: The three calls a pass makes once homeostasis's own think call is declined.
THREE_CALL_SPEND = 2 * THINK_SPEND + ESCALATE_SPEND


show = tagged_show("W6-firing")


def output_entry(context, tick: int, node: NodeName):
    """One node's **own** entry for a tick — the reserved `call# = 0`."""
    found = [
        entry
        for entry in entries_of(context, tick)
        if entry.node is node and entry.call_number == OUTPUT_CALL_NUMBER
    ]
    assert len(found) == 1, f"{node} writes exactly one output entry per tick: {found}"
    return found[0]


def committed_latest(context, tick: int) -> dict:
    """The `latest` slice of the checkpoint the boundary committed for this tick, off disk."""
    payload = stubs.committed_state(context.paths)
    assert payload["state"]["tick"] == tick, "the last checkpoint is this tick's"
    return payload["state"]["latest"]


# --------------------------------------------------------------------------------------
# A declining node: no body, no call, and a `FiringDecision` at `call# = 0`
# --------------------------------------------------------------------------------------


def _decline_two_passes(brain: Path, workspace: Path, patch, task: str):
    """Pass 1 with every check firing, then the hippocampus and the thalamus declined for pass 2.

    Two passes, because the clause under test is about **last** pass's output still sitting in a
    slot: a root whose first pass already declined would have nothing stale to withhold.
    """
    context, state, port, _seat = stubs.open_task(
        brain, workspace, "firing_decline.yaml", task, goal=GOAL
    )
    state.tick += 1
    run_tick(context, state)
    landed = state.latest.hippocampus.model_dump_json()
    show("slot after the firing pass", landed)

    stubs.set_weight(brain, "hippocampus", **{hippocampus_node.WEIGHT_FIRING: DECLINE})
    stubs.set_weight(brain, "thalamus", **{thalamus_node.WEIGHT_FIRING: DECLINE})
    context = reopen(brain, task, context, workspace)

    sink: list[str] = []
    stubs.recorded_nodes(patch, sink)
    calls_before = list(port.addressees)
    statuses_before = [unit.status for unit in state.units]
    state.tick += 1
    result = run_tick(context, state)
    return context, state, result, sink, landed, port, calls_before, statuses_before


@pytest.fixture(scope="module")
def declining(tmp_path_factory):
    """`_decline_two_passes()` once for the module — **read-only** to its consumers.

    Seven of the eight clauses below read the *same* declining pass: which bodies ran, the
    `FiringDecision` at `call# = 0`, the calls the declining node did not issue, the slot still
    holding last pass's output under last pass's stamp, the commit, and the two contractual
    inhibitions. None of them advances the tick or writes into the root. The one that does —
    `basal_ganglia_input()`'s withheld slot, which runs a third pass under its own monkeypatch —
    takes the function-scoped `declining_fresh` instead. `cycle.NODES` is patched only for the
    length of the two passes: the `pytest.MonkeyPatch()` context is left before any consumer runs.
    """
    base = tmp_path_factory.mktemp("declining")
    brain = stubs.seed_brain(REPO_ROOT / "brain", base / "brain")
    workspace = base / "workspace"
    workspace.mkdir()
    with pytest.MonkeyPatch().context() as patch:
        return _decline_two_passes(brain, workspace, patch, "task-firing")


@pytest.fixture()
def declining_fresh(brain: Path, workspace: Path, monkeypatch):
    """`_decline_two_passes()` on a root of this test's own — for a consumer that drives it on."""
    return _decline_two_passes(brain, workspace, monkeypatch, "task-firing")


def test_the_declining_pass_ran_no_hippocampus_body_and_still_ran_every_step(declining):
    """The node is still on the path; what it stopped doing is work."""
    context, _state, result, sink, _landed, _port, _before, _statuses = declining
    show("recorded bodies", sink)
    show("recorded step order", result.order)
    assert result.order == config.NODE_ORDER, "the ring does not move"
    assert str(NodeName.HIPPOCAMPUS) not in sink, "no hippocampus body ran"
    assert str(NodeName.THALAMUS) not in sink, "and no thalamus body either"
    assert str(NodeName.BASAL_GANGLIA) in sink, "while the gate, which fired, did run"
    assert result.journal_entries >= len(config.NODE_ORDER), "one output entry per node, still"


def test_the_declining_node_writes_its_firing_decision_at_call_zero(declining):
    """§ Deliverable 1: a skip is a recorded prediction, not an absence."""
    context, _state, _result, _sink, _landed, _port, _before, _statuses = declining
    raw = [
        line
        for line in context.paths.journal(2).read_text(encoding="utf-8").splitlines()
        if json.loads(line)["node"] == str(NodeName.HIPPOCAMPUS)
    ]
    show("journal-2.jsonl, the hippocampus's lines", raw)
    assert len(raw) == 1, "one entry, and it is the output one"
    entry = output_entry(context, 2, NodeName.HIPPOCAMPUS)
    decision = entry.output
    show("hippocampus call#0 output", decision)
    assert entry.call_number == OUTPUT_CALL_NUMBER
    assert decision.emitter == "firing"
    assert decision.node is NodeName.HIPPOCAMPUS
    assert decision.check == hippocampus_node.CHECK_PROJECTED_CANDIDATES
    assert decision.key == hippocampus_node.WEIGHT_FIRING
    assert decision.threshold == DECLINE
    assert decision.value < decision.threshold
    assert decision.fired is False


def test_a_declining_node_issues_none_of_the_calls_planned_for_it(declining):
    """The think call `firing_decline.yaml` puts on the hippocampus is simply not made."""
    context, state, _result, _sink, _landed, port, before, _statuses = declining
    show("port invocations before the declining pass", before)
    show("port invocations after it", port.addressees)
    assert port.addressees[len(before):] == ["manager"], (
        "the cortex's own seat call and nothing else: a skip that still spent on the think "
        "call planned for it would not be a skip"
    )
    made = call_entries_of(context, 2)
    show("this pass's call entries", [(str(entry.node), entry.call_number) for entry in made])
    assert [entry.node for entry in made] == [NodeName.CORTEX], "no call, so no call entry"


def test_the_slot_still_holds_last_passs_output_under_last_passs_stamp(declining):
    """No committed field is emptied and no stamp is rewritten — byte for byte."""
    context, state, _result, _sink, landed, _port, _before, _statuses = declining
    show("slot after the declining pass", state.latest.hippocampus.model_dump_json())
    assert state.latest.hippocampus.model_dump_json() == landed
    assert state.latest.hippocampus.tick == 1, "last pass's stamp, on this pass"
    committed = committed_latest(context, 2)
    assert json.dumps(committed["hippocampus"], sort_keys=True) == json.dumps(
        json.loads(landed), sort_keys=True
    ), "and the checkpoint the boundary committed says the same"


def test_the_declining_pass_still_commits(declining):
    """"and the tick still commits" — the boundary is untouched by a skip."""
    context, _state, result, _sink, _landed, _port, _before, _statuses = declining
    committed = stubs.committed_state(context.paths)
    show("committed terminal", result.committed_terminal)
    show(
        "checkpoint on disk",
        {
            "tick": committed["state"]["tick"],
            "terminal": committed["state"]["terminal"],
            "schema_version": committed["schema_version"],
        },
    )
    assert result.receipt is not None
    assert result.receipt.checkpoint_is_last(), "committed at the boundary and nowhere else"
    assert committed["state"]["tick"] == 2


# --------------------------------------------------------------------------------------
# The one stale-slot mechanism: the stamp test at the projection boundary
# --------------------------------------------------------------------------------------


def test_thalamus_input_hands_none_in_place_of_a_withheld_slot(
    brain: Path, workspace: Path, monkeypatch
):
    """The instrumented capture G2 names: `retrieval=None`, from the run itself."""
    context, state, _port, _seat = stubs.open_task(
        brain, workspace, "firing_decline.yaml", "task-stamp", goal=GOAL
    )
    state.tick += 1
    run_tick(context, state)
    stubs.set_weight(brain, "hippocampus", **{hippocampus_node.WEIGHT_FIRING: DECLINE})
    context = reopen(brain, "task-stamp", context, workspace)

    seen: list[object] = []
    real = projections.thalamus_input

    def recording(state_, weights, retrieval):
        payload = real(state_, weights, retrieval)
        seen.append((retrieval, payload.retrieval))
        return payload

    monkeypatch.setattr(projections, "thalamus_input", recording)
    state.tick += 1
    run_tick(context, state)

    slot, projected = seen[-1]
    show("the slot as it sits in `latest`", slot)
    show("what `thalamus_input()` handed the consumer", projected)
    assert slot is not None and slot.tick == 1, "last pass's output is still in the slot"
    assert projected is None, "and it does not reach the consumer wearing this pass's authority"


def test_basal_ganglia_input_hands_none_in_place_of_a_withheld_slot(
    declining_fresh, monkeypatch
):
    """The same shown for `basal_ganglia_input()`/`admitted` — one mechanism, two call sites."""
    context, state, _result, _sink, _landed, _port, _before, _statuses = declining_fresh
    seen: list[object] = []
    real = projections.basal_ganglia_input

    def recording(state_, weights, admitted, workspace_root):
        payload = real(state_, weights, admitted, workspace_root)
        seen.append((admitted, payload.admitted, payload.pending_unit))
        return payload

    monkeypatch.setattr(projections, "basal_ganglia_input", recording)
    state.tick += 1
    run_tick(context, state)

    slot, projected, unit = seen[-1]
    show("the thalamus slot as it sits in `latest`", None if slot is None else slot.tick)
    show("what `basal_ganglia_input()` handed the gate", projected)
    assert slot is not None and slot.tick < state.tick
    assert projected is None
    assert unit is not None, "the gate's defined empty input: a pending unit, no admitted context"


def test_the_stamp_test_is_one_function_at_two_call_sites(brain: Path, workspace: Path):
    """"exactly one mechanism" — asserted over the module, not promised in its docstring."""
    source = (REPO_ROOT / "src" / "protean" / "runtime" / "projections.py").read_text(
        encoding="utf-8"
    )
    show("_this_tick call sites", source.count("=_this_tick("))
    assert source.count("def _this_tick(") == 1
    assert source.count("=_this_tick(") == 2, "exactly two call sites, and no third mechanism"


# --------------------------------------------------------------------------------------
# The two contractual inhibitions
# --------------------------------------------------------------------------------------


def test_the_gate_runs_on_its_defined_empty_input_and_records_a_verdict(declining):
    """"the veto always runs when a unit is pending", whatever the thalamus did."""
    context, state, _result, sink, _landed, _port, _before, _statuses = declining
    entry = output_entry(context, 2, NodeName.BASAL_GANGLIA)
    show("gate call#0 output", entry.output)
    assert str(NodeName.BASAL_GANGLIA) in sink, "the gate's body ran"
    assert entry.output.emitter == "basal_ganglia"
    assert entry.output.decision is SelectionDecision.GO
    assert state.latest.basal_ganglia.tick == 2, "a verdict of this pass, not last pass's"


def test_the_monitor_runs_on_its_defined_empty_input(declining):
    """"no summary this tick, which is no grade and an unchanged unit".

    The last clause is a **before/after** comparison: the unit statuses are captured by the
    fixture *before* the declining pass and compared against the same list after it, because a
    list compared against itself after the fact cannot fail however far the statuses moved.
    """
    context, state, _result, sink, _landed, _port, _before, statuses_before = declining
    entry = output_entry(context, 2, NodeName.ANTERIOR_CINGULATE)
    show("monitor call#0 output", entry.output)
    assert str(NodeName.ANTERIOR_CINGULATE) in sink
    assert state.latest.dispatch is None, "nothing dispatched, so no summary this pass"
    assert entry.output.emitter == "anterior_cingulate"
    assert [unit.status for unit in state.units] == statuses_before, (
        "no summary, so no grade, so not one unit's status moved on the declining pass"
    )


def test_a_pass_with_no_pending_unit_skips_the_gate_and_is_build_threes_no_subject_case(
    brain: Path, workspace: Path
):
    """The gate's structural check, and why skipping there deletes nothing that was graded."""
    context, state, _port, _seat = stubs.open_task(
        brain, workspace, "firing_decline.yaml", "task-nosubject", goal=GOAL
    )
    state.tick += 1
    run_tick(context, state)

    entry = output_entry(context, 1, NodeName.BASAL_GANGLIA)
    show("gate call#0 output on the opening pass", entry.output)
    assert entry.output.emitter == "firing"
    assert entry.output.check == gate_node.CHECK_PENDING_UNIT
    assert entry.output.fired is False
    assert entry.output.key == "", "the gate's check reads no threshold key at all"
    assert entry.output.threshold is None

    #: And the pair it would have written is the one build 3's admissible set already drops.
    would_have = TraceRecord(
        schema_version=config.TRACE_SCHEMA_VERSION,
        task=state.task_id,
        tick=1,
        node=NodeName.BASAL_GANGLIA,
        kind=TraceKind.PREDICTION,
        source=TraceSource.NODE,
        prediction=BasalGangliaPrediction(unit_id=NO_SUBJECT),
    )
    show("build 3's verdict on the prediction the skip did not write", _vacuity(would_have))
    assert _vacuity(would_have) == config.EXCLUSION_VACUOUS


def test_a_pass_with_a_pending_unit_always_records_a_gate_verdict(brain: Path, workspace: Path):
    """The other half of the same clause, on the pass the manager's unit is pending for."""
    context, state, _port, _seat = stubs.open_task(
        brain, workspace, "firing_decline.yaml", "task-verdict", goal=GOAL
    )
    state.tick += 1
    run_tick(context, state)
    state.tick += 1
    run_tick(context, state)

    entry = output_entry(context, 2, NodeName.BASAL_GANGLIA)
    show("gate call#0 output with a unit pending", entry.output)
    assert entry.output.emitter == "basal_ganglia"
    assert entry.output.unit_id == "u-firing-1"


# --------------------------------------------------------------------------------------
# Homeostasis: the full report is never skippable and only its think call is
# --------------------------------------------------------------------------------------


@pytest.fixture()
def ceiling(brain: Path, workspace: Path):
    """Homeostasis declined from the start, then a ceiling the next pass's calls cross.

    The threshold is raised before any pass, so homeostasis's think call is skipped on every one
    of them; the ceiling is written between passes and the context rebuilt, exactly as
    `tests/runtime/test_call_cost.py` does it, so the crossing belongs to the pass's own calls.
    """
    stubs.set_weight(brain, "homeostasis", **{homeostasis_node.WEIGHT_FIRING: DECLINE})
    context, state, port, _seat = stubs.open_task(
        brain, workspace, "firing_ceiling.yaml", "task-ceiling", goal=GOAL
    )
    state.tick += 1
    run_tick(context, state)
    opening = state.cost.tokens

    stubs.set_weight(brain, "homeostasis", max_tokens=opening + THREE_CALL_SPEND - 1)
    context = reopen(brain, "task-ceiling", context, workspace)
    return context, state, port, opening


def test_the_fixtures_declared_spend_is_what_the_envelopes_carry(ceiling):
    """The mirrored constants above, against the fixture's own envelopes."""
    context, state, _port, _opening = ceiling
    state.tick += 1
    run_tick(context, state)
    spends = [spend_tokens(entry.envelope.usage) for entry in call_entries_of(context, 2)]
    show("this pass's per-call spend", spends)
    assert spends == [THINK_SPEND, THINK_SPEND, ESCALATE_SPEND]


def test_only_homeostasis_think_call_skips_and_its_full_report_does_not(ceiling):
    """§ Deliverable 1's homeostasis bullet, and G2's clause about it."""
    context, state, port, _opening = ceiling
    state.tick += 1
    result = run_tick(context, state)

    entry = output_entry(context, 2, NodeName.HOMEOSTASIS)
    show("homeostasis call#0 output", entry.output)
    show("latest.homeostasis, the full report", state.latest.homeostasis)
    show("this pass's addressees", port.addressees[-3:])
    assert entry.output.emitter == "homeostasis", "the body ran: the report is not a decision"
    assert entry.output.ceilings, "and it is the **full** report, ceilings and all"
    assert result.firing[0].node is NodeName.HOMEOSTASIS
    assert result.firing[0].fired is False, "while its own check declined"
    assert port.addressees[-3:] == ["think", "think", "escalate"], (
        "the hippocampus's and the thalamus's thinks and the monitor's escalate were made; "
        "the one on homeostasis was not"
    )
    assert len(call_entries_of(context, 2)) == 3, "three of the four planned calls"
    assert result.committed_terminal is TerminalState.STOPPED, "the crossing still stops the task"
    assert state.latest.homeostasis.tick == 2, "and `latest` carries this pass's full report"


def test_a_crossed_ceiling_suppresses_every_further_call_and_the_nodes_still_run(ceiling):
    """G2's last clause, asserted from the firing side rather than built a second time."""
    context, state, port, _opening = ceiling
    state.tick += 1
    run_tick(context, state)
    made_before = list(port.addressees)

    state.tick += 1
    result = run_tick(context, state)
    show("addressees after the crossing", port.addressees[len(made_before):])
    show("recorded step order", result.order)
    assert state.latest.homeostasis.stop is True, "this pass opened over the ceiling"
    assert port.addressees == made_before, "no further model call was issued"
    assert call_entries_of(context, 3) == []
    assert result.order == config.NODE_ORDER, "and every node still ran"
    assert result.tokens == 0
    assert result.committed_terminal is TerminalState.STOPPED
    assert [decision.node for decision in result.firing] == [
        NodeName(name) for name in config.DETERMINISTIC_NODES
    ], "every outer node's check still ran, in the ring's order"


# --------------------------------------------------------------------------------------
# The decisions the runtime keeps
# --------------------------------------------------------------------------------------


def test_every_outer_node_answers_its_check_every_pass(brain: Path, workspace: Path):
    """Five checks, five answers, in `NODE_ORDER` — the cortex is not a firing node."""
    context, state, _port, _seat = stubs.open_task(
        brain, workspace, "firing_decline.yaml", "task-answers", goal=GOAL
    )
    state.tick += 1
    result = run_tick(context, state)
    show("decisions", [(str(d.node), d.check, d.fired) for d in result.firing])
    assert [str(decision.node) for decision in result.firing] == list(
        config.DETERMINISTIC_NODES
    )
    assert str(NodeName.CORTEX) not in {str(decision.node) for decision in result.firing}
    assert set(firing.FIRING_KEYS) == set(config.DETERMINISTIC_NODES) - {
        str(NodeName.BASAL_GANGLIA)
    }, "four firing keys, and the gate is the stated exemption"
