"""Loading a run's records, the `ref` join, and Deliverable 1's admissibility classification.

`the build specification (not in this mirror)` § Deliverable 1 (the admissible-set table and the paragraph
beneath it), § Deliverable 2 (the read set: an archive directory, or the live node folders plus
the root's most recent **committed** task), § Directional decisions 18 and 22, § Resolutions
A1-8, A1-13, D3-1, D3-2, D3-3.

**The classification lives here, in the learner, and never in `outcomes.py`** (folded: A1-8).
The grader keeps recording what happened, so the archive's existing outcome records stay
reproducible by the current code; this module decides what a *learner* may consume from them.
That is also why the four tests read the run's own artifacts rather than re-grading anything:
nothing below writes, and nothing below produces a second verdict.

**The four tests, in the table's order** (decision 18):

1. **joined** — both records committed, and the outcome's `ref` equals the prediction's
   `prediction_key()`. A prediction no outcome claims, and an outcome whose `ref` names no
   committed prediction, are both `unjoined`.
2. **on the list** — the signal is one of `config.ADMISSIBLE_SIGNALS`. `operator_answer` outcomes are
   `off-list`: `OperatorAnswerOutcome` deliberately declines to put a verdict on the node that asked
   (`runtime/outcomes.py`'s module docstring), so it is evidence for the operator and not for a learner.
3. **gradeable** — the verdict came from evidence **present**, not from its absence (D16-4).
4. **non-vacuous** — the verdict is not independent of what the node did (folded: A1-13).

**Tests 3 and 4 read order W1's verdict rather than making a second one** (D3-2, D3-3). The two
pure predicates `protean.nodes.anterior_cingulate.ungradeable()` and `withheld_from_verdict()`
are called directly, over the unit's `expected` list off the run's checkpoint and the tick's
`ExecutorSummary` off its journal — the same two arguments the monitor evaluated. Only
`dispatch_expectations` can fire either arm, because D16-4's class is the *predicate*-absence
class and that is the one signal whose grade rests on predicates. The three vacuous cases the
SPEC names directly — an empty `episode_ids`, an empty `admitted_ids`, a `gate_unit_survives`
prediction whose `unit_id` is `NO_SUBJECT` — are read off the prediction payload itself.

**This is what keeps run 1's three-tick repeat from compiling** (§ Build process, "Legs 1 and 5
are the same argument from both ends"). The archive's `e-branch-1` and `e-branch-3` are
`exit_code` predicates with no `code` argument, so every executor pair on ticks 2–4 is excluded
here — before a candidate can form, rather than by a threshold tuned afterwards.

**Nothing here is written and nothing is pruned.** The archive is read-only to sleep (row N8):
every path below is opened for reading, and the loader never creates a directory.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from protean import config
from protean.brain.jsonl import read_lines
from protean.nodes.anterior_cingulate import ungradeable, withheld_from_verdict
from protean.runtime import paths as paths_module
from protean.runtime.paths import BrainPaths, CHECKPOINT_FILENAME
from protean.runtime.predictions import NO_SUBJECT
from protean.state.enums import NodeName, TerminalState, TraceKind
from protean.state.errors import SchemaVersionMismatch
from protean.state.primitives import Expectation, WorkUnit
from protean.state.records import TraceRecord
from protean.state.seats import ExecutorSummary

#: The artifact name a refusal quotes when a run's checkpoint is a version this code cannot read.
CHECKPOINT_ARTIFACT: Final[str] = "checkpoint"

#: Where an archive keeps the three things this module reads. `--from` names the directory that
#: holds them; `protean.runtime.archive` is what put them there and is read-only to sleep.
ARCHIVE_NODES_DIRNAME: Final[str] = "nodes"
ARCHIVE_STATE_DIRNAME: Final[str] = "state"

#: The trace filename inside a node folder, archived or live. Named here rather than imported
#: from `runtime.paths`, whose accessor takes a task id an archive does not have.
TRACE_FILENAME: Final[str] = "trace.jsonl"

#: The `BrainState.extensions` namespace a task's project slug is carried in (decision 22).
#: Read here, written by order W5; a checkpoint without it reads as the `_root` slug, which is
#: exactly run 1's case.
PROJECT_EXTENSION: Final[str] = "project"
PROJECT_SLUG_FIELD: Final[str] = "slug"


class RunUnreadable(ValueError):
    """A `--from` directory, or a brain root, that carries no run this verb can read."""


# --------------------------------------------------------------------------------------
# What one run puts on disk
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunRecords:
    """One run as sleep reads it — archived or live, the same shape either way.

    `predictions` and `outcomes` are flat rather than per folder because the join is by `ref`
    and a `ref` already names its node; the folder is kept on each record.
    """

    #: `--from`'s directory, or the brain root the live traces came from.
    source: str
    task: str
    terminal: TerminalState | None
    project: str
    ticks: int
    #: `{brain-root-relative path: sha256}` as the run's checkpoint recorded them. Sleep
    #: re-hashes these before deriving one update (decision 17); it never trusts them.
    seed_hashes: Mapping[str, str]
    predictions: tuple[TraceRecord, ...]
    outcomes: tuple[TraceRecord, ...]
    #: `BrainState.units`, by id — where a unit's `expected` predicates live.
    units: Mapping[str, WorkUnit]
    #: tick → that tick's `ExecutorSummary`, off the journal's cortex entry.
    summaries: Mapping[int, ExecutorSummary]

    def unit(self, unit_id: str) -> WorkUnit | None:
        return self.units.get(unit_id)

    def summary(self, tick: int) -> ExecutorSummary | None:
        return self.summaries.get(tick)

    def recorded_weights_files(self) -> tuple[str, ...]:
        """Every `nodes/<node>/weights.yaml` key this run's checkpoint recorded, sorted.

        The subject of refusal 2 and of the seed verification alike: § Deliverable 2 is explicit
        that "every `weights.yaml` is in `seed_hashes()`", so this is the intersection of what
        was recorded with what sleep could write, never a hand-kept list.
        """
        wanted = {
            f"{ARCHIVE_NODES_DIRNAME}/{node}/weights.yaml"
            for node in config.WEIGHTS_WRITABLE_NODES
        }
        return tuple(sorted(key for key in self.seed_hashes if key in wanted))


def _read_checkpoint(path: Path) -> dict[str, Any]:
    """One `checkpoint.json`, refusing a version this code does not write.

    Deliberately **not** `protean.state.checkpoint.load_checkpoint()`: that is the resume
    ladder, whose seed-hash arm is the very thing sleep runs for itself (step 6) and whose
    extension arm would refuse an archived checkpoint written by a later build's registry.
    Sleep reads a run it did not produce, so it checks the two versions and the shape.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    found = int(payload.get("schema_version", -1))
    if found != config.CHECKPOINT_SCHEMA_VERSION:
        raise SchemaVersionMismatch(
            artifact=CHECKPOINT_ARTIFACT,
            found=found,
            expected=config.CHECKPOINT_SCHEMA_VERSION,
        )
    return payload


