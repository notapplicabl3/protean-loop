"""G4 and G5 — what a seat is sent: no file body, admitted items once, retrieval without text.

`the build specification (not in this mirror)` § Deliverable 2 (with § Resolutions X43, audit R3-F1 (a)),
§ Scaffold clause items 2(c)–2(e), and DoD rows G4 and G5. `projections.workspace(state)` keeps
`latest` as a deep copy of `state.latest` with three bodies withheld on the seat path:

1. **`latest.dispatch`** — each id present in `expectation_values` that the summary's unit
   currently marks `FILE_CONTAINS`, or no longer declares under any kind, becomes a record of the
   text's UTF-8 byte length and SHA-256 digest that states the text was withheld; an absent id
   stays absent; a value under an id the unit declares under another kind passes byte-unchanged.
2. **`latest.thalamus`** — each admitted item's `summary` becomes its own id.
3. **`latest.hippocampus`** — every candidate's `text` is `None`.

`workspace.admitted` stays `state.latest.thalamus`, so the admitted bodies ride exactly once, and
committed state keeps every body. Every case is named for its row, so `-k G4` and `-k G5` select
them.

**The end-to-end case is scripted over a real workspace**, in the form of
`tests/runtime/test_file_contains.py`: a manager that dispatches a wave for one `FILE_CONTAINS`
unit on every tick, a member that reports nothing, and a workspace file holding a sentinel.

**Zero model calls.** Every answer is a scripted responder behind `stubs.StubSeat`; nothing spawns
a process.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from protean.cortex.bodies import request_on_stdin, request_payload
from protean.nodes import thalamus
from protean.runtime import observations, projections
from protean.runtime.cycle import apply_manager, run_tick
from protean.runtime.engine import build_context, new_state
from protean.runtime.projections import SHA256_KEY, UTF8_BYTES_KEY, WITHHELD_KEY
from protean.runtime.seat import SeatLayer, SeatSelection
from protean.state.brain_state import BrainState
from protean.state.enums import CallType, ExpectationKind, Tier
from protean.state.outputs import AdmittedContext, AdmittedItem, RetrievalSet, RetrievedEpisode
from protean.state.primitives import Expectation, GoalItem, WorkUnit
from protean.state.seats import DirectorDirection, ExecutorSummary, ManagerPlan, WaveMember
from protean.state.semantic import SemanticChunk
from protean.state.workspace import DirectorRequest, LatestOutputs, ManagerRequest
from tests.conftest import tagged_show
from tests.runtime import stubs

TASK = "task-seat-workspace"
GOAL_ID = "g-1"
GOAL = "write the answer into out.txt"
UNIT_ID = "u-file"
TICK = 1

#: The `FILE_CONTAINS` id the fill writes from the sentinel file.
FILE_ID = "e-contains"
#: A second `FILE_CONTAINS` id whose file does not exist, so the fill leaves it absent.
ABSENT_ID = "e-missing"
#: An id the unit declares under another kind; the member reported a value for it.
OTHER_ID = "e-exists"

TARGET = "out.txt"
MISSING = "never-written.txt"

#: The substring the predicate asks the file for. It rides the unit's own arguments to a seat,
#: so it is never the sentinel.
VALUE = "the answer"

#: The body no seat may receive. Non-ASCII on purpose, so the UTF-8 byte length and the character
#: count differ and a record that counted characters would fail the length clause.
SENTINEL = "SENTINEL-4f9c2e — fichier réservé ✓"
FILE_TEXT = f"before {VALUE} after\n{SENTINEL}\n"

#: What a member reported under `OTHER_ID` — its own report, which passes byte-unchanged.
OTHER_REPORT = "member report: out.txt exists — ünchanged"

show = tagged_show("G4")


def _goal() -> GoalItem:
    return GoalItem(id=GOAL_ID, text=GOAL, opened_at_tick=0, last_progress_tick=0)


def _unit(*expected: Expectation, goal_id: str = GOAL_ID) -> WorkUnit:
    return WorkUnit(id=UNIT_ID, goal_id=goal_id, intent="write the answer", expected=list(expected))


def _contains(expectation_id: str, path: str) -> Expectation:
    return Expectation(
        id=expectation_id,
        kind=ExpectationKind.FILE_CONTAINS,
        arguments={"path": path, "value": VALUE},
    )


def _exists(expectation_id: str) -> Expectation:
    return Expectation(
        id=expectation_id, kind=ExpectationKind.FILE_EXISTS, arguments={"path": TARGET}
    )


def _record_of(text: str) -> dict:
    """The record G4 names, computed here from the text and never through the projection."""
    data = text.encode("utf-8")
    return {
        WITHHELD_KEY: True,
        UTF8_BYTES_KEY: len(data),
        SHA256_KEY: hashlib.sha256(data).hexdigest(),
    }


def _serialized(request) -> str:
    """The request as the port puts it on the seat's stdin (`protean.cortex.bodies`)."""
    return request_on_stdin(request_payload(request))


