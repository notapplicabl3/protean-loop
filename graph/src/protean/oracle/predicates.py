"""The four named success predicates, as matchers over the transcript.

`the build specification (not in this mirror)` § Deliverable 4, "The four canonical tasks" (folded: S-29),
and order W6 § Process 7 — **do not "fix" the two that are not exit 0**.

Two tasks succeed on a zero exit and two do not, and that asymmetry is the ruling rather than an
oversight. The rig succeeds by *refusing*: DEV credentials never enter a clone, so reaching the
documented `credential-missing` refusal is the credential-free frontier of the surface. The suite
succeeds by *completing*, whatever its counts: 27 failed / 524 errors / 2406 passed is the
workload's known baseline and its zero exit is the goal of the change, never the precondition of
the measurement.

**A candidate and a success are different questions.** `is_candidate()` asks "was this an
invocation of the task's tool at all" — that is what gives a never-succeeding session a real
`exit_code` and a real `summary_line` instead of two nulls. `is_success()` asks the ruled
question. Help invocations are not candidates: reading `--help` is exploration, and it is
precisely the exploration the step count is measuring.

**The rig predicate carries two arms, and dispatch-14 ledger D14-1 is why.** S-29's parenthetical
says exit 2 with the token on stderr; measured on a fresh clone at the pinned workload commit, `rig.cli open`
reaches the refusal, persists it into the session's `run-output.json`, and exits **0** with an
empty stderr, because the workload's runner module returns a persisted refusal rather than raising.
`RIG_RULED_ARM` is S-29's shape and `RIG_MEASURED_ARM` is the one this tree produces; the
predicate is satisfied by either, and `success_predicate` in the report is S-29's sentence
verbatim. Deleting `RIG_MEASURED_ARM` reverses the reading in one edit.

**Every predicate here is anchored to identity, never to narration (S-46).** A candidate is a
`Bash` tool use whose **own command begins** with the task's canonical invocation, after an
optional `uv run --no-project ` or `uv run ` prefix is stripped — never a substring found
anywhere in the command, and so never an `echo` of the right words, a `grep` for them, or a
compound whose second segment happens to reach the tool. The success gates are anchored the
same way: the digest's flags must be real argv tokens beside a genuine zero exit, the rig's
measured arm reads the refusal off the **clone's own** `run-output.json` rather than off text
the session produced, and the dashboard's artifact must be at the workload's documented output
path (`.notes/gate-dashboard/index.html`) rather than anywhere an `rglob` finds an `index.html`.
The deep round on this module found all three passable by a session that only *said* the right
words; the oracle's own tests (not in this mirror) were the standing proof they are not.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from protean.oracle.audit import shell_segments
from protean.oracle.transcript import (
    BASH_TOOL,
    TranscriptEvent,
    TranscriptMetrics,
    last_meaningful_line,
    pytest_summary_line,
)
from protean.state.oracle import TASK_DASHBOARD, TASK_DIGEST, TASK_RIG, TASK_SUITE

#: A help invocation. Never a candidate: finding the flags is the measurement.
_HELP = re.compile(r"(^|\s)(--help|-h)(\s|$)")

#: The runner prefixes a command may reach the workload's tooling through, longest first. The
#: workload's own docs spell the invocation `uv run --no-project python -m …`, and the seat's
#: allow-list licenses `Bash(uv:*)`, so the prefix is stripped before the invocation is read —
#: and nothing else is. A command that reaches the tool through `bash -c`, an `export` and a
#: semicolon, or a shell function is not a candidate, because what it ran cannot be read off
#: the argv the CLI recorded (S-46).
UV_PREFIXES: Final[tuple[str, ...]] = ("uv run --no-project ", "uv run ")

#: The canonical invocation each task's candidate must **begin** with (S-46). Both interpreter
#: spellings, since `python3` is the same invocation (ledger S1-1); the `-m` module form is the
#: one every `success_predicate` sentence in `protean.oracle.tasks` names.
DIGEST_INVOCATIONS: Final[tuple[str, ...]] = ("python -m digest.cli", "python3 -m digest.cli")
RIG_INVOCATIONS: Final[tuple[str, ...]] = (
    "python -m rig.cli open",
    "python3 -m rig.cli open",
)
DASHBOARD_INVOCATIONS: Final[tuple[str, ...]] = (
    "python -m dashboard.cli",
    "python3 -m dashboard.cli",
)
SUITE_INVOCATIONS: Final[tuple[str, ...]] = ("pytest",)

#: The two flags S-29 makes mandatory on the digest, checked as **argv tokens** rather than as
#: substrings: `--stub` inside a quoted argument, a comment or a printed string is not a flag
#: the process received.
DIGEST_REQUIRED_FLAGS: Final[tuple[str, ...]] = ("--group-key", "--stub")

#: The token the rig's refusal is named by (the workload's runner module).
CREDENTIAL_MISSING: Final[str] = "credential-missing"

#: S-29's ruled observable for the rig: exit 2, that token on stderr.
RIG_RULED_EXIT: Final[int] = 2

#: The file the measured refusal lands in, named so the second arm is specific rather than a
#: free-text search of anything the session happened to print.
RIG_RUN_OUTPUT: Final[str] = "run-output.json"

#: What `render the dashboard` must have written, and **where** the workload documents that it
#: lands: three places in the workload's own files (its CLI, its README and its\n#: architecture doc). One path, not a search: an `index.html` anywhere else in the clone is
#: some other file (ledger S1-2).
DASHBOARD_ARTIFACT: Final[str] = "index.html"
DASHBOARD_OUTPUT_SEGMENTS: Final[tuple[str, ...]] = (".notes", "gate-dashboard")

#: The two exits § Deliverable 4 accepts from the dashboard: clean, or findings raised.
DASHBOARD_EXITS: Final[tuple[int, ...]] = (0, 1)

#: S-29's reference counts for the suite, recorded beside whatever this run measured.
SUITE_BASELINE: Final[dict[str, int]] = {"failed": 27, "errors": 524, "passed": 2406}


@dataclass(frozen=True, slots=True)
class Verdict:
    """One task's grade on one session, and the evidence the grade rests on."""

    first_success: bool
    steps_to_first_success: int | None
    exit_code: int | None
    summary_line: str


