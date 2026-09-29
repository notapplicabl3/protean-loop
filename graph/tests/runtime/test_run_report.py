"""Row W8: `WorkloadRunReport` carries every group, and every number in it is derived.

`the build specification (not in this mirror)` § Deliverable 6 → *S6 — `WorkloadRunReport`*, § Rulings 6 and 16,
§ Named assumptions 2, § Resolutions S-19, S-27, S-43. Builder row **K9** rides beside it.

**Every assertion recomputes the number independently.** No expectation below is a literal: each
one is derived a second time, here, from `seat_calls.jsonl`'s raw lines, from the per-tick
journals' raw records, or from the cortex folder's `trace.jsonl` — and the report is asserted
equal to *that*. A test that wrote `assert report.seats[0].tokens == 15` would pin the fixture
rather than the derivation, which is the failure row W8's "none hardcoded" clause is about.

**The scenario is a scripted terminal run** (order W7 § Process step 9). The seats are
hand-written responders reporting their invocations through the `calls()` seam exactly as the
live adapter does, and the run drives itself to `interrupted` through the real ladder: the
monitor's streak crosses `mismatch_streak`, the router escalates to the planner, the planner
dismisses a detector, and the second escalation raises a question. Detector fires, dismissals,
mismatches and ungradeable predicates are all real consequences of that run, not planted values.

**The shapes a scripted run cannot produce come from a fixture `seat_calls.jsonl`** — a mid-run
version change, a decode retry, a `SeatUnavailable` refusal and S-43's `resumed_as_new` fallback
are written as lines and the report is rebuilt over them.

**Zero model calls.** Nothing here spawns a process except `git`, in the files-group case, and
the stand-in seat binary (`tests/cortex/fake_cli`), in row G7's live-layer case.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest

from protean import config
from protean.brain.jsonl import read_lines
from protean.cortex.bodies import request_on_stdin as PORT_REQUEST_ON_STDIN
from protean.cortex.layer import build_live_layer
from protean.cortex.live.invoke import RESUMED_AS_NEW as ADAPTER_RESUMED_AS_NEW
from protean.mailbox.files import build as build_mailbox
from protean.runtime import engine, journal
from protean.runtime.paths import BrainPaths
from protean.runtime.cycle import SEAT_CALL_NUMBER, WAVE_CALL_NUMBER
from protean.runtime.seat import addressee_of
from protean.runtime.report import (
    COST_KEY,
    REPORT_FILENAME,
    RESUMED_AS_NEW,
    build_report,
    load_report,
    report_path,
    request_on_stdin,
    tick_summaries,
    ungradeable,
)
from protean.runtime.seat import SeatLayer, SeatSelection
from protean.state.enums import (
    CallType,
    Escalation,
    ExpectationKind,
    InterruptKind,
    MismatchClass,
    NodeName,
    Raiser,
    TerminalState,
    Tier,
    TrapDetector,
)
from protean.state.errors import SchemaVersionMismatch
from protean.state.interrupts import InterruptRequest
from protean.state.primitives import Expectation, WorkUnit
from protean.state.records import OUTPUT_CALL_NUMBER, JournalEntry, TraceRecord
from protean.state.run_report import WorkloadRunReport, SeatRequestBytes, load_run_report
from protean.state.seat_calls import SeatCallRecord
from protean.state.seats import ExecutorSummary, ManagerPlan, WaveMember
from tests.conftest import tagged_show
from tests.cortex import fake_cli
from tests.runtime import stubs
from tests.runtime.conftest import REPO_ROOT

UNIT_ID = "u1"
EXPECTATION_ID = "e1"

#: The counters S-19 calls spend. Restated here so the assertions do not call the same helper
#: the writer called: a shared helper would make the check a tautology.
SPEND_KEYS = ("input_tokens", "cache_creation_input_tokens", "output_tokens")
CACHE_KEY = "cache_read_input_tokens"

#: One invocation's fixture usage. The three spend counters differ from each other and from the
#: cache read, so a derivation that summed the wrong subset could not accidentally agree.
USAGE = {CACHE_KEY: 40, "input_tokens": 3, "cache_creation_input_tokens": 5, "output_tokens": 7}
WALL_SECONDS = 0.25
COST_PER_CALL = 0.125
VERSION = "9.9.9 (Test)"


show = tagged_show("W8-report")


# --------------------------------------------------------------------------------------
# The scripted run: a real ladder climb, seats that report their invocations
# --------------------------------------------------------------------------------------


def _recorded_facts(seat, tier: str, index: int, outcome: str) -> dict:
    """The fields this module's report assertions are recomputed against.

    `stubs.RecordingSeat` carries the shared skeleton; the cost per call, the wall seconds and
    the turn count are what the seat-economics group is derived from here, so they are stated
    beside the numbers the assertions restate rather than inside the shared class.
    """
    return {
        "effort": "high",
        "wall_seconds": WALL_SECONDS,
        "model_usage": {f"model-{tier}": {COST_KEY: COST_PER_CALL}},
        "num_turns": 2,
    }


def _recording_seat(responder) -> stubs.RecordingSeat:
    """This module's reading of the shared recording port (`tests/runtime/stubs.py`)."""
    return stubs.RecordingSeat(
        responder=responder,
        argv=("--output-format", "json"),
        cli_version=VERSION,
        usage=dict(USAGE),
        cache_read=USAGE[CACHE_KEY],
        extra=_recorded_facts,
    )


