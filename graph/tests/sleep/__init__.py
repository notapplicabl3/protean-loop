"""The sleep battery's own builders: a brain root, an archive-shaped run, and its records.

`the work orders (not in this mirror)` order W2 — the writable set names `tests/sleep/__init__.py`
and three test modules and no `conftest.py`, so the shared builders live on the package marker
rather than in a fixture module. `tests/state/samples.py` is the precedent one tree over.

**Everything here writes into a `tmp_path` and never into the repo's own `brain/`.** Refusal 2
is live on this checkout — run 1 is paused at tick 4 — so a wet-shaped test that pointed at the
repo root would be testing the refusal and nothing else. The one thing copied out of the repo is
the *tracked seed tree*, `brain/nodes/`, because the seed verification has to have real
`weights.yaml` bytes to re-hash.

**Hand-authored records, never captured ones.** Each builder below writes exactly the pair the
test under it is about, so an exclusion reason is proven by a fixture whose only interesting
property is the one being tested.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from protean import config
from protean.brain.folders import seed_hashes
from protean.runtime.paths import BrainPaths
from protean.state.enums import (
    CallType,
    ExpectationKind,
    NodeName,
    TraceKind,
    TraceSource,
    Tier,
)
from protean.state.primitives import Expectation, WorkUnit
from protean.state.records import TraceRecord
from protean.state.seats import ExecutorSummary

#: The entry a copied seed tree leaves behind — generated state, never part of the seed.
GENERATED_NODE_ENTRY = "trace.jsonl"

#: The archive's own layout, as `protean.runtime.archive` writes it.
ARCHIVE_NODES = "nodes"
ARCHIVE_STATE = "state"


def seeded_brain(tmp_path: Path, repo_root: Path) -> BrainPaths:
    """A throwaway brain root carrying the tracked seed tree's node folders and nothing else."""
    root = tmp_path / "brain"
    shutil.copytree(
        repo_root / "brain" / "nodes",
        root / "nodes",
        ignore=shutil.ignore_patterns(GENERATED_NODE_ENTRY),
    )
    return BrainPaths(root=root)


