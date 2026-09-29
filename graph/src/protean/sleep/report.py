"""P5 `SleepReport`: assembling the five groups, writing it, and the `--dry-run` diff.

`the build specification (not in this mirror)` § Deliverable 2 → *S5's mirror — P5 `SleepReport`* and its
group table, § Automation gate (the split review surface), § Resolutions S-13, and § DoD row L9.

**Five groups and no `comparison` group** (folded: S-13). Sleep reads one run per invocation, so
the two-run numbers of decision 20 have no second subject here; they are
`tests/wet/run_sleep_compare.py`'s own output.

**Nothing here computes a number of its own.** `protean.sleep.evidence` classifies and the three
producer phases derive; this module counts what they returned and lays it out. That is row L9's
rule — "every number derived from the traces, `seat_calls.jsonl` or `habit_hits.jsonl`, none
hardcoded" — held by construction: the only integer literals below are index and default zeros.

**The report is written on a `--dry-run` too.** § Deliverable 2: "`--dry-run` derives everything,
writes the report, prints the diff it *would* apply, and writes no file under `brain/`". So the
report is the one artifact both modes share, and `SleepReport.dry_run` is how a reader tells them
apart. `reports/` is gitignored (D14-7), which is exactly why this file is the **only** review
surface for the gitignored half of what sleep writes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from protean import config
from protean.runtime.paths import BrainPaths
from protean.sleep.evidence import AdmissibleSet, RunRecords
from protean.state.sleep import (
    EvidenceGroup,
    Procedure,
    ProceduresGroup,
    ProjectMemoryGroup,
    ProjectMemoryRecord,
    ProjectMemorySummary,
    RejectedCandidate,
    RunRead,
    SignalEvidence,
    SleepReport,
    SourceGroup,
    WeightsGroup,
    WeightUpdate,
    WithdrawnProcedure,
)

#: The report's filename suffix under `reports/sleep/`.
REPORT_SUFFIX: Final[str] = ".json"

#: How the JSON is written — indented, so the review artifact for the untracked half is one a
#: human reads and a `git diff` of a fixture is legible. Not the `separators` shape the
#: append-only artifacts use: nothing joins on these bytes.
REPORT_INDENT: Final[int] = 2


# --------------------------------------------------------------------------------------
# The three producer phases — orders W3, W5 and W6 return these
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WeightsPhase:
    """Order W3's return: every key considered, and every file it re-valued."""

    updates: tuple[WeightUpdate, ...] = ()
    files: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectMemoryPhase:
    """Order W5's return: the pair lines, the run's summary line, and the files they land in."""

    records: tuple[ProjectMemoryRecord, ...] = ()
    summaries: tuple[ProjectMemorySummary, ...] = ()
    files: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class ProceduresPhase:
    """Order W6's return: habits compiled, candidates rejected, and habits withdrawn."""

    written: tuple[Procedure, ...] = ()
    rejected: tuple[RejectedCandidate, ...] = ()
    withdrawn: tuple[WithdrawnProcedure, ...] = ()
    files: tuple[Path, ...] = ()
    #: Files deleted by a withdrawal. Reported apart from `files`, which are files *written*:
    #: the verb prints one line per file it wrote and nothing it did not write.
    deleted: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class Phases:
    """The three phases of one sleep run, in the order § Build process runs their legs."""

    weights: WeightsPhase = field(default_factory=WeightsPhase)
    project_memory: ProjectMemoryPhase = field(default_factory=ProjectMemoryPhase)
    procedures: ProceduresPhase = field(default_factory=ProceduresPhase)

    def files(self) -> tuple[Path, ...]:
        """Every file the three phases wrote, in phase order and de-duplicated."""
        seen: list[Path] = []
        for group in (self.weights, self.project_memory, self.procedures):
            for path in group.files:
                if path not in seen:
                    seen.append(path)
        return tuple(seen)


# --------------------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------------------


def evidence_group(pairs: AdmissibleSet) -> EvidenceGroup:
    """§ Deliverable 1's set, made countable: per signal, and by reason over every signal."""
    rows: list[SignalEvidence] = []
    for signal in pairs.signals():
        seen = pairs.for_signal(signal)
        excluded = {reason: 0 for reason in config.SLEEP_EXCLUSION_REASONS}
        for pair in seen:
            if not pair.admissible:
                excluded[pair.excluded_reason] = excluded.get(pair.excluded_reason, 0) + 1
        rows.append(
            SignalEvidence(
                signal=signal,
                pairs=len(seen),
                admissible=sum(1 for pair in seen if pair.admissible),
                matched=sum(1 for pair in seen if pair.admissible and pair.matched),
                excluded=excluded,
            )
        )
    return EvidenceGroup(
        signals=rows,
        pairs=len(pairs.pairs),
        admissible=len(pairs.admissible),
        excluded=pairs.by_reason(),
    )


