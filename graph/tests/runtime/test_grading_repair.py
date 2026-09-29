"""Repair (a) replayed against the run it was measured on — the archived tick-2 records.

`the build specification (not in this mirror)` § Deliverable 1, repair (a); DoD row L1, clause 1. The
hippocampus predicts bare episode ids and the thalamus mints — and the seat cites —
`admitted:<episode id>`, so build 2's intersection was empty on every tick of the `~/workload` run
while the thalamus graded `matched: true` on the very same citations. The archive is the before:
`cited_episode_ids: []` against four consecutive `matched: false`.

**The archive is read, never written.** Every path here is opened for reading and the per-file
sha256 of the whole directory is asserted unchanged across the replay (row N8's shape, one test).
The module skips cleanly when the archive is not on disk, following the guard
`tests/dashboard/test_snapshot.py::real_archive` uses — the archive is gitignored and lives on one
machine (§ Named assumptions 8).

**What "replay" means here.** The real `outcomes.derive()` at tick 2, fed the observables the
archive preserves: `previous` and `current` are the `LatestOutputs` rebuilt from journals 1 and 2,
`state` is the checkpoint's own `BrainState`, and `committed` is every folder's committed
predictions. The one observable the archive does not preserve per tick is the tick's measured cost
— `CostCounters` are archived cumulatively, at tick 4 only — so `TickCost` is taken from the
homeostasis record's `observed_tokens`/`observed_wall_seconds`; its *verdict* is still re-derived
from the prediction's `next_tick_tokens`, which is what that arm is being tested on.

**Repair (b) is not here.** It lands in the monitor, not the grader, so its battery is
`tests/nodes/test_anterior_cingulate.py` beside the function it repairs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from protean import config
from protean.brain.trace import committed_predictions
from protean.runtime import journal, outcomes
from protean.state.brain_state import BrainState
from protean.state.records import TraceRecord
from protean.state.workspace import LatestOutputs

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The `~/workload` run repair (a) was measured on (`the local project notes (not in this mirror)` top entry, build 2 order W8).
REAL_ARCHIVE = "workload-run-20260907T153455290946"

#: The boundary the SPEC names: the tick-1 predictions graded at tick 2.
GRADED_TICK = 2


@pytest.fixture(scope="module")
def archive() -> Path:
    directory = REPO_ROOT / "brain" / "archive" / REAL_ARCHIVE
    if not directory.is_dir():
        pytest.skip(f"the real archive {REAL_ARCHIVE} is not on disk")
    # **Build A.1 refuses a pre-A.1 artifact by name and never migrates one**
    # (`the build specification (not in this mirror)` § Out of scope, "Migrating any checkpoint or
    # artifact"): six schema versions went 1 → 2, and this archive is run 1's, written under
    # version 1 with the deleted `planner` and `executor` seats in its checkpoint. The archive
    # is **read-only to every order**, so the refusal is the end of the road rather than
    # something to repair — the skip is the same guard the line above uses, on the same
    # module-scoped fixture, and it names the version rather than the file.
    checkpoint = json.loads(
        (directory / "state" / "checkpoint.json").read_text(encoding="utf-8")
    )
    found = int(checkpoint.get("schema_version", -1))
    if found != config.CHECKPOINT_SCHEMA_VERSION:
        pytest.skip(
            f"the archive is checkpoint schema {found}, not "
            f"{config.CHECKPOINT_SCHEMA_VERSION}: build A.1 refuses a pre-A.1 artifact by "
            f"name and migrates none"
        )
    return directory


def _digest(directory: Path) -> dict[str, str]:
    """Per-file sha256 of every file under the archive — the read-only proof."""
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _latest(archive: Path, tick: int) -> LatestOutputs:
    """The tick's `LatestOutputs`, rebuilt from its journal — one slot per node, tier for seats."""
    slots: dict[str, object] = {}
    for entry in journal.load(archive / "state" / f"journal-{tick}.jsonl"):
        if entry.output is None:
            continue
        slots[str(entry.tier) if entry.tier is not None else str(entry.node)] = entry.output
    return LatestOutputs(**slots)


def _archived_outcomes(archive: Path, tick: int) -> dict[str, dict]:
    """What the run itself recorded at that boundary, folder → the `outcome` payload."""
    found: dict[str, dict] = {}
    for node in config.NODE_ORDER:
        path = archive / "nodes" / node / "trace.jsonl"
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("kind") == "outcome" and record.get("tick") == tick:
                found[node] = record["outcome"]
    return found