def tree_hashes(root: Path) -> list[tuple[str, str]]:
    """Per-file sha256 over every file under a directory, sorted.

    The receipt shape rows L2, L3 and N8 all read: two listings compared, so a file added,
    removed or rewritten under a tree that was supposed to be read-only shows up as a diff.
    """
    return [
        (path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


# --------------------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------------------


def prediction(
    *,
    node: NodeName,
    payload,
    task: str = "task-fixture",
    tick: int = 1,
    tier: Tier | None = None,
) -> TraceRecord:
    """One committed `prediction` record, in the shape a node writes it."""
    return TraceRecord(
        schema_version=config.TRACE_SCHEMA_VERSION,
        task=task,
        tick=tick,
        node=node,
        tier=tier,
        kind=TraceKind.PREDICTION,
        source=TraceSource.NODE,
        prediction=payload,
    )


def outcome(
    record: TraceRecord,
    payload,
    *,
    source: TraceSource = TraceSource.RUNTIME_GRADE,
    scored_at_tick: int | None = None,
) -> TraceRecord:
    """The `outcome` record grading one prediction, `ref` set to its `prediction_key()`."""
    tick = record.tick + 1 if scored_at_tick is None else scored_at_tick
    return TraceRecord(
        schema_version=config.TRACE_SCHEMA_VERSION,
        task=record.task,
        tick=tick,
        node=record.node,
        tier=record.tier,
        kind=TraceKind.OUTCOME,
        source=source,
        outcome=payload,
        ref=record.prediction_key(),
        scored_at_tick=tick,
    )


def unit(unit_id: str, *expectations: Expectation, goal_id: str = "g1") -> WorkUnit:
    """One `WorkUnit` carrying the predicates the monitor evaluated."""
    return WorkUnit(
        id=unit_id,
        goal_id=goal_id,
        intent=f"the fixture unit {unit_id}",
        expected=list(expectations),
    )


def codeless_exit_code(identifier: str) -> Expectation:
    """Run 1's own defect: an `exit_code` predicate with no `code` argument (repair (b))."""
    return Expectation(
        id=identifier,
        kind=ExpectationKind.EXIT_CODE,
        arguments={"command": "git rev-parse --abbrev-ref HEAD", "value": 0},
    )


def gradeable_file_exists(identifier: str, path: str) -> Expectation:
    """A predicate the summary carries an observation for — graded from evidence present."""
    return Expectation(
        id=identifier, kind=ExpectationKind.FILE_EXISTS, arguments={"path": path}
    )


def summary(
    unit_id: str, *, tick: int, observed: Sequence[str] = (), values: Mapping | None = None
) -> ExecutorSummary:
    """The `ExecutorSummary` the monitor graded, carrying an observation per named path."""
    return ExecutorSummary(
        tick=tick,
        unit_id=unit_id,
        narrative="the fixture executor's account",
        observations=[
            {"path": path, "exists": True, "size_bytes": 1, "content_hash": "h"}
            for path in observed
        ],
        expectation_values=dict(values or {}),
    )


# --------------------------------------------------------------------------------------
# The run on disk
# --------------------------------------------------------------------------------------


def write_run(
    directory: Path,
    *,
    brain: BrainPaths,
    records: Iterable[TraceRecord],
    task: str = "task-fixture",
    tick: int = 1,
    terminal: str | None = "done",
    units: Sequence[WorkUnit] = (),
    summaries: Mapping[int, ExecutorSummary] | None = None,
    seeds: Mapping[str, str] | None = None,
    project: str | None = None,
) -> Path:
    """An archive-shaped run directory: node traces, a checkpoint, and one journal per tick.

    `seeds` defaults to the **live** hashes of the brain root handed in, so the seed
    verification passes and a test that wants a moved hash moves the file rather than the map.
    """
    state_dir = directory / ARCHIVE_STATE
    state_dir.mkdir(parents=True, exist_ok=True)
    by_node: dict[str, list[TraceRecord]] = {}
    for record in records:
        by_node.setdefault(str(record.node), []).append(record)
    for node, rows in by_node.items():
        folder = directory / ARCHIVE_NODES / node
        folder.mkdir(parents=True, exist_ok=True)
        (folder / GENERATED_NODE_ENTRY).write_text(
            "".join(
                json.dumps(row.model_dump(mode="json"), separators=(",", ":")) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )
    for entry_tick, entry in (summaries or {}).items():
        (state_dir / f"journal-{entry_tick}.jsonl").write_text(
            json.dumps(
                {
                    "schema_version": config.JOURNAL_SCHEMA_VERSION,
                    "task": task,
                    "tick": entry_tick,
                    "node": str(NodeName.CORTEX),
                    "tier": str(CallType.DISPATCH),
                    "output": entry.model_dump(mode="json"),
                    "envelope": None,
                },
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
    state = {
        "schema_version": config.BRAIN_STATE_SCHEMA_VERSION,
        "task_id": task,
        "tick": tick,
        "terminal": terminal,
        "units": [row.model_dump(mode="json") for row in units],
        "extensions": {} if project is None else {"project": {"slug": project}},
    }
    (state_dir / "checkpoint.json").write_text(
        json.dumps(
            {
                "schema_version": config.CHECKPOINT_SCHEMA_VERSION,
                "revision": 0,
                "state": state,
                "extensions": {},
                "seed_hashes": dict(seeds if seeds is not None else seed_hashes(brain.root)),
                "integrity": "",
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return directory


def occupy(brain: BrainPaths, *, task_id: str = "task-held", terminal: str | None = None,
           seeds: Mapping[str, str] | None = None) -> str:
    """Put a checkpointed task on the root, with whatever committed terminal a test needs."""
    checkpoint = brain.task(task_id).checkpoint
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(
        json.dumps(
            {
                "schema_version": config.CHECKPOINT_SCHEMA_VERSION,
                "state": {"task_id": task_id, "tick": 1, "terminal": terminal, "units": []},
                "seed_hashes": dict(seeds if seeds is not None else seed_hashes(brain.root)),
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return task_id