# --------------------------------------------------------------------------------------
# G4 — the fixture state: one unit, its `FILE_CONTAINS` id filled from a sentinel file
# --------------------------------------------------------------------------------------


@pytest.fixture()
def filled(workspace: Path) -> BrainState:
    """A committed state whose `latest.dispatch` the real fill wrote from the workspace file.

    The unit declares two `FILE_CONTAINS` predicates — one on the sentinel file, one on a file
    that does not exist — and one `FILE_EXISTS` predicate the member reported a value for.
    """
    (workspace / TARGET).write_text(FILE_TEXT, encoding="utf-8")
    unit = _unit(_contains(FILE_ID, TARGET), _contains(ABSENT_ID, MISSING), _exists(OTHER_ID))
    merged = ExecutorSummary(
        tick=TICK,
        unit_id=UNIT_ID,
        narrative="wrote out.txt",
        expectation_values={OTHER_ID: OTHER_REPORT, ABSENT_ID: VALUE},
    )
    summary = observations.fill_file_contains(merged, [unit], str(workspace))
    state = BrainState(
        task_id=TASK,
        tick=TICK + 1,
        goals=[_goal()],
        units=[unit],
        latest=LatestOutputs(dispatch=summary),
    )
    assert state.latest.dispatch is not None
    assert state.latest.dispatch.expectation_values[FILE_ID] == FILE_TEXT, "the fill read it"
    assert ABSENT_ID not in state.latest.dispatch.expectation_values, "the fill left it absent"
    return state


def _projected_values(state: BrainState) -> dict:
    dispatch = projections.workspace(state).latest.dispatch
    assert dispatch is not None, "the slot is never dropped"
    return dispatch.expectation_values


def _unreduced(state: BrainState):
    """The pre-build workspace — `latest` handed over whole — as the control for a zero count."""
    return projections.workspace(state).model_copy(
        update={"latest": state.latest.model_copy(deep=True)}
    )


def test_G4_the_file_body_reaches_a_seat_as_a_record_of_its_size_and_digest(filled):
    """The record's byte length, SHA-256 digest and withheld key; nothing else, and no text."""
    record = _projected_values(filled)[FILE_ID]
    show("record at the FILE_CONTAINS id", record)

    assert isinstance(record, dict)
    assert record[UTF8_BYTES_KEY] == len(FILE_TEXT.encode("utf-8"))
    assert record[UTF8_BYTES_KEY] != len(FILE_TEXT), "bytes, not characters"
    assert record[SHA256_KEY] == hashlib.sha256(FILE_TEXT.encode("utf-8")).hexdigest()
    assert record[WITHHELD_KEY] is True
    assert record == _record_of(FILE_TEXT)


def test_G4_the_sentinel_appears_zero_times_in_a_serialized_director_and_manager_request(filled):
    """Both seats' requests, built from the one workspace and serialized as the port sends them."""
    workspace = projections.workspace(filled)
    director = _serialized(DirectorRequest(workspace=workspace))
    manager = _serialized(ManagerRequest(workspace=workspace, unit_id=UNIT_ID))
    show("sentinel count director / manager", (director.count(SENTINEL), manager.count(SENTINEL)))

    assert director.count(SENTINEL) == 0
    assert manager.count(SENTINEL) == 0
    control = _serialized(ManagerRequest(workspace=_unreduced(filled)))
    assert control.count(SENTINEL) == 1, "the control: the unreduced workspace carries it"


def test_G4_state_is_unchanged_by_the_projection_and_its_committed_value_is_still_the_text(
    filled,
):
    before = filled.model_copy(deep=True)
    projections.workspace(filled)
    show("committed value after the projection", filled.latest.dispatch.expectation_values[FILE_ID])

    assert filled == before
    assert filled.latest.dispatch.expectation_values[FILE_ID] == FILE_TEXT


