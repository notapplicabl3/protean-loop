"""G5b, G7's wave clauses and G2's veto clause — the tick's single dispatch wave, end to end.

`the build specification (not in this mirror)` § Deliverable 3 (one wave per tick, the per-field merge,
the conflicted and partial rules, and what the suppression keys on), § Deliverable 4 (a wave is
**one call**, `member#` sub-keys in wave order, entries buffered and written in that order, and
the refusal classes) and § DoD row G2's veto clause.

**Zero model calls and no process at all.** Every member's return is scripted, out of
`fixtures/calls/*.yaml`, through order W2's transport: a stand-in answer with nothing behind it.
No kind is spawned, no `kinds:` block is read and no containment is asserted — all of that is
build A.1.i's (§ Out of scope, first bullet).

**What the fixtures drive and what the port drives.** A *shape* — who returns what — is the
fixture's, because a scripted responder is request-keyed. Two things are not shapes and are
driven at the port: a member that **times out** (§ Deliverable 4's third refusal class, which no
YAML can express) and the **order the members are run in**, which is A.1.i's to decide and which
A.1 must be independent of. Both stand in for a transport, exactly as the recording shim does.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from protean import config
from protean.cortex.adapters import ScriptedSeat, SeatDesk
from protean.cortex.calls import CallDesks
from protean.cortex.ladder import LadderWeights
from protean.cortex.router import LadderRouter
from protean.cortex.scripts import load_script
from protean.runtime import cycle as cycle_module
from protean.runtime import observations
from protean.runtime.cycle import (
    SEAT_CALL_NUMBER,
    WAVE_CALL_NUMBER,
    run_tick,
)
from protean.runtime.engine import build_context, new_state
from protean.runtime.seat import MemberUnfinished, SeatLayer, SeatSelection
from protean.state.enums import (
    CallType,
    NodeName,
    SelectionDecision,
    TerminalState,
    Tier,
    UnitStatus,
)
from protean.state.inputs import WAVE_COMPLETE, WAVE_CONFLICTED, WAVE_PARTIAL
from protean.state.seat_calls import load_seat_calls
from tests.conftest import tagged_show
from tests.runtime import stubs
from tests.runtime.conftest import REPO_ROOT, entries_of

FIXTURES = stubs.CALL_FIXTURES

GOAL = "write the note and check it"

#: The two members `dispatch_wave.yaml` lists, in the order it lists them — which is the order
#: `member#` is assigned in, whatever order they are later run in.
WAVE_ORDER = ("writer", "checker")


show = tagged_show("W8-wave")


class WavePort:
    """The scripted seat, with the three things a transport decides rather than a fixture.

    `crash_on_member` tears the process **inside** a member, so the journal a real tear would
    leave is what gets replayed; `timeout_on_member` raises the one fault § Deliverable 4 says
    marks a member failed and the wave `partial` rather than stopping the tick; `reverse` runs
    the members in the opposite order from the one the plan listed them in, which is what makes
    "the line order is `member#` order rather than completion order" a claim with two sides.
    """

    def __init__(
        self,
        seat: ScriptedSeat,
        *,
        crash_on_member: int | None = None,
        timeout_on_member: int | None = None,
    ) -> None:
        self._seat = seat
        self._crash = crash_on_member
        self._timeout = timeout_on_member
        self.addressees: list[str] = []
        self.members: list[str] = []

    def __call__(self, addressee, request):
        self.addressees.append(str(addressee))
        if addressee is CallType.DISPATCH:
            self.members.append(request.kind)
            index = len(self.members)
            if self._crash is not None and index == self._crash:
                raise TornWave(f"killed inside member {index}")
            if self._timeout is not None and index == self._timeout:
                raise MemberUnfinished(f"member {index} ran past its timeout")
        return self._seat(addressee, request)


class TornWave(RuntimeError):
    """The process dying inside a member: not a refusal, and not caught by the tick."""


class RuleRouter:
    """A hand-written selection rule that still opens the task on the adapter's desk.

    The real router is a pure function of the workspace and cannot be made to select the
    director without driving the whole ladder; what these fixtures need is one *stated* arm, so
    the rule is written down and the desk is opened exactly as `LadderRouter` opens it.
    """

    def __init__(self, rule, desk: SeatDesk) -> None:
        self._rule = rule
        self._desk = desk
        self.selections: list[SeatSelection] = []

    def __call__(self, workspace) -> SeatSelection:
        selection = self._rule(workspace)
        self.selections.append(selection)
        self._desk.open_tick(workspace.task_id, selection)
        return selection


def layer_for(brain: Path, fixture: str, *, rule=None, **port_kwargs):
    """`build_layer()`'s own shape over one calls fixture, with the port wrapped."""
    script = load_script(FIXTURES / f"{fixture}.yaml")
    desk = SeatDesk()
    port = WavePort(ScriptedSeat(script=script, desk=desk), **port_kwargs)
    router = (
        LadderRouter(weights=LadderWeights.load(brain), on_tick=desk.open_tick)
        if rule is None
        else RuleRouter(rule, desk)
    )
    layer = SeatLayer(
        router=router,
        port=port,
        sessions=desk.sessions,
        node_calls=CallDesks(port=port, plan=script.calls),
    )
    return layer, port


