"""Seam contract S5 — `OracleReport`, what the synthetic dev measures and hands back.

`the build specification (not in this mirror)` § Deliverable 4 (folded: A1-8, folded: S-29, folded: S-34),
and § Directional decisions 18 — **the oracle measures the transcript, never the session's
self-report**.

**Nothing here is model-authored.** Every field on `OracleTaskResult` is derived by
`protean.oracle.transcript` from `stream-json` events, or read off the process the session ran,
or computed from the tree. The report holds no field a session could write into: there is no
`self_reported_*`, no narrative, no summary the model composed. That is the contract's whole
point — a synthetic dev that graded itself would be a seat, not an oracle.

**`expectation_values` is why this is a plugin rather than a parallel system.** It is a flat
map — no nesting, so equality after `model_dump(mode="json")` is well defined — carried onto an
`ExecutorSummary` by `executor_summary()`. Build 1's anterior cingulate then reads it through
its existing `summary_field_equals` arm (`src/protean/nodes/anterior_cingulate.py:64-68`),
whose `field`/`value` argument keys live in `src/protean/nodes/vocabulary.py`. The oracle plugs
into build 1's comparator instead of standing beside it.

**Two baselines, one report.** § Deliverable 4's acceptance runs the baseline **twice before
the change** — the framing pass's own noise probe — and reports both, so oracle variance is
visible rather than assumed away. S5 names the per-task field list and the report-level
`run_id`; the container that holds two baselines is a builder's default (dispatch-14 ledger
D14-4), and the per-task list below is S5's exactly, unwidened.

This module is **not** exported through `protean.state`'s roster, following its build-2
siblings `semantic.py` and `seat_calls.py`: the roster gate is build 1's inter-node contract
set, and an oracle report is a measurement artifact rather than a contract between two nodes.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from typing import Final, Literal

from pydantic import Field, JsonValue, field_validator

from protean.state.base import ProteanModel
from protean.state.seats import ExecutorSummary

#: The one bound every free-text field on a row is held to. A `summary_line` is the last line
#: of a tool result and a tool result can be a ten-kilobyte stack trace; a report with 24 of
#: those in it is a report nobody opens. The same 400 as `cortex.live.invoke.MESSAGE_LIMIT`,
#: for the same reason and stated once per contract (S-49).
SUMMARY_LINE_LIMIT: Final[int] = 400

#: The report's schema version. Versioning is a **refusal** in build 2 as in build 1
#: (§ Out of scope, "Migrating any checkpoint or artifact"): a reader that meets a version it
#: does not know refuses rather than migrating.
ORACLE_REPORT_SCHEMA_VERSION: Final[int] = 1

#: The two baselines § Deliverable 4's acceptance requires **before** the change. Named rather
#: than free strings so a report carrying one baseline twice is a validation error.
BASELINE_FIRST: Final[str] = "pre-change-1"
BASELINE_SECOND: Final[str] = "pre-change-2"
PRE_CHANGE_BASELINES: Final[tuple[str, ...]] = (BASELINE_FIRST, BASELINE_SECOND)

#: The baseline order W8 records *after* the workload change. Named here so the post-change
#: report is the same type rather than a second one.
BASELINE_POST_CHANGE: Final[str] = "post-change"

#: The four canonical tasks (`DIGEST:101`, folded: S-29). The ids are the report's keys and
#: the module `protean.oracle.tasks` is what binds each to its command and its predicate.
TASK_DIGEST: Final[str] = "digest one ticket"
TASK_RIG: Final[str] = "rig it"
TASK_DASHBOARD: Final[str] = "render the dashboard"
TASK_SUITE: Final[str] = "run the suite"
CANONICAL_TASKS: Final[tuple[str, ...]] = (TASK_DIGEST, TASK_RIG, TASK_DASHBOARD, TASK_SUITE)


class OracleTaskResult(ProteanModel):
    """One canonical task, one repeat, on one fresh clone — S5's per-task field list exactly.

    `steps_to_first_success` is `None` and not `0` when the predicate was never satisfied:
    zero steps is a real measurement (a session that succeeded on its first tool use) and must
    not read the same as a session that never got there.

    `reason` is not an S5 field and is not one here: S-29's "recorded as `first_success: false`
    with the reason" is carried by `summary_line`, which is the one line of captured output the
    verdict rests on — pytest's terminal summary for the suite, the located refusal for the rig,
    the failing command's own message when nothing satisfied the predicate.
    """

    task: str
    success_predicate: str
    repeat: int = Field(ge=1)
    steps_to_first_success: int | None = Field(default=None, ge=0)
    failed_commands: int = Field(ge=0)
    files_read: int = Field(ge=0)
    first_success: bool
    exit_code: int | None = None
    summary_line: str = ""
    wall_seconds: float = Field(ge=0.0)

    #: The CLI that ran **this** session, re-probed per session rather than cached per run
    #: (S-49). The binary auto-updates, and a run whose 24 sessions were not all taken on one
    #: version is a run whose comparison is between two things.
    cli_version: str = ""

    @field_validator("summary_line")
    @classmethod
    def _cap_the_summary(cls, value: str) -> str:
        """The cap is enforced on the contract, so no construction path can get around it."""
        return value[:SUMMARY_LINE_LIMIT]


class OracleBaseline(ProteanModel):
    """One whole pass over the four canonical tasks at N repeats each.

    The container S5 does not name (ledger D14-4). It exists because § Deliverable 4's
    acceptance requires **both** pre-change baselines in one report, and two passes cannot
    share one flat task list without a discriminator somewhere.
    """

    baseline: str
    tree_sha: str
    started_at: str
    finished_at: str
    tasks: list[OracleTaskResult] = Field(default_factory=list)

    def for_task(self, task: str) -> list[OracleTaskResult]:
        return [row for row in self.tasks if row.task == task]

    def successes(self, task: str) -> int:
        """How many repeats reached the predicate. The half of acceptance the median hides."""
        return sum(1 for row in self.for_task(task) if row.first_success)

    def median_steps(self, task: str) -> float | None:
        """The median of the repeats that reached the predicate, or `None` when none did.

        § Deliverable 4's acceptance rule is stated on the median (`DIGEST:117`, Q3's default),
        and a repeat that never succeeded contributes no step count — averaging a `None` in as
        a zero would make a failing task look fast.
        """
        steps = [
            row.steps_to_first_success
            for row in self.for_task(task)
            if row.steps_to_first_success is not None
        ]
        return statistics.median(steps) if steps else None


class OracleStructuralCounts(ProteanModel):
    """The three counts computed from the **tree**, never from the session (§ Deliverable 4).

    Definitions are a builder's default, fixed in `protean.oracle.counts` and recorded in
    dispatch-14 ledger D14-5 so order W8 recomputes the same three numbers rather than three
    differently-defined ones.
    """

    docs_on_the_path: int = Field(ge=0)
    commands_to_know: int = Field(ge=0)
    readme_lines_before_first_runnable: int = Field(ge=0)


class OracleReport(ProteanModel):
    """Seam contract S5. One measurement of one tree, across every baseline that was run."""

    schema_version: Literal[1] = ORACLE_REPORT_SCHEMA_VERSION
    run_id: str
    tree_sha: str
    cli_version: str = ""

    #: Every distinct `cli_version` seen across the run's sessions, sorted. One entry is the
    #: expected shape; two is a CLI that moved mid-run, which is a fact about the measurement
    #: rather than about the tree (S-49).
    cli_versions: list[str] = Field(default_factory=list)
    baselines: list[OracleBaseline] = Field(default_factory=list)
    structural_counts: OracleStructuralCounts
    expectation_values: dict[str, JsonValue] = Field(default_factory=dict)

    def baseline(self, name: str) -> OracleBaseline | None:
        return next((one for one in self.baselines if one.baseline == name), None)

    def has_both_pre_change_baselines(self) -> bool:
        """§ Deliverable 4's noise probe, as a question the DoD row can be read off."""
        present = {one.baseline for one in self.baselines}
        return all(name in present for name in PRE_CHANGE_BASELINES)

    def executor_summary(self, unit_id: str = "") -> ExecutorSummary:
        """The report, projected into the type build 1's comparator already reads.

        `expectation_values` is carried **verbatim** onto the field of the same name, so the
        anterior cingulate's `summary_field_equals` arm — which compares
        `summary.model_dump(mode="json")[field]` against the predicate's `value` — reads the
        oracle's own map. `exit_code` is 0 when every task in every baseline reached its
        predicate and 1 otherwise, so a run-level predicate is available beside the map.

        `narrative` states only what was measured. It is not a self-report: no model wrote it.
        """
        reached = all(row.first_success for one in self.baselines for row in one.tasks)
        return ExecutorSummary(
            tick=0,
            unit_id=unit_id or self.run_id,
            narrative=(
                f"oracle run {self.run_id} over tree {self.tree_sha}: "
                f"{len(self.baselines)} baselines, "
                f"{sum(len(one.tasks) for one in self.baselines)} sessions"
            ),
            exit_code=0 if reached else 1,
            expectation_values=dict(self.expectation_values),
        )


