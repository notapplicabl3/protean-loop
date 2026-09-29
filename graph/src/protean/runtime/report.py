"""The run report writer: every number in `WorkloadRunReport`, derived from what is on disk.

`the build specification (not in this mirror)` § Deliverable 6 → *S6 — `WorkloadRunReport`*, § Rulings 6 and 16,
§ Named assumptions 2, § Resolutions S-19, S-27, S-43, and § DoD row W8.

**Derived, never held.** Row W8's binding half is that no count, ratio or tier total is a
literal anywhere in the build. So this module owns no number: it owns six *readings* of files
the run already wrote, and each one names the file it read.

| group | read from |
|---|---|
| detector telemetry | the per-tick journals' `MonitorVerdict.traps`, and the cortex `trace.jsonl`'s manager-tier `trap_dismissed` |
| seat economics | `seat_calls.jsonl`, through `spend_tokens()` and `cache_reads()` (folded: S-19) |
| mismatch | `seat_calls.jsonl`'s `outcome`, against the journals' `MonitorVerdict.match` |
| versions | `seat_calls.jsonl`'s `cli_version` (§ Rulings 16) |
| request bytes | the per-tick journals' seat-call entries, serialized as the port serializes them (A.3 § Deliverable 4) |
| files | `git` in the clone, through `protean.runtime.archive`'s seam |

and § Named assumptions 2's count is read from the same journals: the unit's `expected` against
the `ExecutorSummary` the tick produced.

**Why the journals rather than the episodes.** Both carry the tick's `MonitorVerdict`. The
journal is truncated and rewritten when a tick replays, so it holds the *surviving* verdict of
the tick as it finally ran; the episodes file is append-only and keyed, so a replay's record
no-ops on the first attempt's. For a receipt of what the run actually did, the replayed tick's
own verdict is the true one.

**Ungradeable is not the same as failed** (§ Named assumptions 2). `evaluate()` in
`protean.nodes.anterior_cingulate` returns a bool for every predicate — it has no third answer —
so a predicate the dispatch summary gave it no evidence for is graded anyway, and graded from an
absence. `ungradeable()` below is that absence, named: the four evidence shapes the evaluator
reads, each checked for presence rather than for value. It changes no verdict; it counts how
often the monitor was answering a question the summary had not addressed.

**The report is written into the task's state directory**, beside the checkpoints and
`seat_calls.jsonl`, so the archive picks it up with the rest of the state and no new path
constant is needed in `protean.runtime.paths` — which order W7 may not edit.

**Nothing here calls a model.** The one subprocess in the whole path is `git`, and it is spawned
in `protean.runtime.archive`.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from protean import config
from protean.nodes.vocabulary import (
    EXPECTATION_CODE,
    EXPECTATION_FIELD,
    EXPECTATION_PATH,
    EXPECTATION_VALUE,
)
from protean.runtime import journal, observations
from protean.runtime.archive import changed_files, is_repository_root
from protean.runtime.seat import IllegalReturn, decode_seat_result
from protean.runtime.paths import BrainPaths, TaskPaths
from protean.state.enums import (
    Addressee,
    CallType,
    ExpectationKind,
    NodeName,
    TerminalState,
    Tier,
    TrapDetector,
)
from protean.state.errors import SchemaVersionMismatch
from protean.state.outputs import MonitorVerdict
from protean.state.primitives import Expectation, WorkUnit
from protean.state.records import ManagerPrediction
from protean.state.run_report import (
    ARTIFACT,
    WorkloadRunReport,
    FileChange,
    SeatEconomics,
    SeatRequestBytes,
    TierMismatch,
    VersionSpread,
    detector_rows,
    load_run_report,
)
from protean.state.seat_calls import SeatCallRecord, load_seat_calls
from protean.state.seats import ExecutorSummary
from protean.brain.trace import committed_predictions

#: `brain/state/<task_id>/run_report.json`. Named here rather than in `protean.runtime.paths`,
#: which order W2 authored and this order may not edit (ledger entry V2-3).
REPORT_FILENAME: Final[str] = "run_report.json"

#: The CLI's own per-model cost field, as the captured envelope spells it
#: (`fixtures/envelopes/live-first.json`). A *key name*, never a rate: this build holds no
#: price, so the cost estimate is the binary's own number or it is zero.
COST_KEY: Final[str] = "costUSD"

#: The marker a session fallback leaves on a record's `error` (folded: S-43). It **restates**
#: `protean.cortex.live.invoke.RESUMED_AS_NEW` rather than importing it, for the same reason
#: `protean.state.seat_calls.SeatCallOutcome` restates the runtime's outcome set: the runtime
#: does not import the seat package. `tests/runtime/test_run_report.py` pins the two equal.
RESUMED_AS_NEW: Final[str] = "resumed_as_new"


#: The exact text a seat call puts on the child's stdin (A.3 § Deliverable 4). It **restates**
#: `protean.cortex.bodies.request_on_stdin` rather than importing it, for `RESUMED_AS_NEW`'s
#: reason: the runtime does not import the seat package.
#: `tests/runtime/test_run_report.py::test_G7_the_restated_serializer_is_the_port_s_own` pins
#: the two equal.
def request_on_stdin(payload: Mapping[str, Any]) -> str:
    """The port's serializer, restated: `json.dumps(dict(payload), ensure_ascii=False)`."""
    return json.dumps(dict(payload), ensure_ascii=False)


