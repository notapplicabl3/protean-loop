"""The five terminal states, their conditions, and the precedence when several fire at once.

`the build specification (not in this mirror)` § Deliverable 3's terminal table and its precedence paragraph;
decision 18.

**`terminal` is a committed field, not a return value.** A condition detected mid-tick does not
shorten the tick: only the seat call is skipped, the remaining nodes run, the boundary commits,
and the process exits **after** the commit. This module answers "which condition fired" and
"which one wins"; the commit writes it and `protean.cli` reads its exit code from
`protean.config`.

**Precedence is `config.TERMINAL_PRECEDENCE`, not a comparison written here.** `interrupted` >
`stuck` > `stopped`; each losing condition is written as a `terminal_loser` `event` record and
re-evaluated at the first boundary after resume, where it fires again on its own terms.

**`stuck` is measured from committed state, not signalled by the seat layer.** The ladder's
third rung is "the director redirecting `k_redirect` times with no goal-stack progress", and
both numbers live in `brain/nodes/cortex/weights.yaml`, so the runtime reads the same file the
router does and the two can never disagree about what exhaustion is.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from protean import config
from protean.state.brain_state import BrainState
from protean.state.enums import TerminalState
from protean.state.outputs import HomeostasisReport
from protean.state.primitives import GoalItem

#: The cortex weights keys rung 3 reads.
WEIGHT_K_REDIRECT = "k_redirect"
WEIGHT_PROGRESS_WINDOW = "progress_window"


def exhausted_goal(
    state: BrainState, cortex_weights: Mapping[str, Any]
) -> GoalItem | None:
    """The open goal whose ladder is exhausted, if any — rung 3 of § Deliverable 6.

    Both arms are required (Ruling 16 (d)): the redirect count has to be spent **and** the goal
    stack has to have made no progress over `progress_window`. A count alone would end a task
    that is moving.
    """
    k_redirect = int(cortex_weights[WEIGHT_K_REDIRECT])
    window = int(cortex_weights[WEIGHT_PROGRESS_WINDOW])
    for goal in state.open_goals():
        if goal.redirect_count >= k_redirect and goal.no_progress_ticks(state.tick) >= window:
            return goal
    return None


def fired(
    state: BrainState,
    *,
    report: HomeostasisReport | None,
    raised_this_tick: bool,
    cortex_weights: Mapping[str, Any],
) -> list[TerminalState]:
    """Every terminal condition true at this boundary, unordered.

    `done` and `blocked` are the two goal-stack-empty branches and are mutually exclusive;
    `stopped`, `interrupted` and `stuck` are independent of them and of each other.
    """
    conditions: list[TerminalState] = []
    goals_open = bool(state.open_goals())
    has_open_interrupt = bool(state.open_interrupts) or raised_this_tick

    if not goals_open:
        conditions.append(
            TerminalState.BLOCKED if has_open_interrupt else TerminalState.DONE
        )
    if report is not None and report.stop:
        conditions.append(TerminalState.STOPPED)
    if raised_this_tick and goals_open:
        conditions.append(TerminalState.INTERRUPTED)
    if exhausted_goal(state, cortex_weights) is not None:
        conditions.append(TerminalState.STUCK)
    return conditions


def winner(conditions: Sequence[TerminalState]) -> TerminalState | None:
    """The condition that is committed. `config.TERMINAL_PRECEDENCE` is the only comparator."""
    if not conditions:
        return None
    return max(conditions, key=lambda state: config.TERMINAL_PRECEDENCE[str(state)])


def losers(conditions: Sequence[TerminalState]) -> list[TerminalState]:
    """Every condition that fired and did not win — each written as a `terminal_loser` event."""
    champion = winner(conditions)
    return [item for item in conditions if item is not champion]


def exit_code(terminal: TerminalState | str) -> int:
    """The process exit code for a committed terminal. `config` owns the table."""
    return config.TERMINAL_EXIT_CODES[str(terminal)]
