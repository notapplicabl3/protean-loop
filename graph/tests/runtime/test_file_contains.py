"""G12 — a `FILE_CONTAINS` expectation is graded from the clone, never from a member's word.

`the build specification (not in this mirror)` § Deliverable 5 (A.2 L25, Option B), § Scaffold clause item
2(e) and § Resolutions E18. After `merge_wave()` returns and before the monitor's projection, the
runtime reads each `FILE_CONTAINS` path of the merged summary's unit under the task workspace,
realpath-confined, and writes **the file's text as read** into `expectation_values[id]`: the
runtime's read replaces a member-reported value; a missing file or a path whose realpath leaves
the workspace deletes that value and writes none (F4); `merge_wave()` is byte-unchanged, so a wave
conflicted on the id stays conflicted; a replayed tick re-reads the clone; and the run report's
`ungradeable_count` keeps A.2's member-reported reading (F14, F30, F32) — a named limit, R26.
Every case is named for its row, so `-k G12` selects them all.

**The waves are scripted here, over a real workspace** — the form of
`tests/runtime/test_run_report.py`'s scripted run: a manager that plans one unit carrying one
`FILE_CONTAINS` expectation on its first tick and dispatches a wave for it on its second, and
members whose reported `expectation_values` each case chooses. The workspace is the test's own
temporary directory, so the file the monitor is graded against is one the case wrote.

**A grade is read where the run keeps it**: the journalled `MonitorVerdict` at the wave's tick,
and the committed checkpoint's `latest.dispatch` for the value the fill stored. Nothing here
recomputes a grade through the fill itself.

**Zero model calls.** Every answer is a scripted responder behind `stubs.StubSeat`; nothing spawns
a process.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protean.runtime import observations
from protean.runtime import report as report_module
from protean.runtime.cycle import run_tick
from protean.runtime.engine import build_context, new_state
from protean.runtime.seat import SeatLayer, SeatSelection
from protean.state.enums import CallType, Escalation, ExpectationKind, NodeName, Tier
from protean.state.inputs import WAVE_COMPLETE, WAVE_CONFLICTED
from protean.state.outputs import MonitorVerdict
from protean.state.primitives import Expectation, WorkUnit
from protean.state.seats import ExecutorSummary, ManagerPlan, WaveMember
from tests.conftest import tagged_show
from tests.runtime import stubs
from tests.runtime.conftest import entries_of

UNIT_ID = "u-file"
EXPECTATION_ID = "e-contains"
TARGET = "out.txt"

#: The substring the unit's one predicate asks the file for.
VALUE = "the answer"

#: A member report that is a string but not the value — "whatever a member reported".
UNRELATED = "something else entirely"

GOAL = "write the answer into out.txt"

#: The tick the wave runs on: the manager plans the unit on the first tick and dispatches its
#: wave on the second (the exemplar's own two-step shape).
WAVE_TICK = 2

#: The two member kinds a two-member wave lists, in `member#` order.
MEMBER_KINDS = ("writer", "checker")

show = tagged_show("G12")


# --------------------------------------------------------------------------------------
# The scripted wave: one unit, one `FILE_CONTAINS` predicate, members that report a value
# --------------------------------------------------------------------------------------


def _unit(goal_id: str, path: str) -> WorkUnit:
    return WorkUnit(
        id=UNIT_ID,
        goal_id=goal_id,
        intent="write the answer",
        expected=[
            Expectation(
                id=EXPECTATION_ID,
                kind=ExpectationKind.FILE_CONTAINS,
                arguments={"path": path, "value": VALUE},
            )
        ],
    )


def _planner(path: str, kinds: tuple[str, ...]):
    """Plans the unit while escalated; dispatches its wave on the pass that carries no rung."""

    def _plan(request) -> ManagerPlan:
        return ManagerPlan(
            tick=request.workspace.tick,
            units=[_unit(request.workspace.goals[0].id, path)],
            wave=(
                []
                if request.escalation is not None
                else [
                    WaveMember(kind=kind, unit_id=UNIT_ID, admitted_ref="admitted")
                    for kind in kinds
                ]
            ),
        )

    return _plan


def _members(reported: tuple[str | None, ...]):
    """One responder per member kind: member `n` reports `reported[n]` for the id, or nothing."""
    by_kind = dict(zip(MEMBER_KINDS, reported))

    def _member(member: WaveMember) -> ExecutorSummary:
        value = by_kind[member.kind]
        return ExecutorSummary(
            tick=0,
            unit_id=member.unit_id,
            narrative=f"{member.kind} reported {value!r}",
            expectation_values={} if value is None else {EXPECTATION_ID: value},
        )

    return _member


def _rule(workspace) -> SeatSelection:
    """Plan while the unit stack is empty, then fall through to the manager's acting pass."""
    if workspace.latest.manager is None:
        return SeatSelection(tier=Tier.MANAGER, escalation=Escalation.EMPTY_UNIT_STACK)
    return SeatSelection(tier=Tier.MANAGER, unit_id=UNIT_ID)