@dataclass(frozen=True, slots=True)
class TaskPredicate:
    """One canonical task's matcher. `describe` is S-29's sentence and is never rewritten.

    `since` is a wall-clock epoch taken immediately before the session was spawned, and it is
    what "the artifact was written **after** the candidate ran" is checked against: a
    `stream-json` `tool_use` block carries no timestamp, so the clone's own mtimes are compared
    to the session's start (ledger S1-3). `None` — every hand-built case and every re-grade of a
    stored transcript, neither of which has a clock — leaves the mtime gate off and checks the
    artifact's presence at its documented path alone.
    """

    task: str

    #: The invocations a candidate's command must begin with. Empty on the base class.
    invocations: tuple[str, ...] = ()

    def is_candidate(self, event: TranscriptEvent) -> bool:
        """A `Bash` use whose own command **begins** with this task's invocation (S-46)."""
        return begins_with_invocation(_bash(event), self.invocations)

    def is_success(
        self, event: TranscriptEvent, clone: Path | None, since: float | None = None
    ) -> bool:
        raise NotImplementedError

    def summary_for(self, event: TranscriptEvent) -> str:
        return last_meaningful_line(event.result_text)


def _bash(event: TranscriptEvent) -> str:
    return event.command if event.tool == BASH_TOOL else ""


def canonical_command(command: str) -> str:
    """One command with its leading whitespace and at most one `uv run` prefix stripped.

    At most one, and only at the front: stripping repeatedly, or anywhere, would turn
    `echo uv run python -m digest.cli` into a candidate, which is the whole class of thing S-46
    exists to refuse.
    """
    text = command.lstrip()
    for prefix in UV_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix) :].lstrip()
    return text


def begins_with_invocation(command: str, invocations: Sequence[str]) -> bool:
    """Does this command **begin** with one of these invocations, and is it not a help call?

    The trailing-space requirement is what stops `pytest` from matching `pytest-watch` and
    `python -m digest.clint`; the whole-string arm is what lets a bare `pytest` match.
    """
    if not command or not invocations:
        return False
    text = canonical_command(command)
    if _HELP.search(text):
        return False
    # One shell segment, or nothing is graded (S-46; audit 2026-09-19, D1): a flag in a later
    # segment was never the tool's argv, and the exit status of `… || true` or `… ; exit 2` is
    # the compound's, never the tool's. The splitter is the containment audit's own (S-55), so a
    # redirect or a quoted `;` stays one segment here exactly as it does there.
    if len(shell_segments(text)) != 1:
        return False
    return any(text == one or text.startswith(f"{one} ") for one in invocations)


def argv_tokens(command: str) -> tuple[str, ...]:
    """A command's argv as the shell would split it, for checking a flag was really passed.

    `shlex` rather than `str.split()` so a flag inside a quoted argument does not count, and a
    lexer error (an unbalanced quote the shell itself would reject) falls back to whitespace
    splitting rather than raising in the middle of a grade.
    """
    try:
        return tuple(shlex.split(command))
    except ValueError:
        return tuple(command.split())