class OracleAcceptance(ProteanModel):
    """§ Deliverable 4's acceptance rule, as a verdict with its reasons (S-50).

    `accepted` is true only when **both** halves hold on **every** canonical task: the median
    steps-to-first-success dropped, and `successes` did not drop. The second half is the fix.
    `median_steps()` medians only the repeats that *reached* the predicate, so a change that
    broke two of three repeats and made the survivor fast reads as an improvement under the
    median alone — 1/3 at `[3]` beats 3/3 at `[2, 5, 9]`, which is the Analyst's counter-example
    and the thing this type refuses. It is a sharpening of Q3's "no task regresses", not a new
    rule: a task that stopped working regressed.

    `reasons` names every task that failed a half, so a rejection says which one and why.
    """

    accepted: bool
    reasons: list[str] = Field(default_factory=list)


def acceptance(pre: OracleBaseline, post: OracleBaseline) -> OracleAcceptance:
    """Did the change land? Both halves, on every task, or it did not (S-50).

    The median arm reads `None` as "no repeat reached the predicate": a post-change `None` is
    never a drop however good the pre-change number was, and a pre-change `None` against any
    post-change median is one, because going from nothing to something is the improvement the
    rule is looking for.
    """
    reasons: list[str] = []
    for task in CANONICAL_TASKS:
        before_median = pre.median_steps(task)
        after_median = post.median_steps(task)
        if after_median is None:
            reasons.append(
                f"{task}: no repeat reached the predicate after the change, so there is no "
                f"median to compare (before: {before_median})"
            )
        elif before_median is not None and after_median >= before_median:
            reasons.append(
                f"{task}: median steps did not drop ({before_median} → {after_median})"
            )
        before_successes = pre.successes(task)
        after_successes = post.successes(task)
        if after_successes < before_successes:
            reasons.append(
                f"{task}: successes dropped ({before_successes} → {after_successes} of "
                f"{len(post.for_task(task))} repeats)"
            )
    return OracleAcceptance(accepted=not reasons, reasons=reasons)