def open_run(brain: Path, workspace: Path, *, path: str, reported: tuple[str | None, ...]):
    """A task opened on a throwaway root over `workspace`, with nothing run yet."""
    kinds = MEMBER_KINDS[: len(reported)]
    seat = stubs.StubSeat(
        responder=stubs.member_keyed(
            {
                str(Tier.MANAGER): _planner(path, kinds),
                str(CallType.DISPATCH): _members(reported),
                str(Tier.DIRECTOR): lambda request: {"tick": request.workspace.tick},
            }
        )
    )
    layer = SeatLayer(router=stubs.StubRouter(rule=_rule), port=seat)
    context = build_context(brain, "task-g12", layer, workspace_path=str(workspace))
    state = new_state("task-g12", GOAL, context)
    return context, state, seat


def drive(brain: Path, workspace: Path, *, path: str = TARGET, reported=(None,)):
    """Open the task and run it through the wave's tick, live."""
    context, state, seat = open_run(brain, workspace, path=path, reported=reported)
    results = []
    while state.tick < WAVE_TICK:
        state.tick += 1
        results.append(run_tick(context, state))
    return context, state, seat, results


def journalled_verdict(context, tick: int = WAVE_TICK) -> MonitorVerdict:
    """The monitor's own output entry at that tick — the run's grade (R4's "the work's own")."""
    verdicts = [
        entry.output
        for entry in entries_of(context, tick)
        if entry.node is NodeName.ANTERIOR_CINGULATE and isinstance(entry.output, MonitorVerdict)
    ]
    assert len(verdicts) == 1, "one monitor output entry per tick"
    return verdicts[0]


def committed_values(context) -> dict:
    """`latest.dispatch.expectation_values` off the committed checkpoint on disk."""
    dispatch = stubs.committed_state(context.paths)["state"]["latest"]["dispatch"]
    assert dispatch is not None, "the wave's merged summary is committed to latest.dispatch"
    return dispatch["expectation_values"]


def grade(verdict: MonitorVerdict) -> str:
    """`passed`, `failed` or `ungraded` for the one predicate."""
    if EXPECTATION_ID in verdict.passed_predicate_ids:
        return "passed"
    if EXPECTATION_ID in verdict.failed_predicate_ids:
        return "failed"
    return "ungraded"


def dispatches(seat: stubs.StubSeat) -> int:
    return sum(1 for addressee, _request in seat.calls if addressee == str(CallType.DISPATCH))


