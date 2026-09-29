"""Row G15's live half — the call site ruling D19-3 landed in `runtime/cycle.py`.

`the build specification (not in this mirror)` § Deliverable 1: *a skip is a recorded prediction, not an
absence* — a node whose cheap check declines mints one `source: firing` trace record on the tick
it skipped, keyed with the `:firing` suffix, and the next boundary grades it under
`firing_grade`. The order-W7 batteries prove the pair on hand-written records; this module is the
regression guard probat 22 asked for: nothing else in the battery asserts `TraceSource.FIRING` on
a **live** tick, so deleting the `predictions.firing_records()` call beside `_mint()` would have
left the battery green. Three passes on a throwaway root, zero model calls.
"""

from __future__ import annotations

from pathlib import Path

from protean import config
from protean.brain.jsonl import read_lines
from protean.brain.trace import prediction_key as raw_prediction_key
from protean.nodes import hippocampus as hippocampus_node
from protean.runtime.cycle import run_tick
from protean.state.enums import NodeName, TraceSource
from protean.state.records import TraceRecord
from tests.runtime import stubs
from tests.runtime.conftest import DECLINE, reopen

FIXTURE = "firing_decline.yaml"
NODE = str(NodeName.HIPPOCAMPUS)
GOAL = "write the note the goal names"


def _trace(brain: Path, node: str) -> list[dict]:
    return read_lines(config.node_dir(node, brain) / "trace.jsonl")


def test_a_declining_node_commits_a_firing_prediction_and_the_next_boundary_grades_it(
    brain: Path, workspace: Path
) -> None:
    task = "task-firing-live"
    context, state, _port, _seat = stubs.open_task(
        brain, workspace, FIXTURE, task, goal=GOAL
    )

    # Pass 1: every check fires on the seeded 0.0 thresholds — no firing record anywhere.
    state.tick += 1
    run_tick(context, state)
    assert [r for r in _trace(brain, NODE) if r["source"] == str(TraceSource.FIRING)] == []

    # Pass 2: the hippocampus declines — its decision rides `result.firing`, and the call site
    # beside `_mint()` commits it as a `source: firing` prediction with the suffixed key.
    stubs.set_weight(brain, NODE, **{hippocampus_node.WEIGHT_FIRING: DECLINE})
    context = reopen(brain, task, context, workspace)
    state.tick += 1
    result = run_tick(context, state)
    declined = [d for d in result.firing if str(d.node) == NODE]
    assert declined and declined[0].fired is False

    firing = [
        r for r in _trace(brain, NODE)
        if r["kind"] == "prediction" and r["source"] == str(TraceSource.FIRING)
    ]
    assert [r["tick"] for r in firing] == [2], "one firing record, on the tick it declined"
    key = TraceRecord.model_validate(firing[0]).prediction_key()
    assert key.endswith(":prediction:firing")
    assert raw_prediction_key(firing[0]) == key, "both implementations agree on the live record"
    own = [
        r for r in _trace(brain, NODE)
        if r["kind"] == "prediction" and r["tick"] == 2 and r["source"] == str(TraceSource.NODE)
    ]
    assert own == [], "a node that declined mints no ordinary prediction that tick (D15-5)"

    # Pass 3: the boundary grades tick 2 — one `firing_grade` outcome whose `ref` is the key.
    state.tick += 1
    run_tick(context, state)
    grades = [
        r for r in _trace(brain, NODE)
        if r["kind"] == "outcome" and r["source"] == str(TraceSource.FIRING_GRADE)
    ]
    assert [r["ref"] for r in grades] == [key]
    assert grades[0]["outcome"]["signal"] == "firing_check"
    assert grades[0]["outcome"]["work_arrived"] is False
    assert grades[0]["outcome"]["matched"] is True
