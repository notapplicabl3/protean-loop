"""The four canonical tasks — what the synthetic dev is asked, and what counts as done.

`the build specification (not in this mirror)` § Deliverable 4, "The four canonical tasks" (`DIGEST:101`,
folded: S-29), and § Deliverable 5's workload paragraph.

**The prompt is what a coworker would receive, and nothing more.** It names the job in the
words the job would arrive in; it never names the command that satisfies it, never names a
flag, and never names a file to read. *Discovering* the command is the measurement — a prompt
that gave it away would measure typing speed. That is why `TaskSpec.prompt` and
`TaskSpec.success_predicate` are separate strings and why nothing concatenates them.

**`success_predicate` is S-29's sentence, verbatim.** It is what `OracleReport` carries and what
The operator reads at B13; the machinery that decides whether it was met lives in `predicates.py`, and
the two are kept apart so a change to the matcher can never quietly re-word the ruling.

**Two of the four are not "exit 0", and that is not a defect.** The rig succeeds by reaching its
documented `credential-missing` refusal — the credential-free frontier of the surface, since DEV
credentials never enter a clone — and the suite succeeds by completing to a summary line whose
counts are recorded against the 27/524/2406 baseline, because the suite exiting 0 is the
workload's goal and never its precondition.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from protean.state.oracle import (
    CANONICAL_TASKS,
    TASK_DASHBOARD,
    TASK_DIGEST,
    TASK_RIG,
    TASK_SUITE,
)

#: The shared opening every task's prompt carries. It establishes the role and the stopping
#: rule — "stop when the command has run" — so a session that has finished does not keep
#: spending, and it establishes that the tree is a normal checkout rather than an exercise.
PREAMBLE: Final[str] = (
    "You are a new developer who has just been given access to this repository. "
    "You have never seen it before. Work from what is in the tree."
)

#: The closing every task's prompt carries. `--add-dir` already confines the session to its own
#: clone; this says the same thing in the words a coworker would be told it in.
CLOSING: Final[str] = (
    "Work only inside this checkout. Stop as soon as the command has actually run — "
    "report what you ran and what it printed, and do not go on to fix anything."
)


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """One canonical task: what the dev is told, and what S-29 ruled counts as reaching it."""

    task: str
    prompt_body: str
    success_predicate: str

    @property
    def prompt(self) -> str:
        """The whole prompt, as the session receives it on argv."""
        return f"{PREAMBLE}\n\n{self.prompt_body}\n\n{CLOSING}"


DIGEST_SPEC: Final[TaskSpec] = TaskSpec(
    task=TASK_DIGEST,
    prompt_body=(
        "Set the project up so you can run its tools, then digest one ticket using this "
        "repository's digest command-line tool. Any one ticket will do."
    ),
    success_predicate=(
        "python -m digest.cli --group-key <fixture key> --stub exits 0"
    ),
)

RIG_SPEC: Final[TaskSpec] = TaskSpec(
    task=TASK_RIG,
    prompt_body=(
        "Set the project up so you can run its tools, then open a rig session over one of "
        "the digest records already in this checkout, using this repository's rig "
        "command-line tool."
    ),
    success_predicate=(
        "python -m rig.cli open <record> reaches its documented credential-missing refusal "
        "(exit 2 with that token on stderr)"
    ),
)

DASHBOARD_SPEC: Final[TaskSpec] = TaskSpec(
    task=TASK_DASHBOARD,
    prompt_body=(
        "Set the project up so you can run its tools, then render this repository's "
        "dashboard using its command-line tool."
    ),
    success_predicate=(
        "python -m dashboard.cli writes index.html (exit 0, or exit 1 with findings)"
    ),
)

SUITE_SPEC: Final[TaskSpec] = TaskSpec(
    task=TASK_SUITE,
    prompt_body=(
        "Set the project up so you can run its tools, then run this repository's test "
        "suite to completion and report the totals it finishes with."
    ),
    success_predicate=(
        "uv run --no-project pytest -q completes with a summary line, its failed/error/passed "
        "counts recorded against the 27/524/2406 baseline"
    ),
)

#: In `CANONICAL_TASKS` order, which is the order a run walks them in.
CANONICAL_TASK_SPECS: Final[tuple[TaskSpec, ...]] = (
    DIGEST_SPEC,
    RIG_SPEC,
    DASHBOARD_SPEC,
    SUITE_SPEC,
)

_BY_NAME: Final[dict[str, TaskSpec]] = {spec.task: spec for spec in CANONICAL_TASK_SPECS}


def task_spec(task: str) -> TaskSpec:
    """One task by name, or a refusal naming the four that exist."""
    if task not in _BY_NAME:
        raise KeyError(f"{task!r} is not one of the four canonical tasks: {list(CANONICAL_TASKS)}")
    return _BY_NAME[task]


__all__: Sequence[str] = (
    "CANONICAL_TASK_SPECS",
    "CLOSING",
    "DASHBOARD_SPEC",
    "DIGEST_SPEC",
    "PREAMBLE",
    "RIG_SPEC",
    "SUITE_SPEC",
    "TaskSpec",
    "task_spec",
)