# --------------------------------------------------------------------------------------
# G12 — the clauses, one named case each
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("reported", [None, VALUE, UNRELATED], ids=["none", "matching", "unrelated"])
@pytest.mark.parametrize(
    "text,expected",
    [(f"before {VALUE} after\n", "passed"), ("nothing to see here\n", "failed")],
    ids=["file-contains", "file-lacks"],
)
def test_G12_the_monitor_grades_the_workspace_file_whatever_a_member_reported(
    brain: Path, workspace: Path, text: str, expected: str, reported
) -> None:
    """Passes when the file contains the value, fails when it does not — the member's word aside.

    A member reporting a matching value against a file that lacks it fails; a member reporting
    nothing, or something else, against a file that contains it passes.
    """
    (workspace / TARGET).write_text(text, encoding="utf-8")
    context, _state, _seat, results = drive(brain, workspace, reported=(reported,))
    verdict = journalled_verdict(context)
    show(f"file={text!r} member={reported!r}", f"{grade(verdict)} ({results[-1].wave_status})")

    assert results[-1].wave_status == WAVE_COMPLETE
    assert grade(verdict) == expected
    assert committed_values(context)[EXPECTATION_ID] == text


@pytest.mark.parametrize("reported", [None, VALUE], ids=["none", "matching"])
def test_G12_a_missing_file_fails_and_a_members_matching_value_is_deleted(
    brain: Path, workspace: Path, reported
) -> None:
    """F4: the id ends the fill absent from the committed `expectation_values`."""
    assert not (workspace / TARGET).exists()
    context, _state, _seat, _results = drive(brain, workspace, reported=(reported,))
    verdict = journalled_verdict(context)
    values = committed_values(context)
    show(f"missing file, member={reported!r}", f"{grade(verdict)}; committed {values}")

    assert grade(verdict) == "failed"
    assert EXPECTATION_ID not in values


