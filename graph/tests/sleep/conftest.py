"""The dry battery's fixture machinery: read one hand-scripted arm, build it, normalise it.

`the build specification (not in this mirror)` § Deliverable 6 (the dry-oracle paragraph and "The metric"),
§ DoD rows L9, L10, N3, N7 and N8; `the work orders (not in this mirror)` order W8.

**The arms are files, not code.** `fixtures/traces/<arm>/trace.yaml` is a hand-authored
prediction/outcome script and `fixtures/traces/<arm>/expected/` is what sleep must produce from
it, byte for byte — the same shape `fixtures/scenarios/dry/scenario.yaml` and its `expected.yaml`
established one build back. Nothing here derives an expectation from a run: a trace the battery
generated would assert only that the run equals itself.

**Why a materialiser rather than a checked-in brain root.** Sleep verifies the seed hashes the
run's `checkpoint.json` recorded against the `weights.yaml` files actually on disk (decision 17),
so a fixture that carried its own recorded hashes would restate a derived number and go stale the
first time the operator re-values a threshold ("docs carry checkable claims, never derived numbers" is the standing rule, by
name; § Resolutions D3-5 is where this build already paid for ignoring it). The arm names
the *shape* of its run; the tracked seed tree supplies the values; `tests.sleep.write_run` records
the live hashes, exactly as every other sleep test does.

**Two things in a report are environment, not rule** — the absolute paths of the throwaway brain
root and the throwaway run directory, and the sha256 of each verified seed file. Both are
substituted for a placeholder before the comparison (`normalise()`), which is § Resolutions
D16-3's `$goal` precedent applied to the comparison rather than to a compiled file: the model is
not widened, no field is dropped, and the placeholder for a seed hash names the file it came from,
so "every applied update carries the seed hash of its own node's file" is still a byte-level
check. Everything else in the report — every count, every ratio, every `sleep_id` — is compared
as written.

**`now=` is what makes two runs of one arm byte-identical.** The `sleep_id` is minted from the
clock; the battery pins it, so the only remaining difference between two runs of the same arm is
the temp directory, which `normalise()` removes.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from protean import config
from protean.runtime import paths as paths_module
from protean.runtime.paths import BrainPaths
from protean.sleep.evidence import admissible_set, load_archived_run
from protean.sleep.run import PhaseInput, SleepOutcome, run_sleep, verify_seeds
from protean.state.enums import CallType, ExpectationKind, NodeName, Tier, TrapDetector
from protean.state.outputs import MonitorVerdict
from protean.state.primitives import Expectation, TrapScalar, WorkUnit
from protean.state.records import (
    DispatchOutcome,
    DispatchPrediction,
    HippocampusOutcome,
    HippocampusPrediction,
    JournalEntry,
    MonitorOutcome,
    MonitorPrediction,
    ManagerOutcome,
    ManagerPrediction,
    TraceRecord,
)
from protean.state.seats import ExecutorSummary
from protean.state.sleep import ProjectMemoryRecord
from tests.sleep import outcome, prediction, seeded_brain, unit, write_run

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The two fixture trees this order authors. `traces/` holds one directory per rule arm;
#: `procedures/` holds the byte-expected compiled-habit files, keyed by the arm that produces
#: (or, for the withdrawal, consumes) them.
TRACES = REPO_ROOT / "fixtures" / "traces"
PROCEDURES = REPO_ROOT / "fixtures" / "procedures"

#: The arm's own file names.
TRACE_FILE = "trace.yaml"
EXPECTED_DIRNAME = "expected"
#: Under `expected/`, a mirror of the brain root: every file here is compared byte for byte
#: against the same relative path under the run's throwaway root.
EXPECTED_BRAIN = "brain"
#: Under `expected/`, the normalised `SleepReport` as JSON.
EXPECTED_REPORT = "report.json"

#: The clock every arm is run under, so the `sleep_id` is a constant rather than a measurement.
SLEEP_NOW = datetime(2026, 9, 8, tzinfo=UTC)
SLEEP_ID = "sleep-20260908-000000Z"
#: The `sleep_id` a *prior* run left on the hand-authored project-memory lines.
EARLIER_SLEEP_ID = "sleep-20260907-000000Z"

#: The placeholders `normalise()` substitutes. Read them as `$goal` is read in a compiled
#: procedure: a name standing where an environment-specific string would otherwise be.
BRAIN_PLACEHOLDER = "$brain"
SOURCE_PLACEHOLDER = "$source"
SEED_PLACEHOLDER = "$seed:"

#: The default task ids an arm uses when it names none.
CURRENT_TASK = "task-fixture"
EARLIER_TASK = "task-earlier"

#: The goal and unit the shared cortex builders script. One goal text, so a compiled habit's
#: `goal_digest` is the same constant wherever the vocabulary is used.
GOAL_ID = f"{CURRENT_TASK}-g1"
GOAL_TEXT = "reconcile the pins and make the suite runnable"
UNIT_ID = "u-1"


# --------------------------------------------------------------------------------------
# Reading an arm
# --------------------------------------------------------------------------------------


def arm_names() -> list[str]:
    """Every arm on disk, sorted — the battery parametrises over this and never over a list."""
    return sorted(
        path.parent.name for path in TRACES.glob(f"*/{TRACE_FILE}") if path.is_file()
    )


def load_arm(name: str) -> dict[str, Any]:
    """One `trace.yaml`, as authored."""
    return yaml.safe_load((TRACES / name / TRACE_FILE).read_text(encoding="utf-8"))


def expected_dir(name: str) -> Path:
    """`fixtures/traces/<arm>/expected/` — what sleep must produce from the arm."""
    return TRACES / name / EXPECTED_DIRNAME


def expected_brain_files(name: str) -> list[Path]:
    """Every byte-expected file under `expected/brain/`, sorted."""
    root = expected_dir(name) / EXPECTED_BRAIN
    return sorted(path for path in root.rglob("*") if path.is_file()) if root.is_dir() else []


def procedure_fixture(name: str, procedure_id: str) -> Path:
    """`fixtures/procedures/<arm>/<procedure_id>.yaml`."""
    return PROCEDURES / name / f"{procedure_id}.yaml"


def numeric_literals(
    path: Path, *, within: str | None = None, bools: bool = False
) -> list[tuple[int, object]]:
    """Every int/float constant in a module, with its line — annotations and docstrings apart.

    `within` narrows the walk to one named function, which is how a claim about a single call
    site is held without the rest of the module's numbers answering for it. `bools` keeps `True`
    and `False`, which `isinstance(value, int)` admits and a "no number here" claim usually does
    not want — the exit-code claim is the one that does.
    """
    tree: ast.AST = ast.parse(path.read_text(encoding="utf-8"))
    if within is not None:
        tree = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == within
        )
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and (bools or not isinstance(node.value, bool))
    ]


# --------------------------------------------------------------------------------------
# The shared builder vocabulary — one spelling per shape, for every module in this package
# --------------------------------------------------------------------------------------
#
# Order W2 put the package's builders on `tests/sleep/__init__.py` and order W8 rebuilt a second,
# private vocabulary here for the arms; the test modules grew a third copy each. These are the
# supersets: one definition per shape, and the private `_*` builders below delegate to them
# wherever the two spellings are the same bytes.


def hippocampus_pair(*, tick: int, matched: bool, task: str = CURRENT_TASK, cited: bool = True):
    """One `hippocampus_citation` pair. `cited=False` predicts nothing, so the pair is vacuous."""
    record = prediction(
        node=NodeName.HIPPOCAMPUS,
        payload=HippocampusPrediction(episode_ids=[f"e-{tick}"] if cited else []),
        task=task,
        tick=tick,
    )
    graded = outcome(
        record,
        HippocampusOutcome(
            cited_episode_ids=[f"e-{tick}"] if matched else [], matched=matched
        ),
    )
    return record, graded


def monitor_pair(*, tick: int, matched: bool, task: str = CURRENT_TASK):
    """One `monitor_next_verdict` pair — the signal that funds the detector thresholds."""
    record = prediction(
        node=NodeName.ANTERIOR_CINGULATE,
        payload=MonitorPrediction(next_verdict_match=True),
        task=task,
        tick=tick,
    )
    graded = outcome(record, MonitorOutcome(observed_match=matched, matched=matched))
    return record, graded


def planner_pair(
    *, tick: int, matched: bool, task: str = CURRENT_TASK, unit_id: str = UNIT_ID
):
    """One `manager_horizon` pair, joined and graded. Admissible: no vacuity arm applies."""
    record = prediction(
        node=NodeName.CORTEX,
        payload=ManagerPrediction(unit_id=unit_id, horizon_ticks=4),
        task=task,
        tick=tick,
        tier=Tier.MANAGER,
    )
    graded = outcome(
        record, ManagerOutcome(passed_within_horizon=matched, matched=matched)
    )
    return record, graded


def planner_plan(tick: int, *, goal_id: str = GOAL_ID, unit_id: str = UNIT_ID) -> dict:
    """The answer the seat gave, as the runtime journalled it — a decoded `ManagerPlan`."""
    return {
        "emitter": "manager",
        "tick": tick,
        "interrupt": None,
        "units": [
            {
                "id": unit_id,
                "goal_id": goal_id,
                "intent": "split the maintainer-only tests out of the suite",
                "expected": [],
            }
        ],
        "goals_satisfied": [],
        "mismatch_class": None,
        "trap_dismissed": [],
        "cited_ids": [],
    }


def flatten(pairs):
    """Every record of a sequence of pairs, in order — what `write_run` takes."""
    return [record for pair in pairs for record in pair]


def by_key(updates):
    """The update rows of one phase, keyed by the weights key each is about."""
    return {row.key: row for row in updates}


def memory_line(
    brain,
    *,
    node: NodeName,
    signal: str,
    ref: str,
    task: str = EARLIER_TASK,
    slug: str = paths_module.ROOT_PROJECT_SLUG,
    sleep_id: str = EARLIER_SLEEP_ID,
    tick: int = 1,
    key: str | None = None,
    matched: bool = True,
    admissible: bool = True,
    excluded_reason: str = "",
    consumed: Mapping[str, str] | None = None,
) -> ProjectMemoryRecord:
    """One hand-authored P4 pair line, appended where order W5's writer will append it."""
    record = ProjectMemoryRecord(
        project=slug,
        node=node,
        sleep_id=sleep_id,
        task=task,
        tick=tick,
        ref=ref,
        signal=signal,
        key=key,
        matched=matched,
        admissible=admissible,
        excluded_reason=excluded_reason,
        consumed_by=dict(consumed or {}),
    )
    path = brain.project_learning(slug, str(node))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.model_dump(mode="json"), separators=(",", ":")) + "\n")
    return record