def test_G4_an_id_the_fill_left_absent_stays_absent(filled):
    values = _projected_values(filled)
    show("projected ids", sorted(values))
    assert ABSENT_ID not in values
    assert set(values) == set(filled.latest.dispatch.expectation_values)


def test_G4_a_value_under_an_id_declared_under_another_kind_is_byte_unchanged(filled):
    """A member's own report under a `FILE_EXISTS` id passes as committed, byte for byte."""
    committed = filled.latest.dispatch.expectation_values[OTHER_ID]
    projected = _projected_values(filled)[OTHER_ID]
    show("committed / projected", (committed, projected))

    assert projected == committed == OTHER_REPORT
    assert json.dumps(projected, ensure_ascii=False) == json.dumps(committed, ensure_ascii=False)
    manager = _serialized(ManagerRequest(workspace=projections.workspace(filled)))
    assert manager.count(json.dumps(OTHER_REPORT, ensure_ascii=False)) == 1


@pytest.mark.parametrize("revision", ["dropped", "replaced-by-another-kind"])
def test_G4_a_stale_id_the_revised_unit_no_longer_declares_is_withheld_as_a_record(
    filled, revision: str
):
    """R3-F1 (a), X43: the plan-apply path revises the unit's `expected` list; no wave follows.

    `apply_manager` merges the manager's revised unit by id, so `state.units` no longer declares
    `FILE_ID` under any kind while `latest.dispatch` still carries the fill's text under it. The
    projection withholds the stale id as a record; the other kind's value still passes.
    """
    kept = [_exists(OTHER_ID)]
    if revision == "replaced-by-another-kind":
        kept.append(_exists("e-exists-instead"))
    plan = ManagerPlan(tick=filled.tick, units=[_unit(*kept)])
    apply_manager(filled, plan, SeatSelection(tier=Tier.MANAGER, unit_id=UNIT_ID))
    declared = {expectation.id for expectation in filled.units[0].expected}
    committed = filled.latest.dispatch.expectation_values
    values = _projected_values(filled)
    show(f"{revision}: declared {sorted(declared)}", values[FILE_ID])

    assert filled.units[0].revision == 1, "the unit was revised through the plan-apply path"
    assert FILE_ID not in declared
    assert committed[FILE_ID] == FILE_TEXT, "no new wave replaced the committed text"
    assert values[FILE_ID] == _record_of(FILE_TEXT)
    assert values[OTHER_ID] == OTHER_REPORT
    assert _serialized(ManagerRequest(workspace=projections.workspace(filled))).count(
        SENTINEL
    ) == 0