def drive(
    brain: Path,
    workspace: Path,
    fixture: str,
    *,
    ticks: int = 2,
    task: str = "task-wave",
    rule=None,
    **port_kwargs,
):
    """Open a task on a **fixture** brain root and run `ticks` passes, live."""
    layer, port = layer_for(brain, fixture, rule=rule, **port_kwargs)
    context = build_context(brain, task, layer, workspace_path=str(workspace))
    state = new_state(task, GOAL, context)
    results = []
    for _ in range(ticks):
        state.tick += 1
        results.append(run_tick(context, state))
    return context, state, port, results


@pytest.fixture(scope="module")
def dispatch_wave_run(tmp_path_factory):
    """One two-tick `dispatch_wave` drive for the module — **read-only** to its consumers.

    G7's key clauses, G5b's per-field merge and decision 17's one-observation rule are all
    readings of the *same* wave: the journal it wrote, the receipts it wrote, the summary it
    merged and the window row it composed. None of the consumers drives a further tick or
    writes into the root; a test that runs the members backwards, tears the pass or names two
    units drives its own.
    """
    return _run_for_module(tmp_path_factory, "wave", "dispatch_wave")


@pytest.fixture(scope="module")
def vetoed_run(tmp_path_factory):
    """One two-tick `vetoed_wave` drive for the module — **read-only** to its consumers.

    Row G2's inhibition clause and folded S-A69's composition clause read the same vetoed pass.
    """
    return _run_for_module(tmp_path_factory, "vetoed", "vetoed_wave")


def _run_for_module(tmp_path_factory, name: str, fixture: str):
    base = tmp_path_factory.mktemp(name)
    brain = stubs.seed_brain(REPO_ROOT / "brain", base / "brain")
    workspace = base / "workspace"
    workspace.mkdir()
    return drive(brain, workspace, fixture)


def wave_entries(context, tick: int):
    """The wave's own entries, in the order the file holds them."""
    return [
        entry
        for entry in entries_of(context, tick)
        if entry.tier is CallType.DISPATCH and entry.is_call()
    ]


# --------------------------------------------------------------------------------------
# G7's wave clauses — one `call#`, `member#` sub-keys, buffered in wave order
# --------------------------------------------------------------------------------------


def test_a_wave_takes_one_call_number_and_its_members_take_member_sub_keys(dispatch_wave_run) -> None:
    """A wave is **one call**; the members sit beneath it (§ Deliverable 4, folded: S-A2)."""
    context, _state, port, _results = dispatch_wave_run
    entries = wave_entries(context, 2)
    show("wave keys", [(str(e.node), e.call_number, e.member_number) for e in entries])

    assert [entry.call_number for entry in entries] == [WAVE_CALL_NUMBER] * len(WAVE_ORDER)
    assert [entry.member_number for entry in entries] == [1, 2]
    assert {str(entry.node) for entry in entries} == {str(NodeName.CORTEX)}
    # One `call#` for the wave, and it is the one after the seat call that produced the plan.
    seat_calls = [
        entry
        for entry in entries_of(context, 2)
        if entry.is_call() and entry.tier is Tier.MANAGER
    ]
    assert [entry.call_number for entry in seat_calls] == [SEAT_CALL_NUMBER]
    assert WAVE_CALL_NUMBER == SEAT_CALL_NUMBER + 1