def report_path(paths: TaskPaths) -> Path:
    """Where this task's `WorkloadRunReport` lives."""
    return paths.state_dir / REPORT_FILENAME


# --------------------------------------------------------------------------------------
# Reading the run back off the tree
# --------------------------------------------------------------------------------------


def tick_verdicts(paths: TaskPaths) -> dict[int, MonitorVerdict]:
    """Every tick's `MonitorVerdict`, off the per-tick journals."""
    verdicts: dict[int, MonitorVerdict] = {}
    for tick in paths.journal_ticks():
        for entry in journal.load(paths.journal(tick)):
            if entry.node is NodeName.ANTERIOR_CINGULATE and isinstance(
                entry.output, MonitorVerdict
            ):
                verdicts[tick] = entry.output
    return verdicts


def tick_summaries(paths: TaskPaths) -> dict[int, ExecutorSummary]:
    """Every tick's `ExecutorSummary`, off the per-tick journals. A skipped seat has none.

    **Re-based by build A.1**: the act is a manager **dispatch wave**, and what a member
    returned lives on its call entry's envelope — the journal's half of C2 carries "the
    returned envelope", and the merged observation is committed state (§ Deliverable 4). So a
    pass's summary is the merge of that pass's members, computed on the one implementation.
    """
    summaries: dict[int, ExecutorSummary] = {}
    for tick in paths.journal_ticks():
        returns: list[tuple[int, ExecutorSummary | None]] = []
        for entry in journal.load(paths.journal(tick)):
            if entry.node is not NodeName.CORTEX:
                continue
            if isinstance(entry.output, ExecutorSummary):
                summaries[tick] = entry.output
            elif entry.tier is CallType.DISPATCH and entry.is_call():
                returns.append(
                    (
                        entry.member_number or 1,
                        None
                        if entry.envelope is None
                        else decode_seat_result(CallType.DISPATCH, entry.envelope, tick),
                    )
                )
        if returns:
            try:
                merged = observations.merge_wave(returns, tick=tick).summary
            except IllegalReturn:
                # A wave naming two units is an **illegal return, not a merge** (§ Deliverable 3)
                # — the tick loop completed that tick `stopped` with no summary, so it has none.
                continue
            if merged is not None:
                summaries[tick] = merged
    return summaries


def seat_request_bytes(paths: TaskPaths) -> list[SeatRequestBytes]:
    """One row per journalled seat call, off the per-tick journals (A.3 § Deliverable 4).

    A seat call is a cortex **call** entry addressed by a `Tier` — `director` or `manager` —
    answered or refused alike: a refusal is journalled with the request it was refused on, so a
    run that stops on a capped call still reports that call's bytes. The journal holds the
    payload as `request.model_dump(mode="json")`, the value the port serializes, so a row's bytes
    are what the seat's stdin carried on the call's first invocation. A call a habit answered is
    journalled like any other and yields a row too, though no process read it.
    """
    rows: list[SeatRequestBytes] = []
    for tick in paths.journal_ticks():
        for entry in journal.load(paths.journal(tick)):
            if entry.node is NodeName.CORTEX and entry.is_call() and isinstance(entry.tier, Tier):
                rows.append(
                    SeatRequestBytes(
                        tick=tick,
                        tier=entry.tier,
                        request_bytes=len(request_on_stdin(entry.payload).encode("utf-8")),
                    )
                )
    return rows


def committed_units(paths: TaskPaths) -> dict[str, WorkUnit]:
    """The task's units, by id, off the committed checkpoint.

    Only `expected` is read, so the units are validated on their own rather than through
    `load_checkpoint()`'s refusal ladder: that ladder re-hashes every seed file and re-checks
    every registered extension, which is the resume path's job and not a report's.
    """
    if not paths.checkpoint.exists():
        return {}
    payload = json.loads(paths.checkpoint.read_text(encoding="utf-8"))
    raw = (payload.get("state") or {}).get("units") or []
    units = [WorkUnit.model_validate(item) for item in raw]
    return {unit.id: unit for unit in units}