def _planner(request) -> ManagerPlan:
    """Plans one unit the executor can never satisfy; dismisses a detector on the escalation."""
    if request.workspace.goals[0].replan_count >= 1:
        return ManagerPlan(
            tick=request.workspace.tick,
            interrupt=InterruptRequest(
                kind=InterruptKind.QUESTION,
                raised_by=Raiser.MANAGER,
                question="which file was I meant to write?",
            ),
        )
    return ManagerPlan(
        tick=request.workspace.tick,
        # **Re-based by build A.1**: the act is the manager's own dispatch wave, assembled on
        # the pass the router falls through to it with — the one arm that carries no escalation
        # (§ Deliverable 3). Every other arm is an escalation and plans without dispatching.
        wave=(
            []
            if request.escalation is not None
            else [WaveMember(kind=KIND, unit_id=UNIT_ID, admitted_ref="admitted")]
        ),
        units=[
            WorkUnit(
                id=UNIT_ID,
                goal_id=request.workspace.goals[0].id,
                intent="write the file",
                expected=[
                    Expectation(
                        id=EXPECTATION_ID,
                        kind=ExpectationKind.FILE_CONTAINS,
                        arguments={"path": "out.txt", "value": "hi"},
                    )
                ],
            )
        ],
        mismatch_class=MismatchClass.EXECUTION_SLIP,
        trap_dismissed=(
            [TrapDetector.DISLODGING]
            if request.escalation is Escalation.MISMATCH_STREAK
            else []
        ),
    )


#: The subagent kind the wave's one member asks for.
KIND = "writer"


def _executor(member) -> ExecutorSummary:
    """Reports no observation at all, so the predicate fails and is graded from an absence.

    Its request is the `WaveMember` the manager listed — a kind, a unit id and a reference, no
    path and no tick, the decoder stamping the runtime's tick over whatever it writes.
    """
    return ExecutorSummary(
        tick=0,
        unit_id=member.unit_id,
        narrative="tried and reported nothing",
        observations=[],
        cited_ids=[],
    )


def _rule(workspace) -> SeatSelection:
    """The real ladder's first rung, read off the workspace: a streak escalates to the planner."""
    if workspace.latest.manager is None:
        return SeatSelection(tier=Tier.MANAGER, escalation=Escalation.EMPTY_UNIT_STACK)
    monitor = workspace.latest.anterior_cingulate
    threshold = 3
    if monitor is not None and monitor.streak >= threshold:
        return SeatSelection(
            tier=Tier.MANAGER, escalation=Escalation.MISMATCH_STREAK, unit_id=UNIT_ID
        )
    # The fall-through: nothing escalated, so the manager acts. Tier three is not a seat and
    # the router never selects it — the dispatch rides the manager's own plan as its wave.
    return SeatSelection(tier=Tier.MANAGER, unit_id=UNIT_ID)


@dataclass(frozen=True, slots=True)
class Run:
    """One finished scripted run and everything a test needs to recompute its numbers."""

    brain: Path
    task_id: str
    terminal: TerminalState
    seat: stubs.RecordingSeat

    @property
    def paths(self):
        return BrainPaths(root=self.brain).task(self.task_id)

    def report(self):
        return load_report(report_path(self.paths))

    def seat_call_lines(self) -> list[dict]:
        """The raw lines, re-read off disk — the second source every assertion derives from."""
        return read_lines(self.paths.seat_calls)

    def journal_records(self) -> list[dict]:
        records: list[dict] = []
        for tick in self.paths.journal_ticks():
            records.extend(read_lines(self.paths.journal(tick)))
        return records


def _drive(brain: Path, workspace: Path, mailbox) -> Run:
    """The scripted run, driven to a terminal through the shipping driver."""
    seat = _recording_seat(
        stubs.member_keyed(
            {
                str(Tier.MANAGER): _planner,
                str(CallType.DISPATCH): _executor,
                str(Tier.DIRECTOR): lambda request: {"tick": request.workspace.tick},
            }
        )
    )
    layer = SeatLayer(router=stubs.StubRouter(rule=_rule), port=seat, calls=seat.calls)
    outcome = engine.start(
        brain,
        "write out.txt",
        layer,
        mailbox=mailbox,
        workspace_path=str(workspace),
        max_ticks=20,
    )
    assert outcome.terminal is not None, "the scenario must reach a terminal"
    return Run(brain=brain, task_id=outcome.task_id, terminal=outcome.terminal, seat=seat)


@pytest.fixture(scope="module")
def run(tmp_path_factory) -> Run:
    """One driven run for the module — **read-only** to its consumers.

    The report's groups are all derived from the same three artifacts a finished run leaves —
    `run_report.json`, `seat_calls.jsonl` and the journals — and thirteen of the fifteen tests
    below only re-read them and recompute. The two that *change* an artifact to watch a number
    move take `fresh_run`, so the run everything else reads is never written into.
    """
    base = tmp_path_factory.mktemp("report")
    brain = stubs.seed_brain(REPO_ROOT / "brain", base / "brain")
    workspace = base / "workspace"
    workspace.mkdir()
    return _drive(brain, workspace, stubs.StubMailbox(root=brain))


@pytest.fixture()
def fresh_run(brain: Path, workspace: Path, mailbox) -> Run:
    """A driven run of this test's own — for a consumer that rewrites one of its artifacts."""
    return _drive(brain, workspace, mailbox)


# --------------------------------------------------------------------------------------
# The run writes it, and it carries the five groups plus the count
# --------------------------------------------------------------------------------------


def test_a_scripted_terminal_run_writes_the_report_beside_its_checkpoints(run: Run) -> None:
    path = report_path(run.paths)
    show("report path", path.relative_to(run.brain))
    show("rendered", "\n" + run.report().render())

    assert path.exists() and path.name == REPORT_FILENAME
    assert path.parent == run.paths.state_dir
    report = run.report()
    assert report.task == run.task_id
    assert report.terminal is run.terminal
    assert report.schema_version == config.WORKLOAD_RUN_REPORT_SCHEMA_VERSION


