"""Contract 4's two amendments: the call-bearing raiser's widened id, and the answer path.

`the build specification (not in this mirror)` § Scaffold clause item 2, contract 4 (folded: S-A52,
folded: S-A72, folded: S-A74, folded: S-A90) and § Deliverable 4's last paragraph.

**The failure this fixes, proved rather than described.** `Raiser` is a closed set and a call
type is a raiser **every** outer node shares, so the hippocampus's think and the thalamus's think
in one tick collapse onto one filename under the three-part id — and two members of one wave
collapse onto another. The id widens to `(task, tick, node, raiser, call#[, member#])` for a
call-bearing raiser **only**: a node or the runtime raising on its own account has no `call#` to
put there and keeps the three-part id, so every component is defined for every raiser.

**And the answer has to land.** `resolution_target()` reads the `node` component **out of the
id**, because the id is the only thing the answer path is given — a `node` that is not in it is a
`node` nothing downstream can recover. The file's shape beyond the front matter, and the answer
path itself, are unchanged.

**Zero model calls.** Every answer is `fixtures/calls/two_thinks.yaml` through the scripted
transport; nothing is spawned and no kind process exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protean import config
from protean.brain.jsonl import read_lines
from protean.cortex.adapters import ScriptedSeat, SeatDesk
from protean.cortex.calls import CallDesks
from protean.cortex.ladder import LadderWeights
from protean.cortex.router import LadderRouter
from protean.cortex.scripts import load_script
from protean.mailbox.files import build as build_mailbox
from protean.runtime.cycle import SEAT_CALL_NUMBER, WAVE_CALL_NUMBER, run_tick
from protean.runtime.engine import build_context, new_state, resume
from protean.runtime.interrupts import resolution_target
from protean.state.enums import CallType, NodeName, Raiser, Tier
from protean.state.interrupts import (
    ANSWER_HEADING,
    components_of,
    interrupt_id,
)
from protean.state.seat_calls import load_seat_calls
from protean.runtime.seat import SeatLayer

from tests.conftest import tagged_show
from tests.mailbox.conftest import committed_prediction_keys

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures" / "calls"

GOAL = "settle the ledger question"


show = tagged_show("W8-raisers")


def layer_for(brain: Path):
    script = load_script(FIXTURES / "two_thinks.yaml")
    desk = SeatDesk()
    seat = ScriptedSeat(script=script, desk=desk)
    return SeatLayer(
        router=LadderRouter(weights=LadderWeights.load(brain), on_tick=desk.open_tick),
        port=seat,
        sessions=desk.sessions,
        node_calls=CallDesks(port=seat, plan=script.calls),
    )


@pytest.fixture()
def raised(brain: Path, workspace: Path):
    """Two passes of `two_thinks` on a fixture brain root: two thinks, then the wave."""
    mailbox = build_mailbox(brain)
    context = build_context(
        brain, "task-raise", layer_for(brain), mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-raise", GOAL, context)
    results = []
    for _ in range(2):
        state.tick += 1
        results.append(run_tick(context, state))
    return context, state, results, mailbox


def open_ids(context) -> list[str]:
    return sorted(path.stem for path in (context.root / "mailbox" / "open").iterdir())


# --------------------------------------------------------------------------------------
# The widened id, and the two collisions it fixes
# --------------------------------------------------------------------------------------


def test_the_id_is_three_part_for_a_node_or_the_runtime_raising_on_its_own_account() -> None:
    """The rule's other half: every component defined for every raiser (contract 4)."""
    assert interrupt_id("t", 3, str(Raiser.THALAMUS)) == "t-t3-thalamus"
    assert interrupt_id("t", 3, str(Raiser.RUNTIME)) == "t-t3-runtime"
    assert components_of("t-t3-thalamus") == (None, "thalamus", None, None)
    with pytest.raises(ValueError):
        interrupt_id("t", 3, str(Raiser.THINK), node="thalamus")


def test_a_call_bearing_raiser_carries_the_node_and_the_call_components() -> None:
    identifier = interrupt_id(
        "t", 3, str(Raiser.DISPATCH), node=str(NodeName.CORTEX), call_number=2, member_number=1
    )
    show("a member's id", identifier)
    assert identifier == "t-t3-cortex-dispatch-c2-m1"
    assert components_of(identifier) == (str(NodeName.CORTEX), "dispatch", 2, 1)
    bare = interrupt_id("t", 3, str(Raiser.THINK), node="thalamus", call_number=1)
    assert bare == "t-t3-thalamus-think-c1"
    assert components_of(bare) == ("thalamus", "think", 1, None)


def test_a_task_id_that_holds_a_dash_still_reads_back() -> None:
    """Read from the right, because the task id is the one component that may hold a `-`."""
    identifier = interrupt_id(
        "task-2026-09-12", 4, str(Raiser.THINK), node="hippocampus", call_number=1
    )
    assert components_of(identifier) == ("hippocampus", "think", 1, None)
    assert components_of("task-2026-09-12-t4-runtime") == (None, "runtime", None, None)