def earlier_memory_line(
    brain, *, slug: str = paths_module.ROOT_PROJECT_SLUG, tick: int = 1
) -> None:
    """A prior sleep run's reading of an earlier task's planner pair, in that project's memory.

    The second task the persistence floor needs, read back at pair granularity and never off
    another task's node traces (decision 22).
    """
    path = brain.project_learning(slug, config.CORTEX_NODE)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "schema_version": config.PROJECT_MEMORY_SCHEMA_VERSION,
        "project": slug,
        "node": config.CORTEX_NODE,
        "sleep_id": EARLIER_SLEEP_ID,
        "task": EARLIER_TASK,
        "tick": tick,
        "ref": f"{EARLIER_TASK}:{tick}:cortex:manager:prediction",
        "signal": "manager_horizon",
        "key": None,
        "matched": True,
        "admissible": True,
        "excluded_reason": "",
        "consumed_by": {},
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, separators=(",", ":")) + "\n")


def monitor_journal(
    state_dir: Path, *, task: str, tick: int, fired: TrapDetector | str | None
) -> None:
    """One tick's journal carrying the anterior cingulate's verdict — the confirmation's source."""
    traps = []
    if fired is not None:
        traps.append(
            TrapScalar(
                detector=TrapDetector(fired),
                value=9.0,
                threshold=2.0,
                weight_key="rut_ticks",
                fired=True,
                unit_id="u-fixture",
            )
        )
    entry = JournalEntry(
        schema_version=config.JOURNAL_SCHEMA_VERSION,
        task=task,
        tick=tick,
        node=NodeName.ANTERIOR_CINGULATE,
        output=MonitorVerdict(tick=tick, unit_id="u-fixture", match=True, traps=traps),
    )
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"{paths_module.JOURNAL_PREFIX}{tick}{paths_module.JOURNAL_SUFFIX}"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry.model_dump(mode="json"), separators=(",", ":")) + "\n")