def _project_of(state: Mapping[str, Any]) -> str:
    """The task's own slug (decision 22), `_root` when the extension carries none."""
    extensions = state.get("extensions") or {}
    block = extensions.get(PROJECT_EXTENSION) if isinstance(extensions, Mapping) else None
    if isinstance(block, Mapping):
        # The runtime registers a `ProjectExtension` — `{name, version, payload: {slug}}` —
        # because the frozen model forbids an extra field (engine.project_extension, D10-7);
        # a hand-written fixture may carry the flat shape. Both are the same slug.
        payload = block.get("payload")
        if isinstance(payload, Mapping):
            slug = payload.get(PROJECT_SLUG_FIELD)
            if isinstance(slug, str) and slug:
                return slug
        slug = block.get(PROJECT_SLUG_FIELD)
        if isinstance(slug, str) and slug:
            return slug
    if isinstance(block, str) and block:
        return block
    return paths_module.ROOT_PROJECT_SLUG


def _trace_records(path: Path) -> tuple[list[TraceRecord], list[TraceRecord]]:
    """One folder's committed predictions and outcomes, parsed."""
    predictions: list[TraceRecord] = []
    outcomes: list[TraceRecord] = []
    for line in read_lines(path):
        record = TraceRecord.model_validate(line)
        if record.kind is TraceKind.PREDICTION:
            predictions.append(record)
        else:
            outcomes.append(record)
    return predictions, outcomes