def test_G4_a_non_string_value_under_a_withheld_id_is_the_record_of_its_json_text(filled):
    """A stale id whose committed value is not a string still rides as a record, never as itself.

    The record's text is the value's sorted, compact JSON (the builder's ledger's reading of "the
    text" for a non-string value), so its size and digest are computed from that here.
    """
    stale = {"lines": [SENTINEL, 2], "ok": True}
    filled.latest.dispatch = filled.latest.dispatch.model_copy(
        update={"expectation_values": {**filled.latest.dispatch.expectation_values, "e-old": stale}}
    )
    text = json.dumps(stale, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    values = _projected_values(filled)
    show("non-string stale value's record", values["e-old"])

    assert values["e-old"] == _record_of(text)
    assert _serialized(ManagerRequest(workspace=projections.workspace(filled))).count(
        SENTINEL
    ) == 0


# --------------------------------------------------------------------------------------
# G4 — end to end: a scripted two-tick run over a real workspace holding the sentinel file
# --------------------------------------------------------------------------------------


def _planner(request) -> ManagerPlan:
    """Plans the one unit and dispatches its wave on every pass."""
    return ManagerPlan(
        tick=request.workspace.tick,
        units=[_unit(_contains(FILE_ID, TARGET), goal_id=request.workspace.goals[0].id)],
        wave=[WaveMember(kind="writer", unit_id=UNIT_ID, admitted_ref="admitted")],
    )


def _member(member: WaveMember) -> ExecutorSummary:
    """A member that reports nothing: the value the monitor grades is the fill's read."""
    return ExecutorSummary(tick=0, unit_id=member.unit_id, narrative="wrote out.txt")


def test_G4_end_to_end_tick_2s_seat_request_carries_the_record_and_never_the_sentinel(
    brain: Path, workspace: Path
):
    """Tick 1 dispatches the wave and commits the fill; tick 2's manager request is the reduced one.

    The unit is on the stack before tick 1 (the fixture state's `units`), so the manager's first
    pass — no escalation, the router's fall-through — dispatches its wave at once.
    """
    (workspace / TARGET).write_text(FILE_TEXT, encoding="utf-8")
    seat = stubs.StubSeat(
        responder=stubs.member_keyed(
            {
                str(Tier.MANAGER): _planner,
                str(CallType.DISPATCH): _member,
                str(Tier.DIRECTOR): lambda request: {"tick": request.workspace.tick},
            }
        )
    )
    router = stubs.StubRouter(
        rule=stubs.always(SeatSelection(tier=Tier.MANAGER, unit_id=UNIT_ID))
    )
    context = build_context(
        brain, TASK, SeatLayer(router=router, port=seat), workspace_path=str(workspace)
    )
    state = new_state(TASK, GOAL, context)
    state.units = [_unit(_contains(FILE_ID, TARGET), goal_id=state.goals[0].id)]

    state.tick += 1
    run_tick(context, state)
    checkpoint = stubs.committed_state(context.paths)["state"]
    committed = checkpoint["latest"]["dispatch"]["expectation_values"]

    state.tick += 1
    run_tick(context, state)
    manager_requests = {
        request.workspace.tick: request
        for tier, request in seat.calls
        if tier == str(Tier.MANAGER)
    }
    request = manager_requests[2]
    serialized = _serialized(request)
    show(
        "tick-1 checkpoint / tick-2 request",
        (checkpoint["tick"], SENTINEL in committed[FILE_ID], serialized.count(SENTINEL)),
    )

    assert checkpoint["tick"] == 1
    assert committed[FILE_ID] == FILE_TEXT and SENTINEL in committed[FILE_ID]
    assert request.workspace.latest.dispatch.expectation_values[FILE_ID] == _record_of(FILE_TEXT)
    assert serialized.count(SENTINEL) == 0


# --------------------------------------------------------------------------------------
# G5 — admitted items ride once; retrieval reaches a seat without text
# --------------------------------------------------------------------------------------

A_SENTINEL = "SENTINEL-A-91d0c4"
B_SENTINEL = "SENTINEL-B-3e57fa"
A_CHUNK = SemanticChunk.of(
    store="docs", source="docs", text=f"Chunk A: {A_SENTINEL}.", manifest_revision="rev-test"
)
B_CHUNK = SemanticChunk.of(
    store="docs", source="docs", text=f"Chunk B: {B_SENTINEL}.", manifest_revision="rev-test"
)
#: An episode candidate beside the chunks: no text, and a summary that is already its id.
EPISODE_ID = "episode:task-old:3"
#: The floor the fixture's thalamus weights set: A and the episode clear it, B does not.
FLOOR = 0.5


@pytest.fixture()
def retrieved() -> BrainState:
    """A committed state whose hippocampus retrieved A and B, and whose thalamus admitted A only.

    The admission is the real thalamus's `run()` over the retrieval, with a relevance floor that
    excludes B, so the slot's `summary` for A is A's text exactly as the node writes it.
    """
    retrieval = RetrievalSet(
        tick=TICK,
        candidates=[
            RetrievedEpisode(episode_id=A_CHUNK.chunk_id, score=0.9, text=A_CHUNK.text),
            RetrievedEpisode(episode_id=B_CHUNK.chunk_id, score=0.2, text=B_CHUNK.text),
            RetrievedEpisode(episode_id=EPISODE_ID, score=0.7),
        ],
    )
    state = BrainState(task_id=TASK, tick=TICK, goals=[_goal()], units=[_unit()])
    state.latest = LatestOutputs(hippocampus=retrieval)
    admitted = thalamus.run(
        projections.thalamus_input(state, {thalamus.WEIGHT_MIN_RELEVANCE: FLOOR}, retrieval)
    )
    state.latest = LatestOutputs(hippocampus=retrieval, thalamus=admitted)
    assert [item.episode_id for item in admitted.admitted] == [A_CHUNK.chunk_id, EPISODE_ID]
    assert [item.episode_id for item in admitted.excluded] == [B_CHUNK.chunk_id]
    assert admitted.admitted[0].summary == A_CHUNK.text
    return state


def test_G5_every_retrieval_candidate_reaches_a_seat_without_text(retrieved):
    committed = retrieved.latest.hippocampus.candidates
    projected = projections.workspace(retrieved).latest.hippocampus.candidates
    show("projected candidates", [(c.episode_id, c.score, c.text) for c in projected], tag="G5")

    assert [candidate.text for candidate in projected] == [None] * len(committed)
    assert [(c.episode_id, c.score) for c in projected] == [
        (c.episode_id, c.score) for c in committed
    ]


def test_G5_every_admitted_summary_in_latest_thalamus_is_the_items_own_id(retrieved):
    committed = retrieved.latest.thalamus
    projected = projections.workspace(retrieved).latest.thalamus
    show("projected admitted", [(i.admitted_id, i.summary) for i in projected.admitted], tag="G5")

    assert [item.summary for item in projected.admitted] == [
        item.episode_id for item in committed.admitted
    ]
    assert [(i.admitted_id, i.episode_id, i.score) for i in projected.admitted] == [
        (i.admitted_id, i.episode_id, i.score) for i in committed.admitted
    ]
    assert projected.excluded == committed.excluded
    assert projected.tick == committed.tick


def test_G5_an_admitted_item_without_an_episode_id_carries_its_admitted_id(retrieved):
    """The "else" of reduction 2: an item with no `episode_id` is named by its `admitted_id`."""
    item = AdmittedItem(admitted_id="admitted:orphan", summary=f"orphan {A_SENTINEL}", score=0.4)
    retrieved.latest = retrieved.latest.model_copy(
        update={"thalamus": AdmittedContext(tick=TICK, admitted=[item])}
    )
    projected = projections.workspace(retrieved).latest.thalamus.admitted
    show("orphan's projected summary", projected[0].summary, tag="G5")
    assert projected[0].summary == "admitted:orphan"
    assert projected[0].episode_id is None


def test_G5_workspace_admitted_is_the_committed_thalamus_slot(retrieved):
    workspace = projections.workspace(retrieved)
    show("admitted summaries", [item.summary for item in workspace.admitted.admitted], tag="G5")
    assert workspace.admitted == retrieved.latest.thalamus
    assert workspace.admitted.admitted[0].summary == A_CHUNK.text


def test_G5_the_manager_request_carries_a_once_b_never_and_bs_id(retrieved):
    serialized = _serialized(ManagerRequest(workspace=projections.workspace(retrieved)))
    counts = (
        serialized.count(A_SENTINEL),
        serialized.count(B_SENTINEL),
        serialized.count(B_CHUNK.chunk_id),
    )
    show("A sentinel / B sentinel / B id", counts, tag="G5")

    assert serialized.count(A_SENTINEL) == 1
    assert serialized.count(B_SENTINEL) == 0
    assert serialized.count(B_CHUNK.chunk_id) >= 1


def test_G5_state_is_unchanged_by_the_projection(retrieved):
    before = retrieved.model_copy(deep=True)
    projections.workspace(retrieved)
    show("committed A summary", retrieved.latest.thalamus.admitted[0].summary, tag="G5")

    assert retrieved == before
    assert retrieved.latest.hippocampus.candidates[1].text == B_CHUNK.text


def test_G5_no_latest_slot_is_dropped_and_the_other_slots_pass_as_committed(retrieved, filled):
    """Every slot present on the committed state is present on the seat's; the rest are equal."""
    retrieved.latest = retrieved.latest.model_copy(
        update={
            "dispatch": filled.latest.dispatch,
            "manager": ManagerPlan(tick=TICK, units=filled.units),
            "director": DirectorDirection(tick=TICK),
        }
    )
    retrieved.units = filled.units
    projected = projections.workspace(retrieved).latest
    reduced = {"dispatch", "thalamus", "hippocampus"}
    present = {name for name in LatestOutputs.model_fields if getattr(retrieved.latest, name)}
    show("present slots", sorted(present), tag="G5")

    assert present >= reduced | {"manager", "director"}
    for name in LatestOutputs.model_fields:
        assert (getattr(projected, name) is None) == (getattr(retrieved.latest, name) is None)
        if name not in reduced:
            assert getattr(projected, name) == getattr(retrieved.latest, name)
