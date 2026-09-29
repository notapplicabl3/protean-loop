"""Row G15's trace half: the agreed key, the round trip, and the tick that writes two lines.

`the build specification (not in this mirror)` § Deliverable 1, "**It sits under its own trace source**"
and "**And its key is distinct too**"; § Scaffold clause item 2, contract 3's amendments (a),
(d) and (e).

**Zero model calls.** Every fixture here writes and reads `trace.jsonl` records and calls
nothing — the decision these records carry is `protean.runtime.firing`'s and is order W6's.

**The two implementations are the point.** `TraceRecord.prediction_key()` and
`protean.brain.trace.prediction_key()` are two independent computations of one key — one off the
model, one off the raw mapping `committed_prediction_keys()` reads back from disk. Both suffix on
the record's `source == firing` and on nothing else. A suffix applied at the model alone would
make **every** firing grade a `TraceAppendRefused` at write (folded: S-A89), so the byte-identity
assertion below is the guard on that failure and not decoration.

**The pre-A.1 key is pinned as a literal, not recomputed.** `PRE_A1_HOMEOSTASIS_KEY` is what
the pre-A.1 revision of `src/protean/state/records.py` — the last commit before build A.1's first —
computes for the record `_own_prediction()` builds: `f"{task}:{tick}:{node}:{tier}:prediction"`.
Recomputing it with today's code would assert today's code against itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protean import config
from protean.brain.jsonl import read_lines
from protean.brain.trace import (
    append_trace,
    committed_prediction_keys,
    committed_predictions,
    graded_refs,
)
from protean.brain.trace import prediction_key as raw_prediction_key
from protean.runtime import outcomes, predictions
from protean.sleep.evidence import RunRecords, admissible_set
from protean.sleep.habits import tier_of_ref
from protean.state.brain_state import BrainState
from protean.state.calls import FiringDecision
from protean.state.enums import NodeName, Tier, TraceKind, TraceSource
from protean.state.outputs import HomeostasisReport
from protean.state.records import FIRING_KEY_SUFFIX, TraceRecord
from protean.state.workspace import LatestOutputs
from tests.brain.conftest import trace_path

TASK = "t-firing"
TICK = 4
BOUNDARY = TICK + 1

#: What build 1's `prediction_key()` wrote for this record, pinned as a literal (see the module
#: docstring). Row G15's "the node's own `ref` byte-identical to what it was before A.1".
PRE_A1_HOMEOSTASIS_KEY = f"{TASK}:{TICK}:homeostasis:-:prediction"


def _decision(node: NodeName, *, fired: bool, value: float = 0.25) -> FiringDecision:
    """One declining (or firing) cheap check, in the shape `runtime.firing` returns."""
    return FiringDecision(
        tick=TICK,
        node=node,
        check=f"{node}_score",
        key="firing_threshold",
        value=value,
        threshold=0.5,
        fired=fired,
    )


def _firing_prediction(node: NodeName = NodeName.HOMEOSTASIS) -> TraceRecord:
    return predictions.firing(task=TASK, tick=TICK, decision=_decision(node, fired=False))


def _own_prediction() -> TraceRecord:
    """Homeostasis's own prediction on the same tick — its body is contractual and always runs."""
    return predictions.homeostasis(
        task=TASK,
        tick=TICK,
        report=HomeostasisReport(tick=TICK, tokens=10, wall_seconds=1.0, error_rate=0.0, ticks=1),
        tokens_this_tick=10,
        seconds_this_tick=1.0,
    )


def _derive(
    *,
    previous: LatestOutputs,
    brain: Path,
    cost: outcomes.TickCost = outcomes.TickCost(tokens=10, wall_seconds=1.0),
) -> list[TraceRecord]:
    """The boundary's own derivation, over whatever this folder has committed."""
    return outcomes.derive(
        tick=BOUNDARY,
        state=BrainState(task_id=TASK),
        previous=previous,
        current=LatestOutputs(),
        cost=cost,
        committed={node: committed_predictions(trace_path(brain, node)) for node in config.NODE_ORDER},
        graded={node: graded_refs(trace_path(brain, node)) for node in config.NODE_ORDER},
    )


# --------------------------------------------------------------------------------------
# The agreed key — amendment (e), in both implementations, under one condition
# --------------------------------------------------------------------------------------


def test_the_two_prediction_key_implementations_agree_on_one_firing_record() -> None:
    """Byte-identical, and both carrying the suffix, on the same record."""
    record = _firing_prediction()
    assert record.source is TraceSource.FIRING
    off_the_model = record.prediction_key()
    off_the_mapping = raw_prediction_key(record.model_dump(mode="json"))
    assert off_the_model == off_the_mapping
    assert off_the_model.encode() == off_the_mapping.encode()
    assert off_the_model.endswith(FIRING_KEY_SUFFIX)


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(_own_prediction(), id="node"),
        pytest.param(
            predictions.synthetic_stuck(
                task=TASK, tick=TICK, goal_id="g-1", weights={"progress_window": 8}
            ),
            id="runtime",
        ),
    ],
)
def test_neither_implementation_suffixes_a_record_that_is_not_firing_sourced(
    record: TraceRecord,
) -> None:
    """The suffix is keyed on `source == firing`, so every existing `ref` stays byte-identical."""
    off_the_model = record.prediction_key()
    off_the_mapping = raw_prediction_key(record.model_dump(mode="json"))
    assert off_the_model == off_the_mapping
    assert not off_the_model.endswith(FIRING_KEY_SUFFIX)
    assert not off_the_mapping.endswith(FIRING_KEY_SUFFIX)