def carries_flag(command: str, flag: str) -> bool:
    """Was `flag` a real argv token — bare, or in its `--flag=value` form?"""
    return any(
        token == flag or token.startswith(f"{flag}=") for token in argv_tokens(command)
    )


def _written_after(path: Path, since: float | None) -> bool:
    """Did this path land after the session opened? `since is None` leaves the gate off."""
    if since is None:
        return True
    try:
        return path.stat().st_mtime >= since
    except OSError:  # pragma: no cover — a file that vanished between glob and stat
        return False


@dataclass(frozen=True, slots=True)
class DigestPredicate(TaskPredicate):
    """`python -m digest.cli --group-key <fixture key> --stub` exits 0.

    `--stub` is mandatory and S-29 says why: the un-stubbed path spawns nested `claude` calls
    that would draw the seat invisibly, and the scrubbed `PATH` cannot find the binary anyway
    (folded: S-31). A session that ran the CLI without it did not do the task.
    """

    task: str = TASK_DIGEST
    invocations: tuple[str, ...] = DIGEST_INVOCATIONS

    def is_success(
        self, event: TranscriptEvent, clone: Path | None = None, since: float | None = None
    ) -> bool:
        if not self.is_candidate(event):
            return False
        command = canonical_command(_bash(event))
        return (
            all(carries_flag(command, flag) for flag in DIGEST_REQUIRED_FLAGS)
            # A genuine zero, never an absent completion read as one (S-47): the real capture's
            # backgrounded run came back with no status at all and used to grade as exit 0.
            and event.exit_code == 0
        )


@dataclass(frozen=True, slots=True)
class RigPredicate(TaskPredicate):
    """`python -m rig.cli open <record>` reaches its documented `credential-missing` refusal.

    Two arms; see the module docstring and dispatch-14 ledger D14-1.
    """

    task: str = TASK_RIG
    invocations: tuple[str, ...] = RIG_INVOCATIONS

    def ruled_arm(self, event: TranscriptEvent) -> bool:
        """S-29's shape, verbatim: exit 2 with the token in what came back.

        The token is read off the result here and only here, and it is safe because the exit
        code carries the weight: a session that merely printed `credential-missing` did not
        also make the CLI exit 2.
        """
        return event.exit_code == RIG_RULED_EXIT and CREDENTIAL_MISSING in event.result_text

    def measured_arm(
        self, event: TranscriptEvent, clone: Path | None, since: float | None = None
    ) -> bool:
        """The shape this tree produces: the refusal, **persisted in the clone** (S-46).

        Checked against the tree and never against the transcript. Before S-46 this arm also
        accepted the token appearing anywhere in the result text, which made
        `echo credential-missing` a first success at zero exit — the finding the deep round
        opened on. What is asked now is that the rig wrote its own `run-output.json` during
        this session and that the refusal is in it.
        """
        if clone is None:
            return False
        for path in sorted(clone.glob(f".notes/rig/sessions/*/{RIG_RUN_OUTPUT}")):
            if not _written_after(path, since):
                continue
            if CREDENTIAL_MISSING in path.read_text(encoding="utf-8", errors="replace"):
                return True
        return False

    def is_success(
        self, event: TranscriptEvent, clone: Path | None = None, since: float | None = None
    ) -> bool:
        if not self.is_candidate(event):
            return False
        return self.ruled_arm(event) or self.measured_arm(event, clone, since)

    def summary_for(self, event: TranscriptEvent) -> str:
        for line in event.result_text.splitlines():
            if CREDENTIAL_MISSING in line:
                return line.strip()
        return last_meaningful_line(event.result_text)


@dataclass(frozen=True, slots=True)
class DashboardPredicate(TaskPredicate):
    """`python -m dashboard.cli` writes `index.html` (exit 0, or exit 1 with findings).

    The artifact half is checked against the **tree**, not the transcript: "writes `index.html`"
    is a fact about the clone, and a session that claimed to have written one would be a
    self-report. Neither half is model-authored.
    """

    task: str = TASK_DASHBOARD
    invocations: tuple[str, ...] = DASHBOARD_INVOCATIONS

    def artifact_path(self, clone: Path) -> Path:
        """`<clone>/.notes/gate-dashboard/index.html` — the workload's documented output."""
        return clone.joinpath(*DASHBOARD_OUTPUT_SEGMENTS, DASHBOARD_ARTIFACT)

    def wrote_the_artifact(self, clone: Path | None, since: float | None = None) -> bool:
        """The artifact, at its documented path, written after this session opened (S-46).

        Before S-46 this was `any(clone.rglob("index.html"))`, which a `touch index.html`
        anywhere in a 4000-file checkout satisfied — and which the workload's own tracked
        fixtures could satisfy on their own.
        """
        if clone is None:
            return False
        path = self.artifact_path(clone)
        return path.is_file() and _written_after(path, since)

    def is_success(
        self, event: TranscriptEvent, clone: Path | None = None, since: float | None = None
    ) -> bool:
        return (
            self.is_candidate(event)
            and event.exit_code in DASHBOARD_EXITS
            and self.wrote_the_artifact(clone, since)
        )