def _summaries_from(journals: Iterable[Path]) -> dict[int, ExecutorSummary]:
    """tick → `ExecutorSummary`, off each journal's cortex entry.

    The summary is what the monitor's evaluator was handed, so it is the second argument of
    both of order W1's predicates. A tick whose cortex entry is a different tier — or a null
    entry, which a refused seat call writes — contributes nothing and simply is not here.
    """
    found: dict[int, ExecutorSummary] = {}
    for journal in journals:
        for line in read_lines(journal):
            if str(line.get("node")) != str(NodeName.CORTEX):
                continue
            output = line.get("output")
            if not isinstance(output, Mapping):
                continue
            if str(output.get("emitter")) != "dispatch":
                continue
            found[int(line.get("tick", -1))] = ExecutorSummary.model_validate(output)
    return found


def _journal_paths(state_dir: Path) -> list[Path]:
    """Every `journal-<tick>.jsonl` under one state directory, ascending by tick."""
    if not state_dir.is_dir():
        return []
    prefix, suffix = paths_module.JOURNAL_PREFIX, paths_module.JOURNAL_SUFFIX
    found = [
        path
        for path in state_dir.iterdir()
        if path.is_file() and path.name.startswith(prefix) and path.name.endswith(suffix)
    ]
    return sorted(found, key=lambda path: int(path.name[len(prefix) : -len(suffix)]))


def _assemble(
    *, source: str, checkpoint_path: Path, state_dir: Path, node_root: Path
) -> RunRecords:
    """The one reader both `--from` and the live root resolve to."""
    payload = _read_checkpoint(checkpoint_path)
    state = payload.get("state") or {}
    predictions: list[TraceRecord] = []
    outcomes: list[TraceRecord] = []
    for node in config.NODE_ORDER:
        trace = node_root / node / TRACE_FILENAME
        if not trace.is_file():
            continue
        folder_predictions, folder_outcomes = _trace_records(trace)
        predictions.extend(folder_predictions)
        outcomes.extend(folder_outcomes)
    units = {
        str(row.get("id")): WorkUnit.model_validate(row)
        for row in state.get("units") or []
        if isinstance(row, Mapping)
    }
    terminal = state.get("terminal")
    return RunRecords(
        source=source,
        task=str(state.get("task_id", "")),
        terminal=None if terminal is None else TerminalState(str(terminal)),
        project=_project_of(state),
        ticks=int(state.get("tick", 0)),
        seed_hashes=dict(payload.get("seed_hashes") or {}),
        predictions=tuple(predictions),
        outcomes=tuple(outcomes),
        units=units,
        summaries=_summaries_from(_journal_paths(state_dir)),
    )


def load_archived_run(directory: Path) -> RunRecords:
    """A `brain/archive/workload-run-*/` directory — the default source and the read-only-safe one.

    Read, never written and never pruned: it is the only copy of build 3's whole input
    (`DIGEST` A1-17, row N8).
    """
    state_dir = directory / ARCHIVE_STATE_DIRNAME
    checkpoint = state_dir / CHECKPOINT_FILENAME
    if not checkpoint.is_file():
        raise RunUnreadable(
            f"{directory} holds no {ARCHIVE_STATE_DIRNAME}/{CHECKPOINT_FILENAME} — "
            f"`--from` names an archived run directory, not a brain root"
        )
    return _assemble(
        source=str(directory),
        checkpoint_path=checkpoint,
        state_dir=state_dir,
        node_root=directory / ARCHIVE_NODES_DIRNAME,
    )


def most_recent_committed_task(brain: BrainPaths) -> str:
    """The root's most recent committed task — the live read set (folded: S-11).

    "The open task" is a subject no task may hold while sleep runs: refusal 1 has already
    refused a task in flight by the time this is called, so the most recent committed one is
    the newest task id with a checkpoint. Task ids are minted from the UTC clock, so sorted
    order is chronological.
    """
    task_ids = brain.task_ids()
    if not task_ids:
        raise RunUnreadable(
            f"no task is checkpointed under {brain.root} — "
            f"`sleep` reads a run, and this root has none"
        )
    return task_ids[-1]


def load_live_run(brain: BrainPaths, task_id: str | None = None) -> RunRecords:
    """The live node folders' `trace.jsonl` plus one committed task's state directory."""
    resolved = task_id or most_recent_committed_task(brain)
    task = brain.task(resolved)
    return _assemble(
        source=str(brain.root),
        checkpoint_path=task.checkpoint,
        state_dir=task.state_dir,
        node_root=brain.root / ARCHIVE_NODES_DIRNAME,
    )