def manager_dismissals(paths: TaskPaths) -> Counter[TrapDetector]:
    """Every detector the manager dismissed, off the cortex folder's `trace.jsonl`.

    The manager's own prediction record carries `trap_dismissed` (`ManagerPrediction`), which is
    what makes this a count off one of the six trace files rather than off a seat's output.
    """
    counted: Counter[TrapDetector] = Counter()
    for record in committed_predictions(paths.trace(config.CORTEX_NODE)):
        if isinstance(record.prediction, ManagerPrediction):
            counted.update(record.prediction.trap_dismissed)
    return counted


def detector_fires(verdicts: Mapping[int, MonitorVerdict]) -> Counter[TrapDetector]:
    """Every fired scalar, counted once per `(tick, unit, detector)`."""
    counted: Counter[TrapDetector] = Counter()
    for verdict in verdicts.values():
        for scalar in verdict.traps:
            if scalar.fired:
                counted[scalar.detector] += 1
    return counted


# --------------------------------------------------------------------------------------
# § Named assumptions 2 — the predicates the evaluator could not grade
# --------------------------------------------------------------------------------------


def _observed(summary: ExecutorSummary, path: str) -> bool:
    """Whether the summary reported an observation at that path — the evidence, not its value."""
    return any(observation.path == path for observation in summary.observations)


def ungradeable(expectation: Expectation, summary: ExecutorSummary) -> bool:
    """Whether this predicate's grade came from missing evidence rather than from evidence.

    One arm per arm of `protean.nodes.anterior_cingulate.evaluate()`, asking *presence* where
    that function asks value. The arms are deliberately in the same order and read the same
    argument keys from `protean.nodes.vocabulary`, so a fifth predicate kind cannot be added to
    the evaluator without this function's default arm catching it.
    """
    arguments: Mapping[str, Any] = expectation.arguments
    if expectation.kind in (ExpectationKind.FILE_EXISTS, ExpectationKind.FILE_ABSENT):
        path = str(arguments.get(EXPECTATION_PATH, ""))
        return not path or not _observed(summary, path)
    if expectation.kind is ExpectationKind.FILE_CONTAINS:
        return (
            EXPECTATION_VALUE not in arguments
            or not isinstance(summary.expectation_values.get(expectation.id), str)
        )
    if expectation.kind is ExpectationKind.SUMMARY_FIELD_EQUALS:
        field = str(arguments.get(EXPECTATION_FIELD, ""))
        return not field or field not in summary.model_dump(mode="json")
    return EXPECTATION_CODE not in arguments


def ungradeable_count(
    units: Mapping[str, WorkUnit], summaries: Mapping[int, ExecutorSummary]
) -> int:
    """How many predicate gradings in the whole run were answered from an absence.

    For `FILE_CONTAINS` this count reads member-reported values only, and so over-reports
    ungradeable wherever the runtime's tick fill graded the clone
    (`the build specification (not in this mirror)` § Deliverable 5); the per-tick `MonitorVerdict` in the
    journal is the grade.
    """
    total = 0
    for summary in summaries.values():
        unit = units.get(summary.unit_id)
        if unit is None:
            continue
        total += sum(1 for one in unit.expected if ungradeable(one, summary))
    return total


# --------------------------------------------------------------------------------------
# The four groups that come off `seat_calls.jsonl`
# --------------------------------------------------------------------------------------


def _cost_of(record: SeatCallRecord) -> float:
    """The CLI's own cost estimate for one invocation, summed over its `model_usage` entries."""
    total = 0.0
    for entry in record.model_usage.values():
        if isinstance(entry, Mapping):
            value = entry.get(COST_KEY)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                total += float(value)
    return total


def _addressees() -> tuple[Addressee, ...]:
    """Every addressee a receipt can be keyed by, in `config.ADDRESSEES`' own order.

    A seat call is keyed by `Tier` and everything else by `CallType`; the report walks both so
    that a dispatch's spend and a think's are as visible as a seat's (build A.1).
    """
    return tuple(Tier(name) for name in config.TIERS) + tuple(CallType)


def seat_economics(records: Sequence[SeatCallRecord]) -> list[SeatEconomics]:
    """Per **addressee**: calls, spend, the cache receipt as a ratio, wall time and cost.

    Folded: S-19, re-based by build A.1 (§ Deliverable 3): the executor seat is gone and the
    tick's work is a manager **dispatch**, so a row keyed by `Tier` would drop tier three's
    spend out of the report entirely. `config.ADDRESSEES` is the literal table, read rather
    than restated.
    """
    rows: list[SeatEconomics] = []
    for tier in _addressees():
        mine = [record for record in records if str(record.tier) == str(tier)]
        tokens = sum(record.spend_tokens() for record in mine)
        cache = sum(record.cache_reads() for record in mine)
        offered = tokens + cache
        rows.append(
            SeatEconomics(
                tier=tier,
                calls=len(mine),
                tokens=tokens,
                cache_read_tokens=cache,
                cache_read_ratio=(cache / offered) if offered else 0.0,
                wall_seconds=sum(record.wall_seconds for record in mine),
                cost_usd=sum(_cost_of(record) for record in mine),
            )
        )
    return rows