def test_the_report_carries_every_group_deliverable_6_names(run: Run) -> None:
    """Five groups and § Named assumptions 2's count — the six things row W8 reads back."""
    report = run.report()
    show("groups", sorted(report.model_dump(mode="json")))

    assert [row.detector for row in report.detectors] == list(TrapDetector), "one row per detector"
    # **Re-based by build A.1**: a receipt is keyed by an **addressee** rather than a tier, so
    # the report carries one row per addressee — the two seats and the four call types
    # (§ Scaffold clause item 2, S1/S2). `config.ADDRESSEES` is the literal table, read rather
    # than restated.
    addressees = [addressee_of(name) for name in config.ADDRESSEES]
    assert [row.tier for row in report.seats] == addressees, "one row per addressee"
    assert [row.tier for row in report.mismatch] == addressees, "one row per addressee"
    assert isinstance(report.versions.versions, list)
    assert isinstance(report.files, list)
    assert isinstance(report.ungradeable_predicates, int)


def test_the_tick_count_is_the_tree_s_own(run: Run) -> None:
    journals = sorted(run.paths.state_dir.glob("journal-*.jsonl"))
    show("journal files", [path.name for path in journals])
    assert run.report().ticks == len(journals)


# --------------------------------------------------------------------------------------
# Group by group, each number recomputed from the artifact it is claimed to come from
# --------------------------------------------------------------------------------------


def test_detector_fires_equal_the_fired_scalars_on_the_journalled_verdicts(run: Run) -> None:
    fired: Counter[str] = Counter()
    for record in run.journal_records():
        if record["node"] == str(NodeName.ANTERIOR_CINGULATE) and record.get("output"):
            for scalar in record["output"].get("traps", []):
                if scalar["fired"]:
                    fired[scalar["detector"]] += 1
    show("recomputed fires", dict(fired))

    assert sum(fired.values()) > 0, "the scenario must actually fire a detector"
    for row in run.report().detectors:
        assert row.fires == fired[str(row.detector)], str(row.detector)


def test_detector_dismissals_equal_the_planner_s_own_trace_records(run: Run) -> None:
    dismissed: Counter[str] = Counter()
    for payload in read_lines(run.paths.trace(config.CORTEX_NODE)):
        record = TraceRecord.model_validate(payload)
        if record.prediction is not None and record.tier is Tier.MANAGER:
            dismissed.update(str(one) for one in record.prediction.trap_dismissed)
    show("recomputed dismissals", dict(dismissed))

    assert sum(dismissed.values()) > 0, "the scenario must actually dismiss a detector"
    for row in run.report().detectors:
        assert row.dismissals == dismissed[str(row.detector)], str(row.detector)
        assert row.confirmations == max(row.fires - row.dismissals, 0)


def test_the_over_firing_test_is_deliverable_6_s_own_sentence(run: Run) -> None:
    """"a detector whose dismissals outnumber its confirmations is over-firing" (§ Rulings 6)."""
    report = run.report()
    show("over-firing", [str(one) for one in report.over_firing()])
    for row in report.detectors:
        assert row.over_firing is (row.dismissals > row.confirmations)
    assert set(report.over_firing()) == {
        row.detector for row in report.detectors if row.dismissals > row.confirmations
    }


def test_seat_economics_are_recomputed_off_the_raw_seat_call_lines(run: Run) -> None:
    """S-19: spend is the per-iteration sum of three counters; the cache read is not in it."""
    lines = run.seat_call_lines()
    assert lines, "the run must have written seat calls"
    for row in run.report().seats:
        mine = [line for line in lines if line["tier"] == str(row.tier)]
        tokens = sum(
            sum(line["usage"].get(key, 0) for key in SPEND_KEYS) for line in mine
        )
        cache = sum(line["usage"].get(CACHE_KEY, 0) for line in mine)
        cost = sum(
            entry.get(COST_KEY, 0.0)
            for line in mine
            for entry in line["model_usage"].values()
        )
        show(
            f"{row.tier} recomputed",
            f"calls={len(mine)} tokens={tokens} cache={cache} cost={cost}",
        )
        assert row.calls == len(mine)
        assert row.tokens == tokens
        assert row.cache_read_tokens == cache
        assert row.wall_seconds == pytest.approx(
            sum(line["wall_seconds"] for line in mine)
        )
        assert row.cost_usd == pytest.approx(cost)
        assert row.cache_read_ratio == pytest.approx(
            (cache / (cache + tokens)) if (cache + tokens) else 0.0
        )


def test_the_cache_read_is_reported_as_a_ratio_and_never_added_to_spend(run: Run) -> None:
    """The other half of S-19, asserted rather than assumed: the two numbers are disjoint.

    **Re-based by build A.1**: a tick now holds several calls, and the layer's `calls` seam
    reports the invocations of its **last** port call — the live adapter's own behaviour, which
    `RecordingSeat` copies. So a line's adapter columns are present for the calls this pass
    reported and empty for the rest, exactly as they are for a restored call (order W4: "the
    journal's key is the whole of what the line can say"). The spend is therefore recomputed off
    the lines that carry usage rather than multiplied by the call count.
    """
    report = run.report()
    lines = run.seat_call_lines()
    for row in report.seats:
        if not row.calls:
            continue
        mine = [line for line in lines if line["tier"] == str(row.tier)]
        spent = sum(sum(line["usage"].get(key, 0) for key in SPEND_KEYS) for line in mine)
        show(f"{row.tier} ratio", f"{row.cache_read_ratio} over {row.tokens} spent")
        assert row.cache_read_tokens > 0, "the fixture usage carries a cache read"
        assert row.tokens == spent, "spend is the lines' own, never a per-call constant"
        assert 0.0 < row.cache_read_ratio < 1.0