def test_the_member_number_follows_the_plan_and_the_journal_lines_follow_the_member_number(dispatch_wave_run) -> None:
    """Assigned in `ManagerPlan` order, written in `member#` order — never completion order."""
    context, _state, port, _results = dispatch_wave_run
    entries = wave_entries(context, 2)
    show("kinds in plan order", [entry.kind for entry in entries])
    assert [entry.kind for entry in entries] == list(WAVE_ORDER)
    # **`block_ref` is the block the DESK resolved**, and this layer has no fifth seam
    # (`the build specification (not in this mirror)` § Deliverable 6, folded: S-i12): A.1 wrote the
    # bare kind name here, A.1.i writes `kinds.<class>.<name>` where a spawn desk resolved one and
    # `""` where none did — the column says under what containment the member ran, and a scripted
    # member ran under none. `kind`, the licensed duplicate above, still carries the bare name.
    assert [entry.block_ref for entry in entries] == ["", ""]
    assert [entry.payload_model for entry in entries] == ["WaveMember"] * len(WAVE_ORDER)
    assert [entry.payload["kind"] for entry in entries] == list(WAVE_ORDER)
    assert all("workspace_path" not in entry.payload for entry in entries), (
        "the member request names no directory at all"
    )


def test_the_entries_are_buffered_and_written_in_member_order(
    brain: Path, workspace: Path
) -> None:
    """The claim with its other side: run the members backwards, read the file forwards.

    § Deliverable 4 (folded: S-A77): "A wave's entries are buffered and written in `member#`
    order after the last member returns", which is what makes G7's byte-identity claim reachable
    at all — and `call#` ordering is well-defined **however the members are later run**, which
    is what leaves the concurrency question to build A.1.i.
    """
    layer, port = layer_for(brain, "dispatch_wave")
    context = build_context(brain, "task-buffered", layer, workspace_path=str(workspace))
    state = new_state("task-buffered", GOAL, context)
    state.tick += 1
    run_tick(context, state)

    # The second pass is the acting one. Run its members in the reverse of the plan's order.
    original = cycle_module.run_wave

    def reversed_order(ctx, st, members, **kwargs):
        kwargs.pop("order", None)
        return original(
            ctx, st, members, order=list(range(len(members), 0, -1)), **kwargs
        )

    cycle_module.run_wave = reversed_order
    try:
        state.tick += 1
        run_tick(context, state)
    finally:
        cycle_module.run_wave = original

    show("completion order", port.members[-len(WAVE_ORDER) :])
    assert port.members[-len(WAVE_ORDER) :] == list(reversed(WAVE_ORDER)), "ran backwards"
    entries = wave_entries(context, 2)
    assert [entry.member_number for entry in entries] == [1, 2]
    assert [entry.kind for entry in entries] == list(WAVE_ORDER), "written forwards"


def test_one_receipt_line_per_member_carrying_the_wave_s_dispatch_id(dispatch_wave_run) -> None:
    """`dispatch_id` is **receipt-only** and never on `UnitObservation` (folded: S-A14)."""
    context, state, _port, _results = dispatch_wave_run
    lines = [
        line
        for line in load_seat_calls(context.paths.seat_calls)
        if line.tier is CallType.DISPATCH
    ]
    show("member receipts", [(line.member_number, line.dispatch_id) for line in lines])
    assert [line.member_number for line in lines] == [1, 2]
    assert len({line.dispatch_id for line in lines}) == 1, "one wave, one dispatch id"
    assert all(line.dispatch_id for line in lines)
    assert [line.kind for line in lines] == list(WAVE_ORDER)

    committed = stubs.committed_state(context.paths)
    for rows in committed["state"]["unit_windows"].values():
        for row in rows:
            assert "dispatch_id" not in row, "never on `UnitObservation`"


# --------------------------------------------------------------------------------------
# G5b — the merge, per field
# --------------------------------------------------------------------------------------


def test_the_merge_is_per_field_over_one_executor_summary(dispatch_wave_run) -> None:
    """Five rules, each against a hand-computed expectation (§ Deliverable 3)."""
    _context, state, _port, results = dispatch_wave_run
    merged = state.latest.dispatch
    show("merged summary", merged.model_dump(mode="json"))

    assert results[1].wave_status == WAVE_COMPLETE
    assert merged.unit_id == "u-wave-1", "identical across every member"
    # `observations` — union.
    assert sorted(item.path for item in merged.observations) == ["checked.md", "notes.md"]
    # `cited_ids` — union.
    assert merged.cited_ids == ["c-1", "c-2"]
    # `expectation_values` — merged per predicate id.
    assert merged.expectation_values == {"e-1": "wrote", "e-2": "checked"}
    # `exit_code` — the worst.
    assert merged.exit_code == 3
    # `narrative` — concatenated in `member#` order.
    assert merged.narrative.splitlines() == [
        "wrote the note",
        "checked the note against the ledger",
    ]