@pytest.mark.parametrize("reported", [None, VALUE], ids=["none", "matching"])
@pytest.mark.parametrize("via", ["file-link", "directory-link"])
def test_G12_a_path_whose_realpath_leaves_the_workspace_fails_and_its_target_is_not_read(
    brain: Path, workspace: Path, tmp_path: Path, monkeypatch, via: str, reported
) -> None:
    """A symlink out of the workspace: the sentinel behind it would pass if it were read.

    The gate's path arm is lexical and resolves no symlink (`brain/nodes/basal_ganglia/NODE.md`),
    so these paths reach the wave; the confinement is the read's own floor. The sentinel carries
    the value, so a fill that followed the link would pass the predicate — and, with a member
    reporting the value, the member's word would pass it too unless the fill deletes it (F4).
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "secret.txt"
    sentinel.write_text(f"sentinel: {VALUE}\n", encoding="utf-8")
    if via == "file-link":
        (workspace / "link.txt").symlink_to(sentinel)
        path = "link.txt"
    else:
        (workspace / "linked").symlink_to(outside, target_is_directory=True)
        path = "linked/secret.txt"

    opened: list[Path] = []
    original_open = Path.open

    def recording_open(self, *args, **kwargs):
        opened.append(Path(self).resolve())
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", recording_open)
    context, _state, _seat, results = drive(brain, workspace, path=path, reported=(reported,))
    monkeypatch.setattr(Path, "open", original_open)
    verdict = journalled_verdict(context)
    values = committed_values(context)
    show(f"{via} {path} member={reported!r}", f"{grade(verdict)}; committed {values}")

    assert results[-1].wave_status == WAVE_COMPLETE, "the gate did not veto the unit"
    assert grade(verdict) == "failed"
    assert EXPECTATION_ID not in values
    assert sentinel.resolve() not in opened, "the sentinel behind the link was never opened"


def test_G12_a_replayed_tick_re_reads_the_file(brain: Path, workspace: Path) -> None:
    """The workspace is re-observed, never re-trusted (`src/protean/runtime/cycle.py`, `run_wave`).

    The wave's tick runs against a file that lacks the value and fails. The file is then written
    with the value and the same tick is replayed from the checkpoint before it: every member is
    journalled, so the wave restores whole and no model is called — and the grade moves, because
    the fill read the clone again rather than anything the first pass recorded.
    """
    file = workspace / TARGET
    file.write_text("not yet\n", encoding="utf-8")
    context, state, seat = open_run(brain, workspace, path=TARGET, reported=(VALUE,))
    state.tick += 1
    run_tick(context, state)
    before = state.model_copy(deep=True)
    state.tick += 1
    run_tick(context, state)
    first = grade(journalled_verdict(context))
    dispatched = dispatches(seat)

    file.write_text(f"now {VALUE}\n", encoding="utf-8")
    replayed = before.model_copy(deep=True)
    replayed.tick += 1
    result = run_tick(context, replayed, replay=True)
    second = grade(journalled_verdict(context))
    show("first pass / replay", f"{first} / {second}; wave restored={result.wave_restored}")

    assert first == "failed"
    assert result.wave_restored is True
    assert dispatches(seat) == dispatched, "the replay called no model for the wave"
    assert second == "passed"
    assert committed_values(context)[EXPECTATION_ID] == f"now {VALUE}\n"


def test_G12_the_committed_value_is_the_files_text_as_read(brain: Path, workspace: Path) -> None:
    """`latest.dispatch.expectation_values[id]` is the file's text, byte for byte, not a member's."""
    text = f"line one\r\nline two — {VALUE}\n\ttabbed\n"
    (workspace / TARGET).write_bytes(text.encode("utf-8"))
    context, state, _seat, _results = drive(brain, workspace, reported=(UNRELATED,))
    values = committed_values(context)
    show("committed", repr(values[EXPECTATION_ID]))

    assert values[EXPECTATION_ID] == (workspace / TARGET).read_bytes().decode("utf-8")
    assert state.latest.dispatch is not None
    assert state.latest.dispatch.expectation_values[EXPECTATION_ID] == text


def test_G12_a_wave_conflicted_on_the_id_stays_conflicted_and_grades_nothing(
    brain: Path, workspace: Path
) -> None:
    """`merge_wave()` is byte-unchanged: two members disagreeing on the id conflict the wave.

    The file contains the value, so a fill that resolved the disagreement would pass the
    predicate; the wave stays `conflicted` and the monitor grades nothing against it.
    """
    (workspace / TARGET).write_text(f"{VALUE}\n", encoding="utf-8")
    context, _state, _seat, results = drive(brain, workspace, reported=(VALUE, UNRELATED))
    verdict = journalled_verdict(context)
    show("wave status / grade", f"{results[-1].wave_status} / {grade(verdict)}")

    assert results[-1].wave_status == WAVE_CONFLICTED
    assert grade(verdict) == "ungraded"
    assert verdict.passed_predicate_ids == [] and verdict.failed_predicate_ids == []


def _member_reported_ungradeable(context) -> int:
    """The report's count under A.2's semantics, recomputed off the journal's raw records.

    A `file_contains` predicate whose members reported no `str` value for its id counts once per
    tick with a wave — derived here from the dispatch envelopes the wave journalled, never from
    `report.py`, so the report is checked against a second reading and not against itself.
    """
    total = 0
    for tick in context.paths.journal_ticks():
        reported: dict[str, object] = {}
        waved = False
        for record in entries_of(context, tick):
            if record.node is not NodeName.CORTEX or record.envelope is None:
                continue
            if record.tier is not CallType.DISPATCH or not record.is_call():
                continue
            waved = True
            output = json.loads(record.envelope.result)
            for key, value in output.get("expectation_values", {}).items():
                reported.setdefault(key, value)
        if waved and not isinstance(reported.get(EXPECTATION_ID), str):
            total += 1
    return total


@pytest.mark.parametrize(
    "setup,reported,expected",
    [
        ("contains", None, "passed"),
        ("contains", VALUE, "passed"),
        ("lacks", VALUE, "failed"),
        ("lacks", None, "failed"),
        ("missing", VALUE, "failed"),
        ("outside", VALUE, "failed"),
    ],
    ids=[
        "contains-none", "contains-matching", "lacks-matching", "lacks-none",
        "missing-matching", "outside-matching",
    ],
)
def test_G12_the_reports_ungradeable_count_keeps_member_semantics_while_the_verdict_grades(
    brain: Path, workspace: Path, tmp_path: Path, setup: str, reported, expected: str
) -> None:
    """F14, F30, F32 and R26: the report is code-unchanged and its count a named limit.

    `report.tick_summaries()` re-merges the members' journalled envelopes and never sees the fill,
    so `ungradeable_count` counts a `FILE_CONTAINS` whose members reported no value — over-reporting
    where the fill graded the clone — while the journalled `MonitorVerdict` carries the grade.
    """
    path = TARGET
    if setup == "contains":
        (workspace / TARGET).write_text(f"{VALUE}\n", encoding="utf-8")
    elif setup == "lacks":
        (workspace / TARGET).write_text("no\n", encoding="utf-8")
    elif setup == "outside":
        sentinel = tmp_path / "sentinel.txt"
        sentinel.write_text(f"{VALUE}\n", encoding="utf-8")
        (workspace / "link.txt").symlink_to(sentinel)
        path = "link.txt"
    context, _state, _seat, _results = drive(brain, workspace, path=path, reported=(reported,))
    paths = context.paths
    counted = report_module.ungradeable_count(
        report_module.committed_units(paths), report_module.tick_summaries(paths)
    )
    recomputed = _member_reported_ungradeable(context)
    verdict = journalled_verdict(context)
    show(
        f"{setup} member={reported!r}",
        f"ungradeable_count={counted} (member-reported recompute {recomputed}); "
        f"verdict {grade(verdict)}",
    )

    assert counted == recomputed
    assert counted == (0 if isinstance(reported, str) else 1)
    assert grade(verdict) == expected


# --------------------------------------------------------------------------------------
# The helper on its own: the confinement and the no-workspace rule, without the gate in front
# --------------------------------------------------------------------------------------


def _merged(values: dict) -> ExecutorSummary:
    return ExecutorSummary(tick=1, unit_id=UNIT_ID, narrative="-", expectation_values=values)


@pytest.mark.parametrize("spelling", ["dotdot", "absolute", "symlink"])
def test_G12_the_fill_reads_nothing_outside_the_workspace_realpath_however_the_path_is_spelled(
    workspace: Path, tmp_path: Path, spelling: str
) -> None:
    """The gate vetoes `..` and an absolute path before a wave runs; the fill refuses them too.

    Called directly, the helper deletes a member's matching value and writes none for each
    spelling that leaves the workspace — the confinement is the read's own floor, not the gate's.
    """
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text(f"{VALUE}\n", encoding="utf-8")
    path = {
        "dotdot": f"../{sentinel.name}",
        "absolute": str(sentinel),
        "symlink": "link.txt",
    }[spelling]
    if spelling == "symlink":
        (workspace / "link.txt").symlink_to(sentinel)
    filled = observations.fill_file_contains(
        _merged({EXPECTATION_ID: VALUE}), [_unit("g-1", path)], str(workspace)
    )
    show(f"{spelling} {path}", filled.expectation_values)
    assert EXPECTATION_ID not in filled.expectation_values


def test_G12_a_tick_with_no_workspace_path_fills_nothing(workspace: Path) -> None:
    """No workspace path, no read: the summary comes back as it went in."""
    (workspace / TARGET).write_text(f"{VALUE}\n", encoding="utf-8")
    merged = _merged({EXPECTATION_ID: UNRELATED, "other": "kept"})
    filled = observations.fill_file_contains(merged, [_unit("g-1", TARGET)], "")
    show("no workspace", filled.expectation_values)
    assert filled == merged


# --------------------------------------------------------------------------------------
# G16 — a file over `FILE_CONTAINS_BOUND` is refused, never truncated (E64)
# --------------------------------------------------------------------------------------

#: A file whose text contains the value; each G16 case lowers the bound around its byte size.
BOUNDED_TEXT = f"{VALUE}\n"


@pytest.mark.parametrize("reported", [None, VALUE], ids=["none", "matching"])
def test_G16_a_file_one_byte_over_the_bound_fails_and_a_members_matching_value_is_deleted(
    brain: Path, workspace: Path, monkeypatch, reported
) -> None:
    """Handled exactly as a missing file: the id ends the fill absent, whatever a member said.

    The file contains the value, so a fill that read it — whole or truncated at the bound —
    would pass the predicate; the refusal fails it instead.
    """
    (workspace / TARGET).write_text(BOUNDED_TEXT, encoding="utf-8")
    size = (workspace / TARGET).stat().st_size
    monkeypatch.setattr(observations, "FILE_CONTAINS_BOUND", size - 1)
    context, _state, _seat, results = drive(brain, workspace, reported=(reported,))
    verdict = journalled_verdict(context)
    values = committed_values(context)
    show(
        f"size={size} bound={size - 1} member={reported!r}",
        f"{grade(verdict)}; committed {values}",
        tag="G16",
    )

    assert results[-1].wave_status == WAVE_COMPLETE
    assert grade(verdict) == "failed"
    assert EXPECTATION_ID not in values


def test_G16_a_file_exactly_at_the_bound_is_read_whole_and_passes(
    brain: Path, workspace: Path, monkeypatch
) -> None:
    """At the bound the file is read whole: its committed value is the file's entire text."""
    (workspace / TARGET).write_text(BOUNDED_TEXT, encoding="utf-8")
    size = (workspace / TARGET).stat().st_size
    monkeypatch.setattr(observations, "FILE_CONTAINS_BOUND", size)
    context, _state, _seat, _results = drive(brain, workspace, reported=(UNRELATED,))
    verdict = journalled_verdict(context)
    values = committed_values(context)
    show(f"size={size} bound={size}", f"{grade(verdict)}; committed {values}", tag="G16")

    assert grade(verdict) == "passed"
    assert values[EXPECTATION_ID] == BOUNDED_TEXT


