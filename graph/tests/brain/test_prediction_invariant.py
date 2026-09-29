"""M8's counting half — one prediction per `(folder, tier)` per tick in which that node ran.

`the build specification (not in this mirror)` § Deliverable 4: "**One prediction record per node folder per
tick in which that node ran**, and the cortex folder's records are keyed by tier — so a tick
that fires the planner writes a planner-tier record and no executor-tier one."

**The count is read off the committed files, not off the return value.** `TickResult.predictions`
is what the runtime *minted*; what the row claims is what the boundary commit *landed*, and the
two differ whenever a dedupe key collides — which is the replay case the same key exists for.

**The synthetic `stuck` prediction's own raise case is W3's**, where the ladder that produces it
lives. What is asserted here is the two halves this order owns: the runtime writes one
director-tier record per tick, and a second one is rejected.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from protean import config
from protean.brain.jsonl import read_lines
from protean.brain.trace import append_trace
from protean.state.enums import Tier
from tests.brain import factories
from tests.brain.conftest import advance, trace_path

DETERMINISTIC = [name for name in config.NODE_ORDER if name != config.CORTEX_NODE]


def _predictions(brain: Path, node: str) -> list[dict]:
    return [line for line in read_lines(trace_path(brain, node)) if line["kind"] == "prediction"]


@pytest.mark.parametrize("node", DETERMINISTIC)
def test_one_prediction_per_deterministic_folder_per_tick(started, brain: Path, node: str):
    """One record per folder per tick **in which it ran** — under A.1 a node whose cheap check
    declined (the gate on a no-unit tick) mints no ordinary prediction that tick (D15-5)."""
    context, state, _router, _seat = started
    results = advance(context, state, 3)

    ran = [
        r.tick for r in results
        if all(d.fired for d in r.firing if str(d.node) == node)
    ]
    records = [r for r in _predictions(brain, node) if r["source"] == "node"]
    assert [record["tick"] for record in records] == ran
    assert ran, f"{node} ran on no tick of three — the fixture would prove nothing"
    assert {record["tier"] for record in records} == {None}
    assert {record["node"] for record in records} == {node}
    assert {record["source"] for record in records} == {"node"}


def test_the_cortex_folder_writes_one_record_for_the_tier_that_ran(started, brain: Path):
    """A planner tick writes a planner-tier record and no executor-tier one."""
    context, state, router, _seat = started
    advance(context, state, 3)

    records = _predictions(brain, config.CORTEX_NODE)
    selected = [str(item.tier) for item in router.selections]
    assert selected == ["manager", "manager", "manager"]
    assert [(record["tick"], record["tier"]) for record in records] == list(
        zip([1, 2, 3], selected)
    )


def test_no_folder_and_tier_is_written_twice_in_one_tick(started, brain: Path):
    context, state, _router, _seat = started
    advance(context, state, 3)

    for node in config.NODE_ORDER:
        keys = Counter(
            (record["tick"], record["tier"], record["source"])
            for record in _predictions(brain, node)
        )
        assert all(count == 1 for count in keys.values()), (node, keys)


def test_the_committed_files_hold_exactly_what_the_tick_minted(started, brain: Path):
    """Minted and landed agree on a clean run: the dedupe key only bites on a replay."""
    context, state, _router, _seat = started
    results = advance(context, state, 2)

    minted = Counter(
        (str(record.node), str(record.tier) if record.tier else None)
        for result in results
        for record in result.predictions
    )
    landed = Counter(
        (node, record["tier"])
        for node in config.NODE_ORDER
        for record in _predictions(brain, node)
    )
    assert minted == landed


def test_a_second_append_of_a_minted_record_is_rejected(started, brain: Path):
    """The dedupe key, exercised on the runtime's own records rather than a factory's."""
    context, state, _router, _seat = started
    result = advance(context, state, 1)[0]

    for record in result.predictions:
        path = trace_path(brain, record.node)
        before = path.read_bytes()
        assert append_trace(path, record) is None, record.prediction_key()
        assert path.read_bytes() == before


def test_the_director_tier_writes_one_record_per_tick_and_refuses_a_second(
    brain: Path, workspace: Path, director_layer, mailbox
):
    """The runtime's director-tier half of the row; the `stuck` raise's own case is W3's."""
    from protean.runtime.engine import build_context, new_state

    seat_layer, router, _seat = director_layer
    context = build_context(
        brain, "task-director", seat_layer, mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-director", "redirect me", context)
    results = advance(context, state, 3)

    records = _predictions(brain, config.CORTEX_NODE)
    assert [(record["tick"], record["tier"]) for record in records] == [
        (1, "director"),
        (2, "director"),
        (3, "director"),
    ]
    assert {str(item.tier) for item in router.selections} == {"director"}

    path = trace_path(brain, config.CORTEX_NODE)
    for result in results:
        for record in result.predictions:
            if record.tier is Tier.DIRECTOR:
                assert append_trace(path, record) is None
    assert len(_predictions(brain, config.CORTEX_NODE)) == 3


def test_a_hand_built_second_director_record_at_the_same_tick_is_refused(
    brain: Path, workspace: Path, director_layer, mailbox
):
    """Same `(task, tick, node, tier, kind, source)`, a different payload — still one record."""
    from protean.runtime.engine import build_context, new_state

    seat_layer, _router, _seat = director_layer
    context = build_context(
        brain, "task-f", seat_layer, mailbox=mailbox, workspace_path=str(workspace)
    )
    state = new_state("task-f", "redirect me", context)
    advance(context, state, 1)

    path = trace_path(brain, config.CORTEX_NODE)
    before = path.read_bytes()
    duplicate = factories.prediction(config.CORTEX_NODE, Tier.DIRECTOR, task="task-f", tick=1)
    assert append_trace(path, duplicate) is None
    assert path.read_bytes() == before