def flat_expectation_values(
    baselines: Iterable[OracleBaseline], counts: OracleStructuralCounts
) -> dict[str, JsonValue]:
    """The flat map S5 names, built from the measurements and nothing else.

    Flat by construction — every value is a bool, an int, a float or `None`, so the equality
    `summary_field_equals` performs after `model_dump(mode="json")` is well defined. Keys are
    `<baseline>.<task>.<measure>` for the per-task numbers and bare names for the tree's counts.
    """
    values: dict[str, JsonValue] = {}
    for one in baselines:
        for task in CANONICAL_TASKS:
            rows = one.for_task(task)
            values[f"{one.baseline}.{task}.median_steps"] = one.median_steps(task)
            values[f"{one.baseline}.{task}.successes"] = sum(1 for r in rows if r.first_success)
            values[f"{one.baseline}.{task}.repeats"] = len(rows)
            values[f"{one.baseline}.{task}.failed_commands"] = sum(
                r.failed_commands for r in rows
            )
            values[f"{one.baseline}.{task}.files_read"] = sum(r.files_read for r in rows)
    values["docs_on_the_path"] = counts.docs_on_the_path
    values["commands_to_know"] = counts.commands_to_know
    values["readme_lines_before_first_runnable"] = counts.readme_lines_before_first_runnable
    return values


def load_report(payload: object) -> OracleReport:
    """One deserialized report, refusing a version this build does not know.

    A refusal, never a migration (§ Out of scope). The check is here rather than in the reader
    so every reader takes the same path.
    """
    if isinstance(payload, dict):
        version = payload.get("schema_version")
        if version is not None and version != ORACLE_REPORT_SCHEMA_VERSION:
            raise ValueError(
                f"oracle report schema_version {version!r} is not "
                f"{ORACLE_REPORT_SCHEMA_VERSION} — this build refuses rather than migrates"
            )
    return OracleReport.model_validate(payload)


__all__: Sequence[str] = (
    "BASELINE_FIRST",
    "BASELINE_POST_CHANGE",
    "BASELINE_SECOND",
    "CANONICAL_TASKS",
    "ORACLE_REPORT_SCHEMA_VERSION",
    "PRE_CHANGE_BASELINES",
    "TASK_DASHBOARD",
    "TASK_DIGEST",
    "TASK_RIG",
    "TASK_SUITE",
    "SUMMARY_LINE_LIMIT",
    "OracleAcceptance",
    "OracleBaseline",
    "OracleReport",
    "OracleStructuralCounts",
    "OracleTaskResult",
    "acceptance",
    "flat_expectation_values",
    "load_report",
)