def source_group(
    records: RunRecords, *, verified: Mapping[str, str], brain: BrainPaths
) -> SourceGroup:
    """§ Deliverable 2's `source` group — what the update was taken *under* (decision 17)."""
    return SourceGroup(
        runs=[
            RunRead(
                source=records.source,
                task=records.task,
                ticks=records.ticks,
                terminal=records.terminal,
                project=records.project,
            )
        ],
        seed_hashes=dict(verified),
        brain_root=str(brain.root),
    )


def build_report(
    *,
    sleep_id: str,
    dry_run: bool,
    records: RunRecords,
    pairs: AdmissibleSet,
    verified: Mapping[str, str],
    brain: BrainPaths,
    phases: Phases,
    notes: Sequence[str] = (),
) -> SleepReport:
    """The five groups, assembled from what the run read and what the three phases returned."""
    return SleepReport(
        sleep_id=sleep_id,
        dry_run=dry_run,
        source=source_group(records, verified=verified, brain=brain),
        evidence=evidence_group(pairs),
        weights=WeightsGroup(updates=list(phases.weights.updates)),
        procedures=ProceduresGroup(
            written=list(phases.procedures.written),
            rejected=list(phases.procedures.rejected),
            withdrawn=list(phases.procedures.withdrawn),
        ),
        project_memory=ProjectMemoryGroup(
            records=list(phases.project_memory.records),
            summaries=list(phases.project_memory.summaries),
        ),
        files_written=[
            path.relative_to(brain.root).as_posix()
            if path.is_relative_to(brain.root)
            else str(path)
            for path in phases.files()
        ],
        notes=list(notes),
    )


def report_path(directory: Path, sleep_id: str) -> Path:
    """`<reports>/sleep/<sleep_id>.json`."""
    return directory / f"{sleep_id}{REPORT_SUFFIX}"


def write_report(report: SleepReport, directory: Path) -> Path:
    """Write the report and return its path. The one file sleep writes outside the brain root."""
    directory.mkdir(parents=True, exist_ok=True)
    path = report_path(directory, report.sleep_id)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=REPORT_INDENT, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return path


def load_report_file(path: Path) -> SleepReport:
    """Read one written report back, through P5's own version refusal."""
    from protean.state.sleep import load_sleep_report

    return load_sleep_report(json.loads(path.read_text(encoding="utf-8")))


# --------------------------------------------------------------------------------------
# The `--dry-run` diff
# --------------------------------------------------------------------------------------


def diff_lines(report: SleepReport) -> list[str]:
    """The diff a `--dry-run` prints — what it *would* apply, in the report's own numbers.

    One line per APPLIED weight update (a withheld one applies nothing — its why lives in the
    report's `weights` group, folded: D8-11), per procedure written or withdrawn, and one per project the
    memory phase would touch. A run that would change nothing says so in one line rather than
    printing an empty block, because "no habit cleared the floor" is a reportable outcome
    (§ Named assumptions 7) and silence reads like a failure.
    """
    lines: list[str] = []
    for update in report.weights.applied():
        lines.append(f"would {update.landed_under()}")
    for procedure in report.procedures.written:
        lines.append(
            f"would write procedure {procedure.procedure_id} "
            f"({len(procedure.responses)} response(s), hits_required={procedure.hits_required})"
        )
    for withdrawn in report.procedures.withdrawn:
        lines.append(f"would withdraw procedure {withdrawn.procedure_id} at {withdrawn.path}")
    projects = sorted({row.project for row in report.project_memory.records})
    for project in projects:
        count = sum(1 for row in report.project_memory.records if row.project == project)
        lines.append(f"would append {count} project-memory line(s) under project {project!r}")
    if not lines:
        lines.append("would apply nothing: no update, procedure or memory line cleared its floor")
    return lines


__all__ = [
    "Phases",
    "ProceduresPhase",
    "ProjectMemoryPhase",
    "WeightsPhase",
    "build_report",
    "diff_lines",
    "evidence_group",
    "load_report_file",
    "report_path",
    "source_group",
    "write_report",
]