def _replay(archive: Path, tick: int = GRADED_TICK) -> list[TraceRecord]:
    """`outcomes.derive()` at that boundary, over the archive's own records."""
    checkpoint = json.loads((archive / "state" / "checkpoint.json").read_text(encoding="utf-8"))
    state = BrainState.model_validate(checkpoint["state"])
    recorded = _archived_outcomes(archive, tick)
    return outcomes.derive(
        tick=tick,
        state=state,
        previous=_latest(archive, tick - 1),
        current=_latest(archive, tick),
        cost=outcomes.TickCost(
            tokens=recorded["homeostasis"]["observed_tokens"],
            wall_seconds=recorded["homeostasis"]["observed_wall_seconds"],
        ),
        committed={
            node: committed_predictions(archive / "nodes" / node / "trace.jsonl")
            for node in config.NODE_ORDER
        },
        graded={},
    )


def _replayed(archive: Path, tick: int = GRADED_TICK) -> dict[str, dict]:
    return {
        str(record.node): record.outcome.model_dump(mode="json") for record in _replay(archive, tick)
    }


# --------------------------------------------------------------------------------------
# Repair (a) — the id-space mismatch, on the run that measured it
# --------------------------------------------------------------------------------------


def test_the_archive_holds_the_defect_this_repair_is_about(archive: Path):
    """Non-vacuity: without the archived `[]` against a `matched: true`, there is nothing to fix."""
    recorded = _archived_outcomes(archive, GRADED_TICK)
    assert recorded["hippocampus"]["cited_episode_ids"] == []
    assert recorded["hippocampus"]["matched"] is False
    assert recorded["thalamus"]["cited_admitted_ids"], "the seat cited the same items"
    assert recorded["thalamus"]["matched"] is True


def test_the_hippocampus_grade_now_intersects_where_the_archive_holds_nothing(archive: Path):
    """Row L1, clause 1: a prediction and a citation naming the same item now intersect."""
    replayed = _replayed(archive)
    before = _archived_outcomes(archive, GRADED_TICK)["hippocampus"]
    after = replayed["hippocampus"]

    assert before["cited_episode_ids"] == []
    assert after["cited_episode_ids"] == [
        "semantic:1cea19e976f0d33e",
        "semantic:2fdfeac92b7295ff",
        "semantic:481aeca46f708845",
        "task-20260907T152905915343:0",
    ]
    assert after["matched"] is True


def test_build_2s_comparison_is_the_empty_one_and_the_repaired_one_is_not(archive: Path):
    """The before/after of the comparison itself, not only of the record it produced."""
    predictions = committed_predictions(archive / "nodes" / "hippocampus" / "trace.jsonl")
    predicted = next(one for one in predictions if one.tick == GRADED_TICK - 1).prediction
    cited = _latest(archive, GRADED_TICK - 1).planner.cited_ids

    assert cited, "the planner cited something at the graded tick"
    assert sorted(set(cited) & set(predicted.episode_ids)) == [], "build 2's raw intersection"
    assert len({one.split(":", 1)[1] for one in cited} & set(predicted.episode_ids)) == 4


def test_the_thalamus_keeps_grading_those_citations_matched_and_in_its_own_ids(archive: Path):
    """The other half of repair (a): one convention, applied once, and this arm does not move."""
    before = _archived_outcomes(archive, GRADED_TICK)["thalamus"]
    after = _replayed(archive)["thalamus"]

    assert after == before
    assert after["matched"] is True
    assert all(one.startswith("admitted:") for one in after["cited_admitted_ids"])


def test_no_other_outcome_record_of_the_archived_boundary_moved(archive: Path):
    """Row L1: the recorded verdicts are unchanged **except where repair (a) applies**."""
    before = _archived_outcomes(archive, GRADED_TICK)
    after = _replayed(archive)

    assert sorted(after) == sorted(before), "the same folders grade at the same boundary"
    moved = sorted(node for node in before if before[node] != after[node])
    assert moved == ["hippocampus"], f"records moved that repair (a) does not reach: {moved}"


def test_the_replay_writes_nothing_into_the_archive(archive: Path):
    """Row N8's shape, scoped to this module: the archive is evidence, never a workspace."""
    before = _digest(archive)
    assert len(before) >= 18, "the archive is on disk in full"
    _replayed(archive)
    assert _digest(archive) == before