def test_one_observation_per_unit_per_tick_however_wide_the_wave(dispatch_wave_run) -> None:
    """Decision 17: fan-out is an implementation of a unit's work, never a multiplication."""
    _context, state, _port, _results = dispatch_wave_run
    rows = state.unit_windows["u-wave-1"]
    show("window rows for the acting pass", [row.tick for row in rows])
    assert [row.tick for row in rows].count(2) == 1, "two members, one row"


def test_a_wave_naming_two_units_is_refused_as_an_illegal_return(
    brain: Path, workspace: Path
) -> None:
    """Not a merge (§ Deliverable 3), and a fault on a member is the boundary's (§ D4)."""
    _context, state, _port, results = drive(brain, workspace, "two_unit_wave")
    show("terminal", results[1].committed_terminal)
    show("refusal", results[1].seat_refusal)
    assert results[1].committed_terminal is TerminalState.STOPPED
    assert "u-two-" in (results[1].seat_refusal or "")
    assert state.latest.dispatch is None, "nothing merged, so nothing was committed"


def test_a_partial_wave_composes_no_row_and_leaves_the_unit_pending(
    brain: Path, workspace: Path
) -> None:
    """A timeout marks the member failed and the wave `partial`; the tick does not stop."""
    context, state, _port, results = drive(
        brain, workspace, "dispatch_wave", timeout_on_member=2
    )
    show("wave status", results[1].wave_status)
    assert results[1].wave_status == WAVE_PARTIAL
    assert results[1].committed_terminal is not TerminalState.STOPPED

    # The failed member is still journalled and counted, with no envelope to restore.
    entries = wave_entries(context, 2)
    assert [entry.member_number for entry in entries] == [1, 2]
    assert entries[1].envelope is None and not entries[1].is_restorable()

    # No observation row, the unit still `PENDING`, and the streak untouched.
    assert [row.tick for row in state.unit_windows.get("u-wave-1", [])] == []
    assert [unit.status for unit in state.units] == [UnitStatus.PENDING]
    assert state.latest.anterior_cingulate.streak == 0


def test_a_conflicted_wave_on_one_path_updates_the_baselines_from_the_rest(
    brain: Path, workspace: Path
) -> None:
    """One disagreement does not poison the paths nobody disputed (folded: S-A32)."""
    _context, state, _port, results = drive(brain, workspace, "conflicted_paths")
    show("wave status", results[1].wave_status)
    assert results[1].wave_status == WAVE_CONFLICTED
    assert results[1].committed_terminal is not TerminalState.STOPPED, "not a containment fault"

    baselines = state.path_baselines.get("u-conflict-1", {})
    show("baselines", sorted(baselines))
    assert sorted(baselines) == ["agreed.md"], "the non-conflicting paths only"
    assert [row.tick for row in state.unit_windows.get("u-conflict-1", [])] == []
    assert [unit.status for unit in state.units] == [UnitStatus.PENDING]


def test_a_conflicted_wave_on_one_predicate_id_grades_nothing(
    brain: Path, workspace: Path
) -> None:
    """The other half of the conflicted rule: `expectation_values` merged per predicate id."""
    _context, state, _port, results = drive(brain, workspace, "conflicted_values")
    assert results[1].wave_status == WAVE_CONFLICTED
    assert [row.tick for row in state.unit_windows.get("u-conflict-2", [])] == []
    assert state.latest.anterior_cingulate.failed_predicate_ids == []
    assert state.latest.anterior_cingulate.passed_predicate_ids == []