def test_mismatch_rows_are_recomputed_off_the_lines_and_the_journalled_verdicts(
    run: Run,
) -> None:
    lines = run.seat_call_lines()
    matched: dict[int, bool] = {}
    for tick in run.paths.journal_ticks():
        for record in read_lines(run.paths.journal(tick)):
            if record["node"] == str(NodeName.ANTERIOR_CINGULATE) and record.get("output"):
                matched[tick] = bool(record["output"]["match"])

    for row in run.report().mismatch:
        mine = [line for line in lines if line["tier"] == str(row.tier)]
        ticks = sorted({line["tick"] for line in mine} & set(matched))
        missed = [tick for tick in ticks if not matched[tick]]
        show(f"{row.tier} recomputed mismatch", f"{len(missed)}/{len(ticks)}")
        assert row.graded_ticks == len(ticks)
        assert row.mismatch_ticks == len(missed)
        assert row.mismatch_rate == pytest.approx(
            (len(missed) / len(ticks)) if ticks else 0.0
        )
        assert row.decode_retries == sum(1 for one in mine if one["outcome"] == "decode_retry")
        assert row.seat_unavailable == sum(1 for one in mine if one["outcome"] == "unavailable")
    assert any(row.mismatch_ticks for row in run.report().mismatch), (
        "the scenario must actually produce a mismatch"
    )


def test_the_versions_group_is_every_cli_version_the_lines_carry(run: Run) -> None:
    seen: list[str] = []
    for line in run.seat_call_lines():
        if line["cli_version"] and line["cli_version"] not in seen:
            seen.append(line["cli_version"])
    show("recomputed versions", seen)
    assert run.report().versions.versions == seen
    assert run.report().versions.changed_mid_run is (len(seen) > 1)


def test_the_ungradeable_count_is_recomputed_from_the_units_and_the_summaries(
    run: Run,
) -> None:
    """§ Named assumptions 2: predicates graded from an absence, counted where they happened."""
    units = {
        unit["id"]: unit
        for unit in stubs.committed_state(run.paths)["state"]["units"]
    }
    total = 0
    for record in run.journal_records():
        # **Re-based by build A.1**: the act is a **dispatch member**, and what a member
        # returned lives on its call entry's envelope rather than on a node output entry — the
        # journal's half of C2 carries "the returned envelope", and the merged observation is
        # committed state (§ Deliverable 4). So the recompute decodes the envelopes the wave
        # journalled, which is the artifact the report reads too.
        if record["node"] != str(NodeName.CORTEX) or not record.get("envelope"):
            continue
        if record.get("tier") != str(CallType.DISPATCH):
            continue
        output = json.loads(record["envelope"]["result"])
        unit = units.get(output["unit_id"])
        if unit is None:
            continue
        for predicate in unit["expected"]:
            # `file_contains` with no `expectation_values` entry: the evaluator answered from
            # an absence, which is exactly what the count is of.
            if predicate["kind"] == str(ExpectationKind.FILE_CONTAINS) and not isinstance(
                output.get("expectation_values", {}).get(predicate["id"]), str
            ):
                total += 1
    show("recomputed ungradeable", total)
    assert total > 0, "the scenario must actually produce an ungradeable grading"
    assert run.report().ungradeable_predicates == total


# --------------------------------------------------------------------------------------
# Not hardcoded: change the artifacts, and every number moves with them
# --------------------------------------------------------------------------------------


def test_every_number_moves_when_the_artifact_it_is_derived_from_moves(fresh_run: Run) -> None:
    """The strongest form of "none hardcoded": double the lines, watch the totals double."""
    run = fresh_run
    before = build_report(run.brain, run.task_id, terminal=run.terminal)
    lines = run.seat_call_lines()
    doubled = []
    for line in lines:
        twin = dict(line)
        twin["tick"] = int(twin["tick"]) + 1000
        doubled.append(twin)
    with run.paths.seat_calls.open("a", encoding="utf-8") as handle:
        for twin in doubled:
            handle.write(json.dumps(twin, separators=(",", ":")) + "\n")

    after = build_report(run.brain, run.task_id, terminal=run.terminal)
    show("calls before/after", (
        [row.calls for row in before.seats], [row.calls for row in after.seats]
    ))
    for original, changed in zip(before.seats, after.seats, strict=True):
        assert changed.calls == original.calls * 2, str(original.tier)
        assert changed.tokens == original.tokens * 2
        assert changed.cache_read_tokens == original.cache_read_tokens * 2
        assert changed.cost_usd == pytest.approx(original.cost_usd * 2)


def test_a_report_over_an_empty_task_is_zero_everywhere_and_not_a_default(
    brain: Path, workspace: Path
) -> None:
    """The control: the same code over a task with no artifacts reports nothing, not a fixture."""
    empty = build_report(brain, "task-that-never-ran", workspace_path=str(workspace))
    show("empty report", empty.render())
    assert empty.ticks == 0
    assert all(row.calls == 0 and row.tokens == 0 for row in empty.seats)
    assert all(row.fires == 0 and row.dismissals == 0 for row in empty.detectors)
    assert empty.versions.versions == []
    assert empty.ungradeable_predicates == 0


# --------------------------------------------------------------------------------------
# The shapes a scripted run cannot produce, from a fixture `seat_calls.jsonl`
# --------------------------------------------------------------------------------------