# --------------------------------------------------------------------------------------
# The join and the four tests
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Pair:
    """One (prediction, outcome) pair, joined by `ref`, admissible or not.

    `excluded_reason` is empty exactly when `admissible` is true — the two are one fact stated
    twice because the report counts one way and the floor reads the other.
    """

    ref: str
    signal: str
    node: NodeName
    task: str
    tick: int
    project: str
    matched: bool
    admissible: bool
    excluded_reason: str = ""
    prediction: TraceRecord | None = None
    outcome: TraceRecord | None = None


@dataclass(frozen=True, slots=True)
class AdmissibleSet:
    """Every pair the run offered, split by the four tests, and counted by reason."""

    pairs: tuple[Pair, ...] = ()
    #: The run these pairs came from, so a caller never re-derives the task or the slug.
    project: str = ""
    task: str = ""
    _counts: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def admissible(self) -> tuple[Pair, ...]:
        return tuple(pair for pair in self.pairs if pair.admissible)

    @property
    def excluded(self) -> tuple[Pair, ...]:
        return tuple(pair for pair in self.pairs if not pair.admissible)

    def by_reason(self) -> dict[str, int]:
        """Reason → count, every reason in `config.SLEEP_EXCLUSION_REASONS` present at zero."""
        counts = {reason: 0 for reason in config.SLEEP_EXCLUSION_REASONS}
        for pair in self.excluded:
            counts[pair.excluded_reason] = counts.get(pair.excluded_reason, 0) + 1
        return counts

    def signals(self) -> list[str]:
        """Every signal seen, the eight admissible ones first and in their own order."""
        seen = {pair.signal for pair in self.pairs}
        ordered = [name for name in config.ADMISSIBLE_SIGNALS if name in seen]
        return ordered + sorted(seen - set(ordered))

    def for_signal(self, signal: str) -> tuple[Pair, ...]:
        return tuple(pair for pair in self.pairs if pair.signal == signal)


def _signal_of(record: TraceRecord | None, *, prediction: TraceRecord | None = None) -> str:
    """The signal a pair is filed under — the **outcome's**, falling back to the prediction's.

    The outcome's, because the outcome is the thing a learner consumes and because it is the
    outcome side that carries `operator_answer`: a synthetic `director_progress` prediction answered
    by the operator joins cleanly and must still land `off-list`.
    """
    for candidate in (record, prediction):
        if candidate is None:
            continue
        payload = candidate.outcome if candidate.outcome is not None else candidate.prediction
        signal = getattr(payload, "signal", "")
        if signal:
            return str(signal)
    return ""


def _expectations_of(unit: WorkUnit, wanted: Sequence[str]) -> list[Expectation]:
    """The unit's predicates the prediction named, or all of them when it named none."""
    if not wanted:
        return list(unit.expected)
    named = set(wanted)
    return [item for item in unit.expected if item.id in named]


def _predicate_verdict(prediction: TraceRecord, records: RunRecords) -> str:
    """Tests 3 and 4 for `dispatch_expectations`, read off order W1's own two predicates.

    Returns an exclusion reason, or `""` when the pair passes both.

    * every predicate withheld from the verdict — or no predicate at all — is **vacuous**: the
      unit grades `match: true` on no evidence, which is A1-13's class exactly (D3-2);
    * any predicate whose grade came from an *absence* while another graded is **ungradeable**:
      the verdict is part evidence and part absence, which is not "graded from evidence present"
      (D16-4). `ungradeable()` is the wide predicate on purpose — it mirrors all five evaluator
      arms, while `withheld_from_verdict()` narrows to the one arm repair (b) changed (D3-3), and
      the learner's question is the wide one.

    A pair whose unit or whose tick summary is not in the run's records is **ungradeable** too:
    the classifier cannot establish that the verdict came from evidence present, and admitting
    it would be exactly the silent assumption § Named assumptions 1 warns about.
    """
    payload = prediction.prediction
    unit = records.unit(getattr(payload, "unit_id", ""))
    summary = records.summary(prediction.tick)
    if unit is None or summary is None:
        return config.EXCLUSION_UNGRADEABLE
    expectations = _expectations_of(unit, getattr(payload, "expectation_ids", ()))
    if not expectations:
        return config.EXCLUSION_VACUOUS
    withheld = [item for item in expectations if withheld_from_verdict(item, summary)]
    if len(withheld) == len(expectations):
        return config.EXCLUSION_VACUOUS
    if any(ungradeable(item, summary) for item in expectations):
        return config.EXCLUSION_UNGRADEABLE
    return ""