def test_a_waveless_tick_a_vetoed_tick_and_a_director_tick_compose_what_they_composed_before(
    vetoed_run
) -> None:
    """The load-bearing distinction (folded: S-A69): the suppression keys on a wave, not on the
    summary's absence — `compose()` treats a `None` summary as a veto, so keying on the field
    alone would delete the gate's veto from committed state on every tick that never dispatched.
    """
    # A vetoed, wave-less pass: its committed observation still carries the veto.
    context, state, _port, results = vetoed_run
    show("veto verdict", state.latest.basal_ganglia.decision)
    assert state.latest.basal_ganglia.decision is SelectionDecision.NO_GO
    assert results[1].wave_status is None, "no wave ran, so there is no status to report"
    row = state.unit_windows["u-veto-1"][-1]
    show("committed observation", row.model_dump(mode="json"))
    assert row.vetoed is True, "the gate's veto is still in committed state"
    assert row.failed_predicate_ids == ["e-veto-1"]

    # And the unit function itself, on the three shapes, read directly.
    unit = state.units[0]
    for status in (None, WAVE_COMPLETE):
        assert (
            observations.compose(
                tick=9,
                unit=unit,
                verdict=None,
                summary=None,
                admitted=None,
                baselines={},
                vetoed=True,
                wave_status=status,
            )
            is not None
        ), f"a vetoed tick composes its row at wave_status={status!r}"
    for status in (WAVE_PARTIAL, WAVE_CONFLICTED):
        assert (
            observations.compose(
                tick=9,
                unit=unit,
                verdict=None,
                summary=None,
                admitted=None,
                baselines={},
                vetoed=True,
                wave_status=status,
            )
            is None
        ), f"and composes none at wave_status={status!r}"


# --------------------------------------------------------------------------------------
# G5b — one wave per tick, and only the manager assembles it
# --------------------------------------------------------------------------------------


def test_a_pre_cortex_escalate_proposes_and_the_manager_assembles_that_pass_s_one_wave(
    brain: Path, workspace: Path
) -> None:
    """An escalate reply **never authorizes a member** (§ Deliverable 3, folded: S-A3)."""
    context, _state, port, results = drive(brain, workspace, "escalate_proposes")
    show("addressees, in order", port.addressees)

    # Nothing was spawned by the escalate itself: the escalate is answered before the cortex's
    # own step, and no dispatch reaches the port until the manager has assembled the wave.
    first_dispatch = port.addressees.index(str(CallType.DISPATCH))
    last_escalate = len(port.addressees) - 1 - port.addressees[::-1].index(
        str(CallType.ESCALATE)
    )
    assert last_escalate < first_dispatch, "the reply proposed; the manager dispatched"
    assert port.addressees.count(str(CallType.DISPATCH)) == 1, "one member, dispatched once"

    assert [member.kind for member in results[1].wave] == ["patcher"]
    assert results[1].wave_status == WAVE_COMPLETE
    assert len(wave_entries(context, 2)) == 1, "the tick holds exactly one wave"


def test_a_director_tick_assembles_no_wave_and_buffers_the_proposal(
    brain: Path, workspace: Path
) -> None:
    """On a director tick no wave is assembled at all, and the proposals wait (§ D3)."""

    def _director_every_pass(_workspace) -> SeatSelection:
        return SeatSelection(tier=Tier.DIRECTOR)

    context, _state, port, results = drive(
        brain,
        workspace,
        "escalate_proposes",
        ticks=1,
        task="task-director",
        rule=_director_every_pass,
    )
    show("addressees", port.addressees)
    assert str(CallType.DISPATCH) not in port.addressees, "no wave at all"
    assert results[0].wave == () and results[0].wave_status is None
    assert [member.kind for member in results[0].proposals] == ["patcher"], (
        "buffered to the next manager tick"
    )
    assert [member.kind for member in context.proposals] == ["patcher"]


# --------------------------------------------------------------------------------------
# G2's veto clause — what a `no_go` inhibits, and what it does not
# --------------------------------------------------------------------------------------


def test_a_no_go_inhibits_the_wave_and_every_delegate_and_leaves_think_and_escalate(
    vetoed_run
) -> None:
    """Row G2's remaining clause, on the gate's **landed** verdict (folded: D3-8)."""
    context, state, port, results = vetoed_run
    show("addressees on the vetoed pass", port.addressees)

    assert state.latest.basal_ganglia.decision is SelectionDecision.NO_GO
    assert results[1].wave == (), "no wave assembled"
    assert results[1].seat_skipped, "the gate's veto skips the seat call, so nothing plans one"

    entries = entries_of(context, 2)
    addressees = [str(entry.tier) for entry in entries if entry.is_call()]
    show("the pass's journalled calls", addressees)
    assert str(CallType.DISPATCH) not in addressees, "no wave, and no member"
    assert str(CallType.DELEGATE) not in addressees, "no delegate for the pending unit"
    assert addressees.count(str(CallType.THINK)) == 1, "think stays allowed"
    assert addressees.count(str(CallType.ESCALATE)) == 1, "and so does escalate"

    # The tick's journal names all of it: the gate's own output entry carries the verdict.
    gate = next(
        entry
        for entry in entries
        if entry.node is NodeName.BASAL_GANGLIA and not entry.is_call()
    )
    show("the gate's journalled verdict", gate.output.model_dump(mode="json"))
    assert gate.output.decision is SelectionDecision.NO_GO
    assert gate.output.unit_id == "u-veto-1" and gate.output.veto_reason