@dataclass(frozen=True, slots=True)
class SuitePredicate(TaskPredicate):
    """`uv run --no-project pytest -q` completes with a summary line.

    A collection abort is not a completion (dispatch-14 ledger D14-3): pytest prints
    `2 errors in 1.89s` under `Interrupted:` and no test has run. The counts recorded against
    S-29's 27/524/2406 come off the summary line, which is pytest's own output.
    """

    task: str = TASK_SUITE
    invocations: tuple[str, ...] = SUITE_INVOCATIONS

    def is_success(
        self, event: TranscriptEvent, clone: Path | None = None, since: float | None = None
    ) -> bool:
        """The summary must be on **this** candidate's own tool result (S-46).

        `event.result_text` is the result the CLI paired with this invocation, so a summary
        printed by some earlier command, quoted back in prose, or `cat`ted out of a log file
        cannot satisfy it.
        """
        return self.is_candidate(event) and bool(pytest_summary_line(event.result_text))

    def summary_for(self, event: TranscriptEvent) -> str:
        return pytest_summary_line(event.result_text) or last_meaningful_line(event.result_text)


#: One predicate per canonical task, keyed by the task name `OracleReport` carries.
PREDICATES: Final[dict[str, TaskPredicate]] = {
    TASK_DIGEST: DigestPredicate(),
    TASK_RIG: RigPredicate(),
    TASK_DASHBOARD: DashboardPredicate(),
    TASK_SUITE: SuitePredicate(),
}


def verdict_for(
    task: str,
    metrics: TranscriptMetrics,
    clone: Path | None = None,
    since: float | None = None,
) -> Verdict:
    """Grade one session against one task's predicate. The only grading path there is.

    Walks the tool uses in order and stops at the first one that satisfies the predicate; the
    step count is that invocation's one-based index among **all** tool uses, so setup, reading
    and failed attempts are all counted, which is what makes the number a measure of how hard
    the tree was to get going.

    When nothing satisfied it, the last *candidate* invocation still supplies `exit_code` and
    `summary_line` — S-29's "recorded as `first_success: false` with the reason".

    `since` is the session's start as a wall-clock epoch; see `TaskPredicate`. It is only ever
    read by the two predicates that check the clone, and only to ask whether the artifact they
    found is this session's doing rather than the tree's.
    """
    predicate = PREDICATES[task]
    last_candidate: TranscriptEvent | None = None
    for event in metrics.events:
        if predicate.is_candidate(event):
            last_candidate = event
            if predicate.is_success(event, clone, since):
                return Verdict(
                    first_success=True,
                    steps_to_first_success=event.index,
                    exit_code=event.exit_code,
                    summary_line=predicate.summary_for(event),
                )
    if last_candidate is not None:
        return Verdict(
            first_success=False,
            steps_to_first_success=None,
            exit_code=last_candidate.exit_code,
            summary_line=predicate.summary_for(last_candidate),
        )
    return Verdict(
        first_success=False,
        steps_to_first_success=None,
        exit_code=None,
        summary_line="the session never invoked the task's tool",
    )


__all__: Sequence[str] = (
    "CREDENTIAL_MISSING",
    "DASHBOARD_ARTIFACT",
    "DASHBOARD_EXITS",
    "DASHBOARD_INVOCATIONS",
    "DASHBOARD_OUTPUT_SEGMENTS",
    "DIGEST_INVOCATIONS",
    "DIGEST_REQUIRED_FLAGS",
    "PREDICATES",
    "RIG_INVOCATIONS",
    "RIG_RULED_EXIT",
    "RIG_RUN_OUTPUT",
    "SUITE_BASELINE",
    "SUITE_INVOCATIONS",
    "UV_PREFIXES",
    "DashboardPredicate",
    "DigestPredicate",
    "RigPredicate",
    "SuitePredicate",
    "TaskPredicate",
    "Verdict",
    "argv_tokens",
    "begins_with_invocation",
    "canonical_command",
    "carries_flag",
    "verdict_for",
)