def _vacuity(prediction: TraceRecord) -> str:
    """The three vacuous cases § Deliverable 1 names outright, off the prediction payload.

    "An empty `episode_ids` / `admitted_ids` set, or a `gate_unit_survives` prediction whose
    `unit_id` is `NO_SUBJECT`, scores a match on no evidence and is excluded" — each of them a
    grade that could not have come out any other way, whatever the node did.
    """
    payload = prediction.prediction
    signal = str(getattr(payload, "signal", ""))
    if signal == "hippocampus_citation" and not payload.episode_ids:
        return config.EXCLUSION_VACUOUS
    if signal == "thalamus_citation" and not payload.admitted_ids:
        return config.EXCLUSION_VACUOUS
    if signal == "gate_unit_survives" and payload.unit_id == NO_SUBJECT:
        return config.EXCLUSION_VACUOUS
    return ""


def classify(prediction: TraceRecord, outcome: TraceRecord, records: RunRecords) -> str:
    """The four tests over one joined pair, in the table's order. `""` means admissible.

    Test 1 is already true of the arguments — a caller reaches this only with a pair the join
    matched — so this is tests 2, 3 and 4.
    """
    signal = _signal_of(outcome, prediction=prediction)
    if signal not in config.ADMISSIBLE_SIGNALS:
        return config.EXCLUSION_OFF_LIST
    if signal == "dispatch_expectations":
        return _predicate_verdict(prediction, records)
    return _vacuity(prediction)


def admissible_set(records: RunRecords) -> AdmissibleSet:
    """Join every record by `ref`, classify each pair, and count every exclusion by reason.

    Both orphan halves are counted: a prediction no outcome claims and an outcome whose `ref`
    names no committed prediction are each `unjoined`, because test 1 asks that **both** records
    be committed. An ungraded horizon prediction is the ordinary case of the first — run 1's
    planner prediction is still open, which is why § Build process leg 7 orders the resume first.
    """
    by_key = {record.prediction_key(): record for record in records.predictions}
    claimed: set[str] = set()
    pairs: list[Pair] = []

    for outcome in records.outcomes:
        ref = str(outcome.ref)
        prediction = by_key.get(ref)
        if prediction is None:
            pairs.append(
                Pair(
                    ref=ref,
                    signal=_signal_of(outcome),
                    node=outcome.node,
                    task=outcome.task,
                    tick=outcome.tick,
                    project=records.project,
                    matched=bool(getattr(outcome.outcome, "matched", False)),
                    admissible=False,
                    excluded_reason=config.EXCLUSION_UNJOINED,
                    outcome=outcome,
                )
            )
            continue
        claimed.add(ref)
        reason = classify(prediction, outcome, records)
        pairs.append(
            Pair(
                ref=ref,
                signal=_signal_of(outcome, prediction=prediction),
                node=prediction.node,
                task=prediction.task,
                tick=prediction.tick,
                project=records.project,
                matched=bool(getattr(outcome.outcome, "matched", False)),
                admissible=not reason,
                excluded_reason=reason,
                prediction=prediction,
                outcome=outcome,
            )
        )

    for key, prediction in by_key.items():
        if key in claimed:
            continue
        pairs.append(
            Pair(
                ref=key,
                signal=_signal_of(prediction),
                node=prediction.node,
                task=prediction.task,
                tick=prediction.tick,
                project=records.project,
                matched=False,
                admissible=False,
                excluded_reason=config.EXCLUSION_UNJOINED,
                prediction=prediction,
            )
        )

    pairs.sort(key=lambda pair: (pair.tick, str(pair.node), pair.ref))
    return AdmissibleSet(pairs=tuple(pairs), project=records.project, task=records.task)


__all__ = [
    "AdmissibleSet",
    "Pair",
    "RunRecords",
    "RunUnreadable",
    "admissible_set",
    "classify",
    "load_archived_run",
    "load_live_run",
    "most_recent_committed_task",
]