def test_two_nodes_think_calls_in_one_pass_produce_two_filenames(raised) -> None:
    """The collision contract 4 exists to fix, on a real pass (folded: S-A90)."""
    context, _state, _results, _mailbox = raised
    ids = open_ids(context)
    show("mailbox/open/ after the two passes", ids)

    thinks = [
        item
        for item in ids
        if components_of(item)[1] == str(Raiser.THINK) and "-t1-" in item
    ]
    assert len(thinks) == 2, "one file per calling node on the pass, not one between them"
    assert {components_of(item)[0] for item in thinks} == {
        str(NodeName.HOMEOSTASIS),
        str(NodeName.HIPPOCAMPUS),
    }
    assert all(components_of(item)[2] == 1 for item in thinks), "each node's own `call# = 1`"
    # And the ids are replay-stable by construction: the same two calls on the next pass write
    # two more files rather than two more of the same.
    assert len([item for item in ids if components_of(item)[1] == str(Raiser.THINK)]) == 4


def test_the_front_matter_is_unchanged_but_for_the_id_and_the_raiser(raised) -> None:
    """"The file's shape beyond those fields, and the answer path, are unchanged."

    **Contract 4, on the one member, from the id inward** (audit row W13). The member's own
    `call#`/`member#` components were asserted by a second case that selected the same file off
    `raised` with the same comprehension; those three claims are the first block below, because
    the id and the front matter are the two halves of one amendment.
    """
    context, _state, _results, mailbox = raised
    member = next(
        item for item in open_ids(context) if components_of(item)[1] == str(Raiser.DISPATCH)
    )
    node, _raiser, call_number, member_number = components_of(member)
    show("the member's id components", (node, call_number, member_number))
    assert node == str(NodeName.CORTEX)
    assert call_number == WAVE_CALL_NUMBER and member_number == 1

    item = mailbox.read(member)
    show("front matter", {"id": item.id, "raised_by": str(item.raised_by), "kind": str(item.kind)})
    assert item.schema_version == config.MAILBOX_SCHEMA_VERSION == 2
    assert item.raised_by is Raiser.DISPATCH and item.id == member
    assert item.task == "task-raise" and item.tick == 2 and item.raised_at
    assert item.question == "which ledger did you mean?"
    body = (context.root / "mailbox" / "open" / f"{member}.md").read_text(encoding="utf-8")
    assert ANSWER_HEADING in body, "the answer path is where it was"


# --------------------------------------------------------------------------------------
# The answer path: `resolution_target()` reads the node out of the id
# --------------------------------------------------------------------------------------


def test_resolution_target_reads_the_calling_node_out_of_the_id(raised) -> None:
    context, _state, _results, _mailbox = raised
    for item in open_ids(context):
        node_component, raiser, _call, _member = components_of(item)
        folder, column = resolution_target(item)
        show(f"{raiser} resolves to", (str(folder), None if column is None else str(column)))
        if raiser == str(Raiser.THINK):
            assert str(folder) == node_component, "the answer reaches the node that asked"
            assert column is None, "a think mints no cortex prediction to name"
        else:
            assert folder is NodeName.CORTEX and column is CallType.DISPATCH


def test_an_answer_to_a_member_s_question_resumes_instead_of_crashing(
    brain: Path, workspace: Path, raised
) -> None:
    """The whole point of (b): `resume` delivers the answer rather than failing to resolve.

    **One resume, both destinations** (audit row W12). Contract 4's answer path was exercised by
    two cases that answered *every* open item and resumed identically, then read two different
    folders back: the member's answer lands on the cortex folder under the `dispatch` addressee
    and on a `ref` the wave actually committed, and each think's answer lands on the folder of
    the node that asked, with no tier — because `resolution_target()` reads the `node` component
    out of the id. Same end state, same `resume(...)`, both blocks verbatim.
    """
    context, _state, _results, mailbox = raised
    member = next(
        item for item in open_ids(context) if components_of(item)[1] == str(Raiser.DISPATCH)
    )
    for one in open_ids(context):
        path = context.root / "mailbox" / "open" / f"{one}.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                ANSWER_HEADING, f"{ANSWER_HEADING}\n\nthe primary ledger"
            ),
            encoding="utf-8",
        )

    outcome = resume(
        brain,
        layer_for(brain),
        mailbox=mailbox,
        workspace_path=str(workspace),
        max_ticks=1,
    )
    show("resumed terminal", outcome.terminal)
    records = [
        record
        for record in read_lines(context.paths.trace(str(NodeName.CORTEX)))
        if record.get("source") == "operator_answer"
    ]
    show("the member's operator_answer row", [record["ref"] for record in records])
    assert records, "the answer landed on the cortex folder, keyed to the resume pass"
    assert all(record["tier"] == str(CallType.DISPATCH) for record in records)
    # The `ref` names a prediction the wave actually committed, which is what makes the append
    # legal at all: `append_trace()` refuses an outcome whose `ref` names no committed key.
    keys = committed_prediction_keys(read_lines(context.paths.trace(str(NodeName.CORTEX))))
    assert all(record["ref"] in keys for record in records)

    # And each think's answer, on the folder of the node that asked rather than on the cortex's.
    for node in (NodeName.HOMEOSTASIS, NodeName.HIPPOCAMPUS):
        records = [
            record
            for record in read_lines(context.paths.trace(str(node)))
            if record.get("source") == "operator_answer"
        ]
        show(f"{node} operator_answer rows", [record["ref"] for record in records])
        assert len(records) == 1, "the answer reached the node that asked"
        assert records[0]["tier"] is None, "a think mints no cortex prediction"