def test_G16_the_size_is_measured_before_any_read(workspace: Path, monkeypatch) -> None:
    """With the bound lowered to a few bytes, the over-bound file is never read at all.

    The same call under the real bound reads the file and writes its text, so the recorder sees
    reads and the file would read cleanly; under the lowered bound it records none.
    """
    target = workspace / TARGET
    target.write_text(BOUNDED_TEXT, encoding="utf-8")
    reads: list[Path] = []
    original_read_bytes = Path.read_bytes

    def recording_read_bytes(self):
        reads.append(Path(self).resolve())
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", recording_read_bytes)
    unbounded = observations.fill_file_contains(
        _merged({EXPECTATION_ID: VALUE}), [_unit("g-1", TARGET)], str(workspace)
    )
    read_under_real_bound = target.resolve() in reads

    reads.clear()
    monkeypatch.setattr(observations, "FILE_CONTAINS_BOUND", 8)
    bounded = observations.fill_file_contains(
        _merged({EXPECTATION_ID: VALUE}), [_unit("g-1", TARGET)], str(workspace)
    )
    monkeypatch.setattr(Path, "read_bytes", original_read_bytes)
    show(
        f"size={target.stat().st_size} bound=8",
        f"reads={reads}; filled {bounded.expectation_values}",
        tag="G16",
    )

    assert read_under_real_bound
    assert unbounded.expectation_values[EXPECTATION_ID] == BOUNDED_TEXT
    assert target.stat().st_size > 8
    assert reads == [], "the over-bound file was never read"
    assert EXPECTATION_ID not in bounded.expectation_values
