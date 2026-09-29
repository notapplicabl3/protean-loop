"""The run: N baselines × four canonical tasks × R repeats, one fresh clone per session.

`the build specification (not in this mirror)` § Deliverable 4's acceptance (`DIGEST:117`, Q3's default) —
3 repeats per task, the **baseline run twice before the change**, both reported, and the median
rule applied by whoever reads the report rather than by the report.

**Sequential, and never retried.** Every session spends real money exactly once. A session that
times out, refuses or produces nothing is *recorded* — its partial transcript is still a
measurement — and the run moves on. Nothing here widens the wall cap or the dollar cap: those
are the seed's, and the seed is the operator's.

**One clone per session and it is destroyed on the way out**, including when the session raised.
`fresh_clone` is a context manager for exactly that reason.

**Where the report lands.** `brain/` is one of the three trees row K6 proves byte-unchanged
across the run, so a report written there would break the receipt it is supposed to accompany;
`fixtures/` is not a place for a run artifact. The default is `<root>/reports/oracle/` and the
caller may name any other directory (dispatch-14 ledger D14-7).

**One session's failure is one row, never the run's** (S-49). `baseline()` isolates each
session: a raised clone, a raised spawn, a raised grade become a row with `first_success: false`
and the exception's class and message in `summary_line`, and the pass continues. Every record —
failed or not — is handed to `on_session` **as it returns**, which is where the driver writes
the transcript and the audit line, so a run killed at session 19 has 19 measurements on disk
rather than none. Before S-49 the first raised session aborted the pass and `records` never
reached disk, which for a 24-session run with real spend behind it is the expensive failure.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from protean.oracle.audit import ToolAudit, ToolViolation, session_audit, tool_audit
from protean.oracle.clone import fresh_clone, head_sha
from protean.oracle.config import OracleSeat
from protean.oracle.counts import structural_counts
from protean.oracle.predicates import verdict_for
from protean.oracle.session import OracleSession, SessionResult
from protean.oracle.tasks import CANONICAL_TASK_SPECS, TaskSpec
from protean.oracle.transcript import (
    TranscriptMetrics,
    derive_metrics,
    permission_denials,
)
from protean.state.oracle import (
    PRE_CHANGE_BASELINES,
    SUMMARY_LINE_LIMIT,
    OracleBaseline,
    OracleReport,
    OracleTaskResult,
    flat_expectation_values,
)

#: § Deliverable 4's acceptance: 3 repeats per task (`DIGEST:117`, Q3's stated default).
DEFAULT_REPEATS: Final[int] = 3

#: Where a report lands when the caller names nothing, relative to the repo root. Outside
#: `brain/` on purpose — see the module docstring.
REPORT_DIRNAME: Final[str] = "reports"
REPORT_SUBDIRNAME: Final[str] = "oracle"


def default_report_dir(root: Path) -> Path:
    """`<root>/reports/oracle/`. Not under `brain/`, and not under `fixtures/`."""
    return root / REPORT_DIRNAME / REPORT_SUBDIRNAME


def mint_run_id(now: datetime | None = None) -> str:
    """`oracle-YYYYMMDD-HHMMSSZ`, minted from the UTC clock at the run's open."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%SZ")
    return f"oracle-{stamp}"


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """One measured session, whole — the row, plus the receipts row K6 reads off it.

    Kept beside the `OracleTaskResult` rather than folded into it because S5's per-task field
    list is the operator's and does not carry a transcript, an argv or a violation list.
    """

    baseline: str
    task: str
    repeat: int
    row: OracleTaskResult
    metrics: TranscriptMetrics
    session: SessionResult
    violations: tuple[ToolViolation, ...]
    clone_path: str
    clone_exists_after: bool

    #: S-52's three lists for this session, and S-51/S-47's three detection lists beside them.
    #: Carried on the record rather than recomputed by the writer, because the two lists that
    #: must be empty are decided against the **clone**, and the clone is gone by the time any
    #: writer sees this (`audit` is built inside `fresh_clone`'s block).
    audit: ToolAudit = field(default_factory=ToolAudit)
    audit_row: dict[str, Any] = field(default_factory=dict)

    #: Why this session has no measurement, when it has none. Empty on every session that ran.
    error: str = ""