def planner_journal(
    state_dir: Path, *, task: str, tick: int, goal_id: str = GOAL_ID, unit_id: str = UNIT_ID
) -> None:
    """One tick's journal carrying the planner's own answer — a compiled habit's `result`."""
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / f"{paths_module.JOURNAL_PREFIX}{tick}{paths_module.JOURNAL_SUFFIX}").write_text(
        json.dumps(
            {
                "schema_version": config.JOURNAL_SCHEMA_VERSION,
                "task": task,
                "tick": tick,
                "node": str(NodeName.CORTEX),
                "tier": str(Tier.MANAGER),
                "output": planner_plan(tick, goal_id=goal_id, unit_id=unit_id),
                "envelope": None,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def patch_goal_stack(state_dir: Path, *, goal_id: str, text: str) -> None:
    """Put one open goal on a written run's checkpoint — `write_run` writes no goal stack."""
    checkpoint = state_dir / "checkpoint.json"
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    payload["state"]["goals"] = [
        {
            "id": goal_id,
            "text": text,
            "status": "open",
            "opened_at_tick": 0,
            "last_progress_tick": 0,
        }
    ]
    checkpoint.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def drop_weight_key(brain: BrainPaths, *, node: str, key: str) -> None:
    """Remove one key from a node's `weights.yaml` — the absent-key arm's only preparation."""
    path = brain.node_weights(node)
    kept = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.startswith(f"{key}:")
    ]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def habit_run(
    tmp_path: Path,
    brain,
    *,
    name: str,
    ticks=(1, 3),
    matched: bool = True,
    project: str | None = None,
    journal_ticks=(1, 3),
) -> Path:
    """An archive-shaped run whose checkpoint carries the goal stack and whose journal carries
    the planner's own answer — neither of which `tests.sleep.write_run` writes."""
    pairs = [planner_pair(tick=tick, matched=matched) for tick in ticks]
    directory = write_run(
        tmp_path / name,
        brain=brain,
        records=flatten(pairs),
        task=CURRENT_TASK,
        tick=max(ticks) + 1,
        units=[unit(UNIT_ID, goal_id=GOAL_ID)],
        project=project,
    )
    state_dir = directory / "state"
    patch_goal_stack(state_dir, goal_id=GOAL_ID, text=GOAL_TEXT)
    for tick in journal_ticks:
        planner_journal(state_dir, task=CURRENT_TASK, tick=tick)
    return directory


def phase_input(
    brain, directory: Path, *, dry_run: bool = False, verify: bool = True
) -> PhaseInput:
    """What `protean.sleep.run` hands a phase, assembled the way it assembles it.

    `verify=False` leaves `seed_hashes` empty rather than verified, which is what the procedures
    phase wants: it reads none of them, and a fixture run taken over the real archive is under
    seeds this checkout's tree no longer holds.
    """
    records = load_archived_run(directory)
    return PhaseInput(
        brain=brain,
        records=records,
        pairs=admissible_set(records),
        seed_hashes=verify_seeds(brain, records) if verify else {},
        sleep_id=SLEEP_ID,
        dry_run=dry_run,
    )


# --------------------------------------------------------------------------------------
# The pair vocabulary — one entry per shape an arm may script
# --------------------------------------------------------------------------------------


def _hippocampus(*, tick: int, matched: bool, task: str, empty: bool) -> list[TraceRecord]:
    """A `hippocampus_citation` pair. `empty` makes it *vacuous*: `matched` on no retrieval."""
    ids = [] if empty else [f"e-{tick}"]
    record = prediction(
        node=NodeName.HIPPOCAMPUS,
        payload=HippocampusPrediction(episode_ids=ids),
        task=task,
        tick=tick,
    )
    cited = ids if matched else []
    return [record, outcome(record, HippocampusOutcome(cited_episode_ids=cited, matched=matched))]


def _monitor(*, tick: int, matched: bool, task: str) -> list[TraceRecord]:
    """A `monitor_next_verdict` pair — the signal funding the six detector thresholds."""
    return list(monitor_pair(tick=tick, matched=matched, task=task))


def _planner(*, tick: int, matched: bool, task: str, unit_id: str) -> list[TraceRecord]:
    """A `manager_horizon` pair — the cortex signal a habit candidate is grouped from."""
    return list(planner_pair(tick=tick, matched=matched, task=task, unit_id=unit_id))


def _executor(
    *, tick: int, matched: bool, task: str, unit_id: str, vacuous: bool
) -> tuple[list[TraceRecord], WorkUnit, ExecutorSummary]:
    """An `dispatch_expectations` pair, in one of D5-2's two disjoint exclusion shapes.

    `vacuous` — every predicate withheld, so the verdict rests on no evidence at all.
    Otherwise — one withheld beside one graded, which is run 1's own *ungradeable* shape.
    """
    codeless = Expectation(
        id=f"{unit_id}-codeless",
        kind=ExpectationKind.EXIT_CODE,
        arguments={"command": "git rev-parse --abbrev-ref HEAD", "value": 0},
    )
    graded = Expectation(
        id=f"{unit_id}-file",
        kind=ExpectationKind.FILE_EXISTS,
        arguments={"path": "a planning record (not in this mirror)"},
    )
    expectations = [codeless] if vacuous else [codeless, graded]
    subject = WorkUnit(
        id=unit_id,
        goal_id="g1",
        intent=f"the fixture unit {unit_id}",
        expected=list(expectations),
    )
    record = prediction(
        node=NodeName.CORTEX,
        payload=DispatchPrediction(
            unit_id=unit_id, expectation_ids=[row.id for row in expectations]
        ),
        task=task,
        tick=tick,
        tier=CallType.DISPATCH,
    )
    graded_record = outcome(
        record,
        DispatchOutcome(verdict_match=matched, failed_predicate_ids=[], matched=matched),
    )
    observed = [] if vacuous else ["a planning record (not in this mirror)"]
    return (
        [record, graded_record],
        subject,
        ExecutorSummary(
            tick=tick,
            unit_id=unit_id,
            narrative="the fixture executor's account",
            observations=[
                {"path": path, "exists": True, "size_bytes": 1, "content_hash": "h"}
                for path in observed
            ],
            expectation_values={},
        ),
    )


# --------------------------------------------------------------------------------------
# Building the arm on disk
# --------------------------------------------------------------------------------------


def _write_memory_line(brain: BrainPaths, row: Mapping[str, Any]) -> None:
    """One prior sleep run's P4 pair line, appended where this run's window reads it."""
    memory_line(
        brain,
        node=NodeName(row["node"]),
        signal=row["signal"],
        ref=row["ref"],
        slug=row.get("project", paths_module.ROOT_PROJECT_SLUG),
        sleep_id=row.get("sleep_id", EARLIER_SLEEP_ID),
        task=row.get("task", EARLIER_TASK),
        tick=row.get("tick", 1),
        key=row.get("key"),
        matched=row.get("matched", True),
        admissible=row.get("admissible", True),
        excluded_reason=row.get("excluded_reason", ""),
        consumed=row.get("consumed_by") or {},
    )


def _write_earlier_task(brain: BrainPaths, row: Mapping[str, Any]) -> None:
    """A window task's committed checkpoint and, optionally, its per-tick journals.

    The loosening arm reads both: the terminal decides S-16's every-task-done clause and the
    journals decide the confirmation count, and an unreadable run is never read as favourable.
    """
    task_id = row["task"]
    checkpoint = brain.task(task_id).checkpoint
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(
        json.dumps(
            {
                "schema_version": config.CHECKPOINT_SCHEMA_VERSION,
                "state": {
                    "task_id": task_id,
                    "tick": row.get("tick", 1),
                    "terminal": row.get("terminal", "done"),
                },
                "seed_hashes": {},
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    for entry in row.get("monitor_journals") or []:
        monitor_journal(
            brain.task(task_id).state_dir,
            task=task_id,
            tick=entry["tick"],
            fired=entry.get("fired"),
        )


def _write_hit(brain: BrainPaths, row: Mapping[str, Any]) -> None:
    """One P3 line, in the eight fields `protean.state.habit_hits` names."""
    task = row.get("task", CURRENT_TASK)
    path = brain.task(task).habit_hits
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "schema_version": config.HABIT_HIT_SCHEMA_VERSION,
                    "task": task,
                    "tick": row["tick"],
                    "tier": row.get("tier", str(Tier.MANAGER)),
                    "ref": row["ref"],
                    "procedure_id": row["procedure_id"],
                    "matched_condition": dict(row.get("matched_condition") or {}),
                    "avoided_model": row.get("avoided_model", ""),
                },
                separators=(",", ":"),
            )
            + "\n"
        )


def materialise(name: str, tmp_path: Path, repo_root: Path) -> tuple[BrainPaths, Path]:
    """Build one arm's throwaway brain root and its archive-shaped run directory.

    Never the repo's own `brain/`: refusal 2 is live on this checkout (run 1 is paused), and an
    applied update that reached the tracked tree would move a number the operator set.
    """
    spec = load_arm(name)
    brain = seeded_brain(tmp_path, repo_root)
    run = spec.get("run") or {}
    setup = spec.get("brain") or {}

    for row in setup.get("drop_weight_keys") or []:
        drop_weight_key(brain, node=row["node"], key=row["key"])
    if setup.get("seeds"):
        brain.seeds.write_text(setup["seeds"], encoding="utf-8")

    task = run.get("task", CURRENT_TASK)
    goal_id = run.get("goal_id", f"{task}-g1")
    records: list[TraceRecord] = []
    units: list[WorkUnit] = []
    summaries: dict[int, ExecutorSummary] = {}
    for row in run.get("pairs") or []:
        kind = row["kind"]
        tick, matched = row["tick"], row.get("matched", True)
        row_task = row.get("task", task)
        if kind == "hippocampus_citation":
            records.extend(
                _hippocampus(tick=tick, matched=matched, task=row_task, empty=False)
            )
        elif kind == "hippocampus_vacuous":
            records.extend(
                _hippocampus(tick=tick, matched=matched, task=row_task, empty=True)
            )
        elif kind == "monitor_next_verdict":
            records.extend(_monitor(tick=tick, matched=matched, task=row_task))
        elif kind == "manager_horizon":
            records.extend(
                _planner(
                    tick=tick,
                    matched=matched,
                    task=row_task,
                    unit_id=row.get("unit", "u-1"),
                )
            )
        elif kind in ("executor_ungradeable", "executor_vacuous"):
            pair, subject, executor_summary = _executor(
                tick=tick,
                matched=matched,
                task=row_task,
                unit_id=row.get("unit", "u-1"),
                vacuous=kind == "executor_vacuous",
            )
            records.extend(pair)
            units.append(subject)
            summaries[tick] = executor_summary
        else:  # pragma: no cover - an arm naming a shape the vocabulary does not carry
            raise AssertionError(f"{name}: unknown pair kind {kind!r}")

    for row in run.get("units") or []:
        units.append(
            WorkUnit(
                id=row["id"],
                goal_id=goal_id,
                intent=row.get("intent", f"the fixture unit {row['id']}"),
                expected=[],
            )
        )

    directory = write_run(
        tmp_path / "run",
        brain=brain,
        records=records,
        task=task,
        tick=run.get("final_tick", 1),
        terminal=run.get("terminal", "done"),
        units=units,
        summaries=summaries,
        seeds=None if run.get("seed_hashes", "live") == "live" else {},
        project=run.get("project"),
    )
    state_dir = directory / "state"

    if run.get("goal"):
        patch_goal_stack(state_dir, goal_id=goal_id, text=run["goal"])
    for tick in run.get("planner_journals") or []:
        planner_journal(
            state_dir, task=task, tick=tick, goal_id=goal_id, unit_id=run.get("unit", UNIT_ID)
        )
    for entry in run.get("monitor_journals") or []:
        monitor_journal(
            state_dir, task=task, tick=entry["tick"], fired=entry.get("fired")
        )

    for row in setup.get("memory") or []:
        _write_memory_line(brain, row)
    for row in setup.get("tasks") or []:
        _write_earlier_task(brain, row)
    for procedure_id in setup.get("procedures") or []:
        destination = brain.node_procedures(config.CORTEX_NODE)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / f"{procedure_id}.yaml").write_bytes(
            procedure_fixture(name, procedure_id).read_bytes()
        )
    for row in setup.get("hits") or []:
        _write_hit(brain, row)

    return brain, directory


def run_arm(name: str, tmp_path: Path, repo_root: Path) -> tuple[SleepOutcome, BrainPaths, Path]:
    """Materialise one arm and sleep on it under the pinned clock."""
    brain, directory = materialise(name, tmp_path, repo_root)
    result = run_sleep(
        brain,
        source=directory,
        report_dir=tmp_path / "reports",
        now=SLEEP_NOW,
    )
    return result, brain, directory


# --------------------------------------------------------------------------------------
# Normalisation — the two things in an artifact that are environment rather than rule
# --------------------------------------------------------------------------------------


def substitutions(result: SleepOutcome, brain: BrainPaths, directory: Path) -> list[tuple[str, str]]:
    """What `normalise()` replaces, longest literal first so no prefix eats another.

    The seed hashes are taken from the report's own verified map, so the placeholder names the
    file each hash covers: an applied update that carried some *other* node's hash would
    normalise to a different string and fail the byte comparison.
    """
    rows = [
        (str(directory), SOURCE_PLACEHOLDER),
        (str(brain.root), BRAIN_PLACEHOLDER),
    ]
    for relative, digest in result.report.source.seed_hashes.items():
        rows.append((digest, f"{SEED_PLACEHOLDER}{relative}"))
    return sorted(rows, key=lambda row: len(row[0]), reverse=True)


def normalise(text: str, rows: Sequence[tuple[str, str]]) -> str:
    """Substitute every environment-specific literal for its placeholder."""
    for literal, placeholder in rows:
        text = text.replace(literal, placeholder)
    return text


def report_text(result: SleepOutcome, rows: Sequence[tuple[str, str]]) -> str:
    """The report as its own writer writes it, normalised — what `expected/report.json` holds."""
    return normalise(
        json.dumps(result.report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        rows,
    )


def brain_text(path: Path, rows: Sequence[tuple[str, str]]) -> str:
    """One produced file's bytes, normalised — what `expected/brain/<relative>` holds."""
    return normalise(path.read_text(encoding="utf-8"), rows)


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------


@pytest.fixture()
def brain(tmp_path: Path, repo_root: Path) -> BrainPaths:
    """A throwaway brain root carrying the tracked seed tree's node folders and nothing else.

    Function-scoped on purpose, and the six modules that each declared this fixture for
    themselves all relied on that: every consumer writes into the root it is handed — an applied
    update, a compiled procedure, a trimmed `weights.yaml`, an appended memory line — so a shared
    root would carry one test's end state into the next one's premise.
    """
    return seeded_brain(tmp_path, repo_root)


@pytest.fixture(scope="session")
def trace_fixtures() -> Path:
    """`fixtures/traces/` — one directory per rule arm."""
    return TRACES


@pytest.fixture(scope="session")
def procedure_fixtures() -> Path:
    """`fixtures/procedures/` — the byte-expected compiled-habit files."""
    return PROCEDURES