def _fixture_line(**fields) -> dict:
    line = {
        "schema_version": config.SEAT_CALL_SCHEMA_VERSION,
        "task": "task-fixture",
        "tick": 1,
        "tier": str(Tier.MANAGER),
        "node": str(NodeName.CORTEX),
        "call_number": SEAT_CALL_NUMBER,
        "member_number": None,
        "ref": None,
        # **`request` is removed from the receipt by build A.1** (§ Scaffold clause item 2, S2,
        # folded: S-A73): the request payload lives in the journal alone, because a fact with
        # two homes is a fact with two versions.
        "session_handle": "handle-planner",
        "model": "model-planner",
        "effort": "high",
        "permission_mode": None,
        "cli_version": VERSION,
        "usage": dict(USAGE),
        "model_usage": {"model-planner": {COST_KEY: COST_PER_CALL}},
        "wall_seconds": WALL_SECONDS,
        "outcome": "ok",
        "argv": [],
        "num_turns": 1,
        "error": "",
    }
    line.update(fields)
    return line


@pytest.fixture()
def fixture_calls(brain: Path):
    """Write a hand-built `seat_calls.jsonl` for a task and hand back its report builder."""

    def _write(lines: list[dict], task_id: str = "task-fixture"):
        paths = BrainPaths(root=brain).task(task_id)
        paths.state_dir.mkdir(parents=True, exist_ok=True)
        paths.seat_calls.write_text(
            "".join(json.dumps(line, separators=(",", ":")) + "\n" for line in lines),
            encoding="utf-8",
        )
        return build_report(brain, task_id)

    return _write


def test_a_mid_run_version_change_is_flagged(fixture_calls) -> None:
    """§ Rulings 16's mitigation: the unpinned binary moving mid-run is visible, not silent."""
    report = fixture_calls(
        [
            _fixture_line(tick=1),
            _fixture_line(tick=2, cli_version="9.9.10 (Test)"),
            _fixture_line(tick=3, cli_version="9.9.10 (Test)"),
        ]
    )
    show("versions", report.versions.model_dump(mode="json"))
    assert report.versions.versions == [VERSION, "9.9.10 (Test)"]
    assert report.versions.changed_mid_run is True


def test_one_version_all_run_is_not_flagged(fixture_calls) -> None:
    report = fixture_calls([_fixture_line(tick=1), _fixture_line(tick=2)])
    show("versions", report.versions.model_dump(mode="json"))
    assert report.versions.versions == [VERSION]
    assert report.versions.changed_mid_run is False


def test_the_mismatch_group_counts_retries_refusals_and_the_s43_fallback(
    fixture_calls,
) -> None:
    report = fixture_calls(
        [
            _fixture_line(tick=1, outcome="decode_retry"),
            _fixture_line(tick=1, outcome="ok"),
            _fixture_line(tick=2, outcome="unavailable", error="exit 1: the CLI refused"),
            _fixture_line(tick=3, error=f"{RESUMED_AS_NEW}: --resume was rejected"),
            _fixture_line(tick=4, tier=str(CallType.DISPATCH)),
        ]
    )
    planner = report.tier_mismatch(Tier.MANAGER)
    show("manager mismatch row", planner.model_dump(mode="json"))
    assert planner.decode_retries == 1
    assert planner.seat_unavailable == 1
    assert planner.resumed_as_new == 1
    # **Re-based by build A.1**: the rows are keyed by **addressee**, so the dispatch row is
    # looked up on the list rather than through `tier_mismatch()`, whose `Tier()` coercion
    # refuses a call type. That coercion is `src/protean/state/run_report.py`'s and is outside
    # this order's writable set — see the dispatch ledger's blocked entry.
    dispatched = next(row for row in report.mismatch if row.tier is CallType.DISPATCH)
    assert dispatched.decode_retries == 0


def test_the_fallback_marker_is_the_adapter_s_own_token() -> None:
    """The restated literal cannot drift: the two names are pinned equal."""
    show("marker", RESUMED_AS_NEW)
    assert RESUMED_AS_NEW == ADAPTER_RESUMED_AS_NEW


def test_a_line_at_an_unknown_schema_version_is_refused_not_migrated(fixture_calls) -> None:
    with pytest.raises(SchemaVersionMismatch) as raised:
        fixture_calls([_fixture_line(schema_version=config.SEAT_CALL_SCHEMA_VERSION + 1)])
    show("refusal", str(raised.value))
    assert "seat_calls" in str(raised.value)


# --------------------------------------------------------------------------------------
# The files group, and the report's own loader
# --------------------------------------------------------------------------------------


def test_the_files_group_is_the_clone_s_own_changes(run: Run, shared_clone: Path) -> None:
    """The group is read off a **real** work tree — `tests/runtime/conftest.py`'s own clone.

    `test_archive.py::test_the_files_group_is_git_s_own_status_letters` was removed in favour of
    the exact dict equality below, which subsumes its two `in` checks over the same git call, so
    the only direct `changed_files` unit coverage now rides `build_report`.
    """
    report = build_report(
        run.brain, run.task_id, terminal=run.terminal, workspace_path=str(shared_clone)
    )
    rows = {row.path: row.status for row in report.files}
    show("files group", rows)
    assert rows == {"answer.txt": "A", "scratch.txt": "??"}
    assert report.notes == [], "a real clone leaves nothing unexplained"


def test_a_run_with_no_clone_reports_no_files_and_says_why(run: Run) -> None:
    report = build_report(run.brain, run.task_id, terminal=run.terminal, workspace_path="")
    show("notes", report.notes)
    assert report.files == []
    assert any("no workspace" in note for note in report.notes)


def test_the_report_loader_refuses_a_version_it_does_not_write(fresh_run: Run) -> None:
    path = report_path(fresh_run.paths)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = config.WORKLOAD_RUN_REPORT_SCHEMA_VERSION + 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SchemaVersionMismatch) as raised:
        load_report(path)
    show("refusal", str(raised.value))
    assert "workload_run_report" in str(raised.value)