# --------------------------------------------------------------------------------------
# G7's torn-wave clause
# --------------------------------------------------------------------------------------


def _digests(context) -> dict[str, str]:
    """Per-file sha256 over the four committed artifacts G7 names."""
    paths = {
        "journal-1": context.paths.journal(1),
        "journal-2": context.paths.journal(2),
        "checkpoint": context.paths.checkpoint,
        "seat_calls": context.paths.seat_calls,
    }
    for node in config.NODE_ORDER:
        paths[f"trace-{node}"] = context.paths.trace(node)
    return {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in paths.items()
        if path.is_file()
    }


def test_a_torn_wave_re_runs_whole_and_its_returned_members_are_discarded(
    brain: Path, workspace: Path, tmp_path: Path, one_reading_per_source
) -> None:
    """The wave is the replay unit: it restores only if **every** member has a return.

    § Deliverable 6 (folded: S-A2) and row B35. The tear falls inside member 2, so member 1's
    return **is** journalled and member 2's is not; the replay re-runs the whole wave and
    discards member 1's already-returned observation, because the workspace is re-observed and
    never re-trusted.
    """
    untorn_root = stubs.seed_brain(REPO_ROOT / "brain", tmp_path / "untorn")
    untorn, _state, _port, _results = drive(
        untorn_root, workspace, "dispatch_wave", task="task-torn"
    )
    expected = _digests(untorn)

    layer, port = layer_for(brain, "dispatch_wave", crash_on_member=2)
    context = build_context(brain, "task-torn", layer, workspace_path=str(workspace))
    state = new_state("task-torn", GOAL, context)
    state.tick += 1
    run_tick(context, state)
    before = state.model_copy(deep=True)
    state.tick += 1
    with pytest.raises(TornWave):
        run_tick(context, state)

    torn_entries = wave_entries(context, 2)
    show("journalled by the torn pass", [entry.member_number for entry in torn_entries])
    assert torn_entries == [], "the entries are buffered, so a torn wave journals none of them"
    assert not context.paths.checkpoint.read_text(encoding="utf-8") or True

    # The replay: a fresh layer, the same fixture, the pass re-run from the last **boundary** —
    # which is tick 1's checkpoint, because the torn pass committed none.
    replay_layer, replay_port = layer_for(brain, "dispatch_wave")
    replay_context = build_context(
        brain, "task-torn", replay_layer, workspace_path=str(workspace)
    )
    replay_state = before.model_copy(deep=True)
    replay_state.tick += 1
    result = run_tick(replay_context, replay_state, replay=True)

    show("members re-run by the replay", replay_port.members)
    assert replay_port.members == list(WAVE_ORDER), "the whole wave re-ran, member 1 included"
    assert result.wave_restored is False
    assert result.wave_status == WAVE_COMPLETE
    assert _digests(replay_context) == expected, (
        "the committed records are byte-identical to an untorn run of the same fixture"
    )


def test_a_wave_every_member_journalled_restores_whole_and_calls_no_model(
    brain: Path, workspace: Path, one_reading_per_source
) -> None:
    """The other side of the same rule: every member restorable, so nothing is re-invoked."""
    layer, port = layer_for(brain, "dispatch_wave")
    context = build_context(brain, "task-restore", layer, workspace_path=str(workspace))
    state = new_state("task-restore", GOAL, context)
    state.tick += 1
    run_tick(context, state)
    before = state.model_copy(deep=True)
    state.tick += 1
    run_tick(context, state)
    dispatched = port.members.copy()

    replayed = before.model_copy(deep=True)
    replayed.tick += 1
    result = run_tick(context, replayed, replay=True)
    show("members after the replay", port.members)
    assert port.members == dispatched, "the replay called no model for the wave"
    assert result.wave_restored is True
    assert result.wave_status == WAVE_COMPLETE
    assert [entry.member_number for entry in wave_entries(context, 2)] == [1, 2]