def test_the_nodes_own_ref_is_byte_identical_to_the_pre_a1_key() -> None:
    """`f"{task}:{tick}:{node}:{tier}:prediction"`, exactly as the last commit before build A.1 wrote it."""
    assert _own_prediction().prediction_key() == PRE_A1_HOMEOSTASIS_KEY
    assert raw_prediction_key(_own_prediction().model_dump(mode="json")) == PRE_A1_HOMEOSTASIS_KEY


def test_tier_of_ref_reads_the_same_tier_out_of_a_suffixed_key() -> None:
    """The named ref-parser blast radius: `parts[3]` under a six-part key (folded: S-A61)."""
    own = _own_prediction().prediction_key()
    firing = _firing_prediction().prediction_key()
    assert firing.split(":") != own.split(":")
    assert len(firing.split(":")) == len(own.split(":")) + 1
    assert tier_of_ref(firing) == tier_of_ref(own) == "-"

    cortex = predictions.synthetic_stuck(
        task=TASK, tick=TICK, goal_id="g-1", weights={"progress_window": 8}
    )
    assert tier_of_ref(cortex.prediction_key()) == str(Tier.DIRECTOR)


# --------------------------------------------------------------------------------------
# The round trip — the pair written, read back and joined
# --------------------------------------------------------------------------------------


def test_the_firing_grade_survives_append_trace(brain: Path) -> None:
    """The suffixed key is in `committed_prediction_keys()`, so the grade is not refused."""
    path = trace_path(brain, NodeName.HOMEOSTASIS)
    prediction = _firing_prediction()
    assert append_trace(path, prediction) is not None
    assert committed_prediction_keys(path) == {prediction.prediction_key()}

    graded = _derive(previous=LatestOutputs(), brain=brain)
    assert [record.source for record in graded] == [TraceSource.FIRING_GRADE]
    assert graded[0].ref == prediction.prediction_key()
    assert append_trace(path, graded[0]) is not None


def test_the_pair_round_trips_and_joins_as_one_admissible_pair(brain: Path) -> None:
    """Row G15's join clause, through `sleep/evidence`'s own `by_key`."""
    path = trace_path(brain, NodeName.HIPPOCAMPUS)
    prediction = _firing_prediction(NodeName.HIPPOCAMPUS)
    append_trace(path, prediction)
    grade = _derive(previous=LatestOutputs(), brain=brain)[0]
    append_trace(path, grade)

    lines = read_lines(path)
    assert [line["kind"] for line in lines] == ["prediction", "outcome"]
    assert [line["source"] for line in lines] == ["firing", "firing_grade"]
    assert lines[1]["ref"] == f"{TASK}:{TICK}:hippocampus:-:prediction:firing"

    records = [TraceRecord.model_validate(line) for line in lines]
    pairs = admissible_set(
        RunRecords(
            source=str(path),
            task=TASK,
            terminal=None,
            project="p",
            ticks=BOUNDARY,
            seed_hashes={},
            predictions=(records[0],),
            outcomes=(records[1],),
            units={},
            summaries={},
        )
    )
    assert len(pairs.pairs) == 1
    pair = pairs.pairs[0]
    assert pair.admissible is True
    assert pair.excluded_reason == ""
    assert pair.signal == "firing_check"
    assert pair.ref == prediction.prediction_key()
    # Nothing arrived for a node that declined and ran no body, so the decline was right.
    assert pair.matched is True


# --------------------------------------------------------------------------------------
# One tick, two predictions, two keys, two grades
# --------------------------------------------------------------------------------------


def test_a_tick_writes_two_lines_two_keys_and_the_boundary_grades_both(brain: Path) -> None:
    """Homeostasis is the live case: its full report is never skippable and its think call is."""
    path = trace_path(brain, NodeName.HOMEOSTASIS)
    own, firing = _own_prediction(), _firing_prediction()
    assert own.dedupe_key() != firing.dedupe_key()
    append_trace(path, own)
    append_trace(path, firing)

    written = read_lines(path)
    assert len(written) == 2
    keys = [raw_prediction_key(line) for line in written]
    assert keys == [PRE_A1_HOMEOSTASIS_KEY, PRE_A1_HOMEOSTASIS_KEY + FIRING_KEY_SUFFIX]
    assert len(set(keys)) == 2

    # Its body ran — the decline stopped the think call alone — so its slot is stamped and the
    # skip grade reads "work arrived" (ledger `D19-2`).
    previous = LatestOutputs(
        homeostasis=HomeostasisReport(
            tick=TICK, tokens=10, wall_seconds=1.0, error_rate=0.0, ticks=1
        )
    )
    graded = _derive(previous=previous, brain=brain)
    assert {record.source for record in graded} == {
        TraceSource.RUNTIME_GRADE,
        TraceSource.FIRING_GRADE,
    }
    assert sorted(record.ref for record in graded) == sorted(keys)
    for record in graded:
        assert record.kind is TraceKind.OUTCOME
        assert append_trace(path, record) is not None
    assert graded_refs(path) == set(keys)

    skip = next(one for one in graded if one.source is TraceSource.FIRING_GRADE)
    assert skip.outcome.work_arrived is True
    assert skip.outcome.matched is False
    assert tier_of_ref(skip.ref) == "-"


def test_a_declining_node_nothing_arrived_for_is_graded_matched(brain: Path) -> None:
    """The other half of the observable: no stamp on the skipped tick, so the skip was right."""
    path = trace_path(brain, NodeName.THALAMUS)
    append_trace(path, _firing_prediction(NodeName.THALAMUS))
    graded = _derive(previous=LatestOutputs(), brain=brain)
    assert len(graded) == 1
    assert graded[0].outcome.work_arrived is False
    assert graded[0].outcome.matched is True