# --------------------------------------------------------------------------------------
# `ungradeable()`, arm by arm against the evaluator it mirrors
# --------------------------------------------------------------------------------------


def _summary(**fields) -> ExecutorSummary:
    base = {"tick": 1, "unit_id": UNIT_ID, "narrative": "-"}
    base.update(fields)
    return ExecutorSummary(**base)


@pytest.mark.parametrize(
    "expectation,summary,expected",
    [
        (
            Expectation(id="e", kind=ExpectationKind.FILE_EXISTS, arguments={"path": "a.txt"}),
            _summary(),
            True,
        ),
        (
            Expectation(id="e", kind=ExpectationKind.FILE_ABSENT, arguments={"path": "a.txt"}),
            _summary(),
            True,
        ),
        (
            Expectation(
                id="e", kind=ExpectationKind.FILE_CONTAINS,
                arguments={"path": "a.txt", "value": "hi"},
            ),
            _summary(),
            True,
        ),
        (
            Expectation(
                id="e", kind=ExpectationKind.FILE_CONTAINS,
                arguments={"path": "a.txt", "value": "hi"},
            ),
            _summary(expectation_values={"e": "hi there"}),
            False,
        ),
        (
            Expectation(
                id="e", kind=ExpectationKind.SUMMARY_FIELD_EQUALS,
                arguments={"field": "exit_code", "value": 0},
            ),
            _summary(),
            False,
        ),
        (
            Expectation(
                id="e", kind=ExpectationKind.SUMMARY_FIELD_EQUALS,
                arguments={"field": "a_field_no_summary_has", "value": 0},
            ),
            _summary(),
            True,
        ),
        (
            Expectation(id="e", kind=ExpectationKind.EXIT_CODE, arguments={"code": 0}),
            _summary(),
            False,
        ),
        (
            Expectation(id="e", kind=ExpectationKind.EXIT_CODE, arguments={}),
            _summary(),
            True,
        ),
    ],
)
def test_ungradeable_is_an_absence_of_evidence_not_a_failing_value(
    expectation, summary, expected: bool
) -> None:
    show(f"{expectation.kind} {expectation.arguments}", ungradeable(expectation, summary))
    assert ungradeable(expectation, summary) is expected


# --------------------------------------------------------------------------------------
# A wave naming two units: the report re-derives the tick's verdict, it never raises
# --------------------------------------------------------------------------------------

#: The second unit a two-unit wave names beside `UNIT_ID`.
OTHER_UNIT_ID = "u2"


def _two_unit_planner(request) -> ManagerPlan:
    """Mints two units and dispatches one member at each — a wave whose returns name two ids."""
    units = [
        WorkUnit(id=unit_id, goal_id=request.workspace.goals[0].id, intent=f"write {unit_id}")
        for unit_id in (UNIT_ID, OTHER_UNIT_ID)
    ]
    return ManagerPlan(
        tick=request.workspace.tick,
        wave=[
            WaveMember(kind=KIND, unit_id=unit.id, admitted_ref="admitted") for unit in units
        ],
        units=units,
    )


def test_a_wave_naming_two_units_leaves_its_tick_without_a_summary_and_the_report_is_written(
    brain: Path, workspace: Path, mailbox
) -> None:
    """The tick loop's merge hears two unit ids among a wave's returns as an **illegal return,
    not a merge** (§ Deliverable 3) and completes the tick `stopped` with no summary.
    `tick_summaries()` re-merges the same journalled returns, so it must reach the same verdict
    the same way: that tick carries no summary, and `engine.start`'s close-out writes the report
    rather than raising out of it (the A.2 specification § Resolutions D12-5)."""
    seat = _recording_seat(
        stubs.member_keyed(
            {
                str(Tier.MANAGER): _two_unit_planner,
                str(CallType.DISPATCH): _executor,
                str(Tier.DIRECTOR): lambda request: {"tick": request.workspace.tick},
            }
        )
    )
    layer = SeatLayer(
        router=stubs.StubRouter(rule=lambda workspace: SeatSelection(tier=Tier.MANAGER)),
        port=seat,
        calls=seat.calls,
    )
    outcome = engine.start(
        brain,
        "write two files",
        layer,
        mailbox=mailbox,
        workspace_path=str(workspace),
        max_ticks=3,
    )
    paths = BrainPaths(root=brain).task(outcome.task_id)

    # The premise, re-read off the raw journal lines: one tick's two dispatch members, each
    # returning a summary for a different unit.
    by_tick: dict[int, dict[int, str]] = {}
    for tick in paths.journal_ticks():
        for record in read_lines(paths.journal(tick)):
            if record["tier"] == str(CallType.DISPATCH) and record.get("envelope"):
                returned = json.loads(record["envelope"]["result"])
                by_tick.setdefault(tick, {})[record["member_number"]] = returned["unit_id"]
    (wave_tick,) = [tick for tick, members in by_tick.items() if len(members) == 2]
    show("wave members", by_tick[wave_tick])
    assert sorted(by_tick[wave_tick].values()) == [UNIT_ID, OTHER_UNIT_ID], "two distinct units"
    show("terminal", outcome.terminal)

    assert outcome.terminal is TerminalState.STOPPED
    assert report_path(paths).exists(), "the close-out wrote the report"
    summaries = tick_summaries(paths)
    show("summarised ticks", sorted(summaries))
    assert wave_tick not in summaries, "the tick produced no summary, so the report reads none"


# --------------------------------------------------------------------------------------
# Row G7 (A.3 § Deliverable 4): each seat call's request bytes, on the report
# --------------------------------------------------------------------------------------
#
# Every expected byte count below is recomputed off the raw journal lines with the **port's
# own** serializer, `protean.cortex.bodies.request_on_stdin` — never with the restatement the
# writer calls — so a drift between the two fails a derivation case as well as the pin.