def tier_mismatch(
    records: Sequence[SeatCallRecord], verdicts: Mapping[int, MonitorVerdict]
) -> list[TierMismatch]:
    """Per tier: how often the monitor disagreed on a tick this tier was called on, and the
    two ways the seat itself failed.

    A tier is charged with a tick's mismatch when it made a call in that tick. That is a
    *reading* of "per-tier mismatch rate": the monitor grades a unit rather than a seat, so the
    only honest join between the two is the tick, and a tier that made no call in a tick had no
    hand in its verdict.
    """
    rows: list[TierMismatch] = []
    for tier in _addressees():
        mine = [record for record in records if str(record.tier) == str(tier)]
        ticks = {record.tick for record in mine}
        graded = sorted(tick for tick in ticks if tick in verdicts)
        missed = [tick for tick in graded if not verdicts[tick].match]
        rows.append(
            TierMismatch(
                tier=tier,
                graded_ticks=len(graded),
                mismatch_ticks=len(missed),
                mismatch_rate=(len(missed) / len(graded)) if graded else 0.0,
                decode_retries=sum(1 for one in mine if one.outcome == "decode_retry"),
                seat_unavailable=sum(1 for one in mine if one.outcome == "unavailable"),
                resumed_as_new=sum(1 for one in mine if RESUMED_AS_NEW in one.error),
            )
        )
    return rows


def version_spread(records: Sequence[SeatCallRecord]) -> VersionSpread:
    """Every distinct `cli_version` in first-seen order, and whether it moved (§ Rulings 16)."""
    seen: list[str] = []
    for record in records:
        if record.cli_version and record.cli_version not in seen:
            seen.append(record.cli_version)
    return VersionSpread(versions=seen, changed_mid_run=len(seen) > 1)


# --------------------------------------------------------------------------------------
# The files group, and the report itself
# --------------------------------------------------------------------------------------


def clone_changes(
    workspace_path: str, *, base_ref: str | None = None
) -> tuple[list[FileChange], list[str]]:
    """Every file the run created or changed in the clone, and any note about why it could not
    be read. A run with no clone is an ordinary shape, not a failure."""
    if not workspace_path:
        return [], ["no files group: this run had no workspace clone"]
    workspace = Path(workspace_path)
    if not is_repository_root(workspace):
        return [], [f"no files group: {workspace_path} is not the root of a git work tree"]
    rows = [
        FileChange(path=path, status=status)
        for status, path in changed_files(workspace, base_ref=base_ref)
    ]
    return rows, []


def build_report(
    root: Path,
    task_id: str,
    *,
    terminal: TerminalState | str | None = None,
    workspace_path: str = "",
    base_ref: str | None = None,
) -> WorkloadRunReport:
    """Read one finished task off the tree and compose its receipt. Nothing is written."""
    paths = BrainPaths(root=root).task(task_id)
    records = load_seat_calls(paths.seat_calls)
    verdicts = tick_verdicts(paths)
    summaries = tick_summaries(paths)
    files, notes = clone_changes(workspace_path, base_ref=base_ref)
    return WorkloadRunReport(
        schema_version=config.WORKLOAD_RUN_REPORT_SCHEMA_VERSION,
        task=task_id,
        terminal=None if terminal is None else TerminalState(str(terminal)),
        ticks=len(paths.journal_ticks()),
        detectors=detector_rows(
            detector_fires(verdicts).items(), manager_dismissals(paths).items()
        ),
        seats=seat_economics(records),
        mismatch=tier_mismatch(records, verdicts),
        versions=version_spread(records),
        files=files,
        seat_requests=seat_request_bytes(paths),
        ungradeable_predicates=ungradeable_count(committed_units(paths), summaries),
        notes=notes,
    )


def write_report(paths: TaskPaths, report: WorkloadRunReport) -> Path:
    """Write the report beside the checkpoints, and read it back before returning the path.

    The read-back is the same discipline the checkpoint's temp-then-rename buys: the archive
    copies this file and hashes it, so a half-written report would be hashed as if it were the
    receipt.
    """
    path = report_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
    )
    load_report(path)
    return path


def load_report(path: Path) -> WorkloadRunReport:
    """The report on disk, refusing a `schema_version` this code does not write."""
    if not path.exists():
        raise SchemaVersionMismatch(
            artifact=ARTIFACT, found=-1, expected=config.WORKLOAD_RUN_REPORT_SCHEMA_VERSION
        )
    return load_run_report(
        json.loads(path.read_text(encoding="utf-8")),
        expected=config.WORKLOAD_RUN_REPORT_SCHEMA_VERSION,
    )