@dataclass(slots=True)
class OracleRun:
    """The runner. One instance per measurement; `baseline()` is one whole pass."""

    workload: Path
    seat: OracleSeat
    spawner: OracleSession
    repeats: int = DEFAULT_REPEATS
    on_session: Callable[[SessionRecord], None] | None = None
    records: list[SessionRecord] = field(default_factory=list)

    #: Which `(baseline, task, repeat)` tuples this pass leaves alone. A **resumed** run passes
    #: the tuples its audit file already holds: every measured session spends real money exactly
    #: once, and buying one a second time is the one thing a measurement must not do. S-49's
    #: incremental write is what makes the question answerable at all — the rows of a killed pass
    #: are on disk, so the pass that follows it can be the complement rather than a repeat.
    skip: Callable[[str, str, int], bool] | None = None

    def one_session(self, baseline: str, spec: TaskSpec, repeat: int) -> SessionRecord:
        """One task, one repeat, one fresh clone — and the clone is gone when this returns.

        Raises. `session_or_failure()` is the arm the pass walks; this one is kept raising so
        that a caller who wants the exception (a smoke test, a single-session probe) still gets
        it rather than a row that quietly says nothing happened.
        """
        started = time.monotonic()
        # The wall clock, not the monotonic one: it is compared against file mtimes in the
        # clone, which is how "the artifact was written after the candidate ran" is checked
        # (S-46; ledger S1-3).
        opened_at = time.time()
        with fresh_clone(self.workload) as clone:
            result = self.spawner.open(spec.prompt, clone)
            metrics = derive_metrics(result.stdout)
            verdict = verdict_for(spec.task, metrics, clone, opened_at)
            # The refused calls are subtracted before the audit: a `tool_use` block the
            # permission layer answered with a denial is an attempt, not a run (S-44;
            # dispatch-15 ledger D15-1).
            denials = permission_denials(result.stdout)
            audit = tool_audit(metrics, self.seat.allowed_tools, denials, clone)
            audit_row = session_audit(
                metrics, self.seat.allowed_tools, denials, clone, since=opened_at
            )
            clone_path = str(clone)
        return self._record(
            baseline=baseline,
            spec=spec,
            repeat=repeat,
            row=OracleTaskResult(
                task=spec.task,
                success_predicate=spec.success_predicate,
                repeat=repeat,
                steps_to_first_success=verdict.steps_to_first_success,
                failed_commands=metrics.failed_commands,
                files_read=metrics.files_read,
                first_success=verdict.first_success,
                exit_code=verdict.exit_code,
                summary_line=verdict.summary_line,
                wall_seconds=round(time.monotonic() - started, 3),
                cli_version=result.cli_version,
            ),
            metrics=metrics,
            session=result,
            audit=audit,
            audit_row=audit_row,
            clone_path=clone_path,
        )

    def session_or_failure(
        self, baseline: str, spec: TaskSpec, repeat: int
    ) -> SessionRecord:
        """One session, isolated: whatever it raises becomes a row and the pass goes on (S-49).

        Deliberately `Exception` and not a named set. What can come out of here is a clone that
        could not be made, a spawn the OS refused, a filesystem that filled, a grade over a
        stream nobody anticipated — and the run's job is to record what happened to all 24
        sessions, not to be right about which of them can fail.
        """
        started = time.monotonic()
        try:
            return self.one_session(baseline, spec, repeat)
        except Exception as error:  # noqa: BLE001 — see the docstring
            return self._record(
                baseline=baseline,
                spec=spec,
                repeat=repeat,
                row=OracleTaskResult(
                    task=spec.task,
                    success_predicate=spec.success_predicate,
                    repeat=repeat,
                    steps_to_first_success=None,
                    failed_commands=0,
                    files_read=0,
                    first_success=False,
                    exit_code=None,
                    # The contract caps this at `SUMMARY_LINE_LIMIT`; capped here too so the
                    # `error` field beside it carries exactly what the row does.
                    summary_line=_reason(error),
                    wall_seconds=round(time.monotonic() - started, 3),
                    cli_version="",
                ),
                metrics=TranscriptMetrics(),
                session=_no_session(),
                audit=ToolAudit(),
                audit_row={},
                clone_path="",
                error=_reason(error),
            )

    def _record(
        self,
        *,
        baseline: str,
        spec: TaskSpec,
        repeat: int,
        row: OracleTaskResult,
        metrics: TranscriptMetrics,
        session: SessionResult,
        audit: ToolAudit,
        audit_row: dict[str, Any],
        clone_path: str,
        error: str = "",
    ) -> SessionRecord:
        """Keep one record and hand it on **now** — the incremental half of S-49.

        `on_session` is where the driver writes the transcript and the audit line, so it is
        called the moment the session returns rather than at the end of the pass: a run this
        long is killed mid-way sooner or later, and a spend whose transcript was never written
        down is a spend with no measurement.
        """
        record = SessionRecord(
            baseline=baseline,
            task=spec.task,
            repeat=repeat,
            row=row,
            metrics=metrics,
            session=session,
            violations=audit.violations,
            clone_path=clone_path,
            clone_exists_after=bool(clone_path) and Path(clone_path).exists(),
            audit=audit,
            audit_row=audit_row,
            error=error,
        )
        self.records.append(record)
        if self.on_session is not None:
            self.on_session(record)
        return record

    def baseline(self, name: str) -> OracleBaseline:
        """One whole pass: the four canonical tasks, `repeats` times each, in order.

        A tuple `skip` claims is not run and contributes no row here — its row is already on
        disk, and `assemble()` in the driver is what puts the two halves back together. The
        baseline this returns is therefore the pass's own work, never the run's whole set.
        """
        opened = datetime.now(UTC).isoformat()
        rows: list[OracleTaskResult] = []
        for spec in CANONICAL_TASK_SPECS:
            for repeat in range(1, self.repeats + 1):
                if self.skip is not None and self.skip(name, spec.task, repeat):
                    continue
                rows.append(self.session_or_failure(name, spec, repeat).row)
        return OracleBaseline(
            baseline=name,
            tree_sha=head_sha(self.workload),
            started_at=opened,
            finished_at=datetime.now(UTC).isoformat(),
            tasks=rows,
        )

    def report(
        self, baselines: Sequence[OracleBaseline], run_id: str | None = None
    ) -> OracleReport:
        """The finished `OracleReport` (S5) over however many baselines were run."""
        counts = structural_counts(self.workload)
        return OracleReport(
            run_id=run_id or mint_run_id(),
            tree_sha=head_sha(self.workload),
            cli_version=self.spawner.cli_version(),
            # Every version any session actually recorded, so a CLI that moved mid-run is
            # visible in the report rather than only in the transcripts (S-49).
            cli_versions=sorted(
                {row.cli_version for one in baselines for row in one.tasks if row.cli_version}
            ),
            baselines=list(baselines),
            structural_counts=counts,
            expectation_values=flat_expectation_values(baselines, counts),
        )

    def pre_change(self, run_id: str | None = None) -> OracleReport:
        """Both pre-change baselines — § Deliverable 4's noise probe — in one report."""
        return self.report(
            [self.baseline(name) for name in PRE_CHANGE_BASELINES], run_id=run_id
        )


def _reason(error: BaseException) -> str:
    """An exception as one capped line: its class and its message, in that order."""
    return f"{type(error).__name__}: {error}"[:SUMMARY_LINE_LIMIT]


def _no_session() -> SessionResult:
    """The empty `SessionResult` a failed row carries. Nothing ran, and it says so."""
    return SessionResult(
        argv=(),
        cwd="",
        environment={},
        stdout="",
        stderr="",
        exit_code=None,
        wall_seconds=0.0,
        timed_out=False,
        cli_version="",
    )


def write_report(report: OracleReport, directory: Path) -> Path:
    """`<directory>/<run_id>.json`, created on write, the way every writer in this build does."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{report.run_id}.json"
    path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


__all__: Sequence[str] = (
    "DEFAULT_REPEATS",
    "REPORT_DIRNAME",
    "REPORT_SUBDIRNAME",
    "OracleRun",
    "SessionRecord",
    "default_report_dir",
    "mint_run_id",
    "write_report",
)