#: The report field these cases read, named once so the pre-build payload drops exactly it.
SEAT_REQUESTS = "seat_requests"

#: Non-ASCII on purpose: a request's UTF-8 length and its character count differ, so a reading
#: that counted characters could not agree with the stand-in's recorded stdin by accident.
G7_GOAL = "report each request’s bytes — naïve café, 日本語, ✓"


def _seat_call_bytes(records: list[tuple[int, dict]]) -> list[tuple[int, str, int]]:
    """`(tick, tier, bytes)` per journalled seat-call record, off the raw lines.

    A seat call is a cortex **call** entry — any `call_number` but the node's own output's —
    addressed `director` or `manager` (`config.TIERS`), answered or refused alike.
    """
    return [
        (tick, record["tier"], len(PORT_REQUEST_ON_STDIN(record["payload"]).encode("utf-8")))
        for tick, record in records
        if record["node"] == config.CORTEX_NODE
        and record["call_number"] != OUTPUT_CALL_NUMBER
        and record["tier"] in config.TIERS
    ]


def _journal_lines(paths) -> list[tuple[int, dict]]:
    return [
        (tick, record)
        for tick in paths.journal_ticks()
        for record in read_lines(paths.journal(tick))
    ]


def _rows(report) -> list[tuple[int, str, int]]:
    return [(row.tick, str(row.tier), row.request_bytes) for row in report.seat_requests]


def _entry(task: str, tick: int, node: NodeName, **fields) -> JournalEntry:
    return JournalEntry(
        schema_version=config.JOURNAL_SCHEMA_VERSION, task=task, tick=tick, node=node, **fields
    )


def test_G7_one_row_per_journalled_seat_call_entry_a_refused_call_s_included(
    brain: Path, run: Run
) -> None:
    """Hand-written journals holding every entry shape a tick writes, then the scripted run.

    Two entries are seat calls — an answered manager call and a **refused** director call,
    journalled with its request and no envelope — and four are not: the cortex's own output
    entries, a dispatch wave member and an outer node's think call.
    """
    task = "task-g7-rows"
    paths = BrainPaths(root=brain).task(task)
    answered = {"workspace": {"tick": 1, "goals": [{"text": "écrire « out.txt » ✓"}]}}
    refused = {"workspace": {"tick": 2, "goals": [{"text": "日本語のゴール"}]}, "escalation": None}
    shapes = {
        1: [
            _entry(task, 1, NodeName.CORTEX, call_number=SEAT_CALL_NUMBER, tier=Tier.MANAGER,
                   payload=answered, payload_model="ManagerRequest",
                   envelope=stubs.envelope({"cited_ids": []})),
            _entry(task, 1, NodeName.CORTEX, call_number=WAVE_CALL_NUMBER, member_number=1,
                   tier=CallType.DISPATCH, payload={"kind": KIND, "unit_id": UNIT_ID}),
            _entry(task, 1, NodeName.ANTERIOR_CINGULATE, call_number=1, tier=CallType.THINK,
                   payload={"question": "is the file there?"}),
            _entry(task, 1, NodeName.CORTEX, tier=Tier.MANAGER),
        ],
        2: [
            _entry(task, 2, NodeName.CORTEX, call_number=SEAT_CALL_NUMBER, tier=Tier.DIRECTOR,
                   payload=refused, payload_model="DirectorRequest"),
            _entry(task, 2, NodeName.CORTEX, tier=Tier.DIRECTOR),
        ],
    }
    for tick, entries in shapes.items():
        journal.start_tick(paths.journal(tick))
        for entry in entries:
            journal.append(paths.journal(tick), entry)

    lines = _journal_lines(paths)
    expected = _seat_call_bytes(lines)
    report = build_report(brain, task)
    show("hand-written journals: rows", _rows(report), tag="G7")
    assert _rows(report) == expected
    assert [(tick, tier) for tick, tier, _ in expected] == [
        (1, str(Tier.MANAGER)), (2, str(Tier.DIRECTOR))
    ], "the premise: two seat calls among six entries"
    refused_line = next(record for tick, record in lines if tick == 2 and record["payload"])
    assert refused_line["envelope"] is None, "the premise: the director call was refused"
    for (_, _, size), payload in zip(expected, [answered, refused], strict=True):
        assert size > len(PORT_REQUEST_ON_STDIN(payload)), "non-ASCII: bytes exceed characters"

    # The same derivation over the scripted terminal run the rest of this module reads.
    scripted = _seat_call_bytes(_journal_lines(run.paths))
    show("scripted run: rows", _rows(run.report()), tag="G7")
    assert scripted, "the scripted run made seat calls"
    assert _rows(run.report()) == scripted


def test_G7_the_restated_serializer_is_the_port_s_own(run: Run) -> None:
    """The restated function cannot drift: over sample payloads and every request the scripted
    run journalled, its text equals the port's (`RESUMED_AS_NEW`'s precedent)."""
    samples: list[dict] = [
        {},
        {"a": 1, "b": [1, 2.5, None, True], "c": {"d": "plain ascii"}},
        {"accents": "naïve café", "dash": "—", "cjk": "日本語", "emoji": "✓ 🙂"},
        {"nested": [{"quote": "« guillemets »", "escape": "tab\tand\\slash"}]},
    ]
    samples.extend(record["payload"] for _, record in _journal_lines(run.paths)
                   if record["payload"])
    for payload in samples:
        assert request_on_stdin(payload) == PORT_REQUEST_ON_STDIN(payload)
    widest = samples[2]
    show("non-ASCII sample: chars / UTF-8 bytes",
         (len(request_on_stdin(widest)), len(request_on_stdin(widest).encode("utf-8"))), tag="G7")
    assert len(request_on_stdin(widest).encode("utf-8")) > len(request_on_stdin(widest))
    assert len(samples) > 4, "the scripted run's journalled requests are among the samples"


def test_G7_on_a_live_layer_run_each_row_s_bytes_are_the_stand_in_s_recorded_stdin(
    tmp_path: Path, monkeypatch, load_envelope
) -> None:
    """The live layer on the stand-in (`tests/cortex/test_live_seat.py`'s shape): tick 1's
    manager call is answered, tick 2's is refused by a non-zero exit, and the run stops.

    The report the close-out wrote on that `stopped` terminal carries one row per invocation,
    each row's bytes the byte length of the stdin the stand-in recorded for the same call — so a
    run that stops on a refused call still reports that call's bytes.
    """
    binaries = fake_cli.install(
        tmp_path / "bin",
        [fake_cli.envelope(fake_cli.planner_result("u1", "g1")),
         load_envelope("live_refusal.json")],
        exit_codes=[0, 1],
    )
    fake_cli.on_path(monkeypatch, binaries)
    root = fake_cli.seed_live_root(tmp_path / "brain")
    outcome = engine.start(
        root, G7_GOAL, build_live_layer(root=root), mailbox=build_mailbox(root), max_ticks=2
    )
    paths = BrainPaths(root=root).task(outcome.task_id)
    rows = load_report(report_path(paths)).seat_requests
    recorded = [
        fake_cli.stdin_of(binaries, index)
        for index in range(1, fake_cli.invocations(binaries) + 1)
    ]
    show("rows", [(row.tick, str(row.tier), row.request_bytes) for row in rows], tag="G7")
    show("stand-in stdin bytes", [len(text.encode("utf-8")) for text in recorded], tag="G7")

    assert outcome.terminal is TerminalState.STOPPED, "the second call's refusal stopped the run"
    assert len(rows) == len(recorded) == 2, "one row per invocation, one invocation per call"
    for row, stdin in zip(rows, recorded, strict=True):
        assert row.request_bytes == len(stdin.encode("utf-8"))
    assert G7_GOAL in recorded[0], "the non-ASCII goal rode the request"
    assert len(recorded[0].encode("utf-8")) > len(recorded[0])
    refused = [
        record for tick, record in _journal_lines(paths)
        if tick == rows[-1].tick and record["node"] == config.CORTEX_NODE
        and record["call_number"] == SEAT_CALL_NUMBER
    ]
    assert [record["envelope"] for record in refused] == [None], "the last row is the refusal"


def test_G7_a_report_payload_written_before_the_field_existed_still_loads(run: Run) -> None:
    """A pre-build report is today's payload without the one new field; it loads, empty."""
    payload = json.loads(report_path(run.paths).read_text(encoding="utf-8"))
    assert payload[SEAT_REQUESTS], "the premise: this run's report carries rows"
    del payload[SEAT_REQUESTS]
    show("pre-build keys", sorted(payload), tag="G7")
    assert set(payload) == set(WorkloadRunReport.model_fields) - {SEAT_REQUESTS}

    loaded = load_run_report(payload, expected=config.WORKLOAD_RUN_REPORT_SCHEMA_VERSION)
    assert loaded.seat_requests == []
    dumped = loaded.model_dump(mode="json")
    del dumped[SEAT_REQUESTS]
    assert dumped == payload, "every other field loads as written"


def test_G7_render_names_the_largest_request(run: Run) -> None:
    """The largest row by bytes — its tick, its tier and its bytes — or `-` with none."""
    report = run.report()
    rows = [
        SeatRequestBytes(tick=1, tier=Tier.MANAGER, request_bytes=11),
        SeatRequestBytes(tick=2, tier=Tier.DIRECTOR, request_bytes=13),
        SeatRequestBytes(tick=3, tier=Tier.MANAGER, request_bytes=12),
    ]
    for candidate in (report, report.model_copy(update={SEAT_REQUESTS: rows})):
        top = max(candidate.seat_requests, key=lambda row: row.request_bytes)
        (line,) = [one for one in candidate.render().splitlines() if one.startswith("request")]
        show("render", line, tag="G7")
        assert f"{top.request_bytes} bytes" in line
        assert str(top.tier) in line and f"tick {top.tick}" in line
    empty = report.model_copy(update={SEAT_REQUESTS: []})
    (line,) = [one for one in empty.render().splitlines() if one.startswith("request")]
    assert line.split() == ["request", "-"]


def test_G7_the_report_s_schema_version_stays_1(run: Run) -> None:
    """No schema version moves (A.3 § Scaffold clause item 2): the field defaults empty."""
    show("WORKLOAD_RUN_REPORT_SCHEMA_VERSION", config.WORKLOAD_RUN_REPORT_SCHEMA_VERSION, tag="G7")
    assert config.WORKLOAD_RUN_REPORT_SCHEMA_VERSION == 1
    assert run.report().schema_version == config.WORKLOAD_RUN_REPORT_SCHEMA_VERSION


def test_G7_the_bytes_live_on_the_report_and_the_seat_call_receipt_gains_nothing(
    run: Run,
) -> None:
    """`SeatCallRecord` and `seat_calls.jsonl` gain nothing: the rows are the report's alone."""
    fields = set(SeatCallRecord.model_fields)
    show("SeatCallRecord fields", sorted(fields), tag="G7")
    assert not fields & (set(SeatRequestBytes.model_fields) - {"tick", "tier"})
    assert SEAT_REQUESTS not in fields
    lines = run.seat_call_lines()
    assert lines and all(set(line) == fields for line in lines)
