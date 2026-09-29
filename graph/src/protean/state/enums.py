"""Every closed set in the build, and the weights keys the six trap detectors read.

`the build specification (not in this mirror)` § Deliverable 2 (the status, kind and source sets),
§ Deliverable 3 (the five terminal states), § Deliverable 4 (the six trap detectors and
their weights keys), § Deliverable 6 (the three tiers, the ladder counts).

**A closed set is a `StrEnum`, never a bare `str`.** That is the structural half of the
prison-smell question B7 rules on: a field whose values are enumerated here is one the schema
constrains, and `tests/state/prison_smell.py` counts exactly these against the free-text and
scored fields. Adding a member is a contract change; adding a *new* enum is a change to the
ratio the reporter prints.

**The literals `protean.config` owns are asserted against, not restated.** `config` is the
single owner of the node order, the tier list and the terminal-state names (§ Deliverable 3:
"a literal in `config.py` ... never hardcoded"); this module builds its enums beside them and
fails at import if the two ever disagree, so there is no second place to edit.

**The weights keys are data about data.** Deliverable 4's table names one to two keys per
detector, and § Deliverable 6 fixes the single-owner rule: trap and streak thresholds live in
`brain/nodes/anterior_cingulate/weights.yaml`, ladder counts in the cortex's, and `rut_ticks`
exists in exactly one file in the whole brain. The mappings below are what
`tests/state/test_brain_tree.py` checks the seeded files against — no node module contains a
threshold literal, so this is the only place the *names* appear at all.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping

from protean import config


class NodeName(StrEnum):
    """The six node folders — five deterministic plus the cortex seat (decision 23)."""

    HOMEOSTASIS = "homeostasis"
    HIPPOCAMPUS = "hippocampus"
    THALAMUS = "thalamus"
    BASAL_GANGLIA = "basal_ganglia"
    CORTEX = "cortex"
    ANTERIOR_CINGULATE = "anterior_cingulate"


class Tier(StrEnum):
    """The cortex's two seats (`the build specification (not in this mirror)` § Deliverable 3).

    Three tiers is still the ceiling and tier three is **not a seat**: it is a specialized
    subagent library the manager dispatches, so it has no member here. A dispatch is addressed
    by the call type `CallType.DISPATCH`, never by a tier, which is why `ExecutorSummary` now
    carries `emitter: "dispatch"` — contract 2 lost a tier, not a model.
    """

    DIRECTOR = "director"
    MANAGER = "manager"


class CallType(StrEnum):
    """The four call-type addressees (§ Deliverable 2's table, § Deliverable 4's legality table).

    `think`, `escalate` and `delegate` are the three possibilities an outer node has and there
    is no fourth (decision 6); `dispatch` is the manager's own wave. `config.CALL_TYPES` is the
    owner of the literal and this enum is asserted against it at import, exactly as `Tier` is
    asserted against `config.TIERS`.
    """

    THINK = "think"
    ESCALATE = "escalate"
    DELEGATE = "delegate"
    DISPATCH = "dispatch"


#: The port's first argument (decision 10): a `Tier` for a seat call, a `CallType` otherwise.
#: One port, many callers — a second type here would be a second code path for containment, the
#: caps and the journal, which is what decision 10 exists to forbid.
Addressee = Tier | CallType


class TerminalState(StrEnum):
    """Five terminal states, five distinct exit codes (§ Deliverable 3, decision 18)."""

    DONE = "done"
    BLOCKED = "blocked"
    STOPPED = "stopped"
    INTERRUPTED = "interrupted"
    STUCK = "stuck"


class GoalStatus(StrEnum):
    """"Goal stack empty" means no `open` goal; closed items are retained."""

    OPEN = "open"
    SATISFIED = "satisfied"
    ABANDONED = "abandoned"


class UnitStatus(StrEnum):
    """A `match` verdict sets `passed`; the manager may set `abandoned`."""

    PENDING = "pending"
    ACTIVE = "active"
    PASSED = "passed"
    ABANDONED = "abandoned"


class SelectionDecision(StrEnum):
    """The gate's verdict. `no_go` is contractual inhibition, never a weighed signal."""

    GO = "go"
    NO_GO = "no_go"


class ConstraintKind(StrEnum):
    """Typed, never free text (§ Deliverable 2, `Constraint`)."""

    PATH_SCOPE = "path_scope"
    ALLOW_IRREVERSIBLE = "allow_irreversible"
    BUDGET = "budget"


class ExpectationKind(StrEnum):
    """One deterministic predicate over an `ExecutorSummary` (§ Deliverable 2)."""

    FILE_EXISTS = "file_exists"
    FILE_ABSENT = "file_absent"
    FILE_CONTAINS = "file_contains"
    SUMMARY_FIELD_EQUALS = "summary_field_equals"
    EXIT_CODE = "exit_code"


class MismatchClass(StrEnum):
    """The manager classifies the mismatch; the monitor never does (folded: S-12)."""

    APPROACH_WRONG = "approach_wrong"
    EXECUTION_SLIP = "execution_slip"


class InterruptKind(StrEnum):
    """The closed `kind` set, and there are exactly two licensed raisers
    (§ Deliverable 5): `question` is a node's ordinary output, `stuck` is the runtime's."""

    QUESTION = "question"
    STUCK = "stuck"


class Raiser(StrEnum):
    """Who may raise. The runtime is licensed for `stuck` and for no other kind.

    **Widened in build A.1** (§ Scaffold clause, contract 4's first amendment): the five outer
    nodes, the two seats and the runtime, plus a member per **call type** — a subagent and a
    non-seat call had nowhere legal to sit before. `planner` and `executor` are gone with their
    tiers. A call-bearing raiser's interrupt id widens to `(task, tick, node, raiser, call#,
    member#)` so two members of one wave cannot collapse onto one filename; that widening is
    order W8's, and the raisers are authored here for the whole build.
    """

    HOMEOSTASIS = "homeostasis"
    HIPPOCAMPUS = "hippocampus"
    THALAMUS = "thalamus"
    BASAL_GANGLIA = "basal_ganglia"
    ANTERIOR_CINGULATE = "anterior_cingulate"
    DIRECTOR = "director"
    MANAGER = "manager"
    DISPATCH = "dispatch"
    THINK = "think"
    ESCALATE = "escalate"
    DELEGATE = "delegate"
    RUNTIME = "runtime"


class TraceKind(StrEnum):
    """Two kinds on one append-only file (binding contract 3)."""

    PREDICTION = "prediction"
    OUTCOME = "outcome"


class TraceSource(StrEnum):
    """`prediction` takes `node` | `runtime` | `firing`; `outcome` takes `runtime_grade` |
    `operator_answer` | `firing_grade`.

    `runtime` is the one synthetic prediction minted at a `stuck` raise (folded: T-7).
    `TraceRecord` enforces the per-kind split, which is what lets an interrupt resolution and
    an ordinary grading land at the same resume tick without colliding on the dedupe key.

    **`firing` and `firing_grade` are build A.1's two additions** (§ Scaffold clause, contract
    3's fourth and fifth amendments). The trace's dedupe key is `(task, tick, node, tier, kind,
    source)`, so a node recording both a firing prediction and its own ordinary prediction in
    one tick would collide — homeostasis is the live case, since its full report is never
    skippable and only its think call is. The two values are authored here for the whole build;
    **the per-kind source validator that admits them is order W7's**, not W1's.
    """

    NODE = "node"
    RUNTIME = "runtime"
    FIRING = "firing"
    RUNTIME_GRADE = "runtime_grade"
    OPERATOR_ANSWER = "operator_answer"
    FIRING_GRADE = "firing_grade"


class EpisodeKind(StrEnum):
    """One record per tick; `event` records are runtime-authored (§ Deliverable 2)."""

    TICK = "tick"
    EVENT = "event"


class EventName(StrEnum):
    """The runtime-authored `event` episodes § Deliverable 3 names, and no others."""

    TASK_START = "task_start"
    LOCK_RECLAIMED = "lock_reclaimed"
    INTERRUPT_RESOLVED = "interrupt_resolved"
    TERMINAL = "terminal"
    TERMINAL_LOSER = "terminal_loser"
    ABANDONED = "abandoned"
    RESEEDED = "reseeded"


class Escalation(StrEnum):
    """Why the router is handing this tick to a judgment seat (§ Deliverable 6).

    The ladder's rungs read off this: a trap signal or a mismatch streak or a veto escalates
    a unit to the **manager** (rung 1, always the manager); `replan_exhausted` climbs to the
    director (rung 2); `redirect_exhausted` is rung 3, which ends the task `stuck`.
    """

    EMPTY_UNIT_STACK = "empty_unit_stack"
    MISMATCH_STREAK = "mismatch_streak"
    TRAP_SIGNAL = "trap_signal"
    VETO = "veto"
    REPLAN_EXHAUSTED = "replan_exhausted"
    REDIRECT_EXHAUSTED = "redirect_exhausted"

class TrapDetector(StrEnum):
    """Six of the eight metacognitive traps, measurable from what the loop records."""

    DISLODGING = "dislodging"
    FORMING = "forming"
    LOCATION = "location"
    INTERRUPTION = "interruption"
    MISLEADING = "misleading"
    PROGRESSION = "progression"


# --------------------------------------------------------------------------------------
# Weights keys — named once, in one place, and owned by exactly one file each
# --------------------------------------------------------------------------------------

#: Detector → the weights keys § Deliverable 4's table names for it. Every one of these lives
#: in `brain/nodes/anterior_cingulate/weights.yaml`; none is a literal in any node module.
TRAP_WEIGHT_KEYS: Final[Mapping[TrapDetector, tuple[str, ...]]] = MappingProxyType(
    {
        TrapDetector.DISLODGING: ("rut_ticks", "rut_delta_max"),
        TrapDetector.FORMING: ("forming_ticks",),
        TrapDetector.LOCATION: ("rework_spike_ratio", "rework_window"),
        TrapDetector.INTERRUPTION: ("abandon_count", "abandon_window"),
        TrapDetector.MISLEADING: ("mislead_window", "mislead_rise"),
        TrapDetector.PROGRESSION: ("uncited_ratio",),
    }
)

#: The router's streak threshold. § Deliverable 6: "the streak and trap thresholds live in
#: `brain/nodes/anterior_cingulate/weights.yaml` beside the detectors that compute them".
MONITOR_ROUTER_KEYS: Final[tuple[str, ...]] = ("mismatch_streak",)

#: Every **trap and streak** key the anterior cingulate's weights file carries — the keys a
#: detector or the router reads. Its `firing_threshold` is build A.1's (§ Deliverable 1) and is a
#: per-node key every firing-bearing folder owns its own copy of, read by no router, so it is
#: deliberately not in this tuple (folded: D15-7).
ANTERIOR_CINGULATE_WEIGHT_KEYS: Final[tuple[str, ...]] = tuple(
    sorted({key for keys in TRAP_WEIGHT_KEYS.values() for key in keys} | set(MONITOR_ROUTER_KEYS))
)

#: `window_len` is set once at task start as `max(...) + 1` over exactly these keys
#: (§ Deliverable 2, window sizing) — derived from the weights the detectors read, never a
#: literal, so retuning a threshold retunes the window.
WINDOW_LEN_KEYS: Final[tuple[str, ...]] = (
    "rut_ticks",
    "forming_ticks",
    "rework_window",
    "abandon_window",
    "mislead_window",
)

#: `brain/nodes/cortex/weights.yaml` carries only these four (§ Deliverable 6). Build A.1
#: re-keys the third from `planner_horizon` to `manager_horizon` with the tier it names — still
#: four keys, still the ladder's counts and nothing else.
CORTEX_WEIGHT_KEYS: Final[tuple[str, ...]] = (
    "k_replan",
    "k_redirect",
    "manager_horizon",
    "progress_window",
)

#: The one key § Deliverable 2 names for the hippocampus: how many of this task's episode
#: records the runtime's boundary loader projects onto `HippocampusInput`.
HIPPOCAMPUS_WEIGHT_KEYS: Final[tuple[str, ...]] = ("candidate_window",)


def window_len(weights: Mapping[str, object]) -> int:
    """`max(rut_ticks, forming_ticks, rework_window, abandon_window, mislead_window) + 1`.

    Takes the anterior cingulate's loaded `weights.yaml`. Raises `KeyError` on a missing key
    rather than defaulting: a window silently shorter than a detector's threshold makes that
    detector unreachable, which is the failure mode Ruling 16(b) is guarding against.
    """
    return max(int(weights[key]) for key in WINDOW_LEN_KEYS) + 1


# --------------------------------------------------------------------------------------
# `config` is the owner; this module only agrees with it
# --------------------------------------------------------------------------------------

_MISMATCHES = {
    "NODE_ORDER": (tuple(sorted(config.NODE_ORDER)), tuple(sorted(NodeName))),
    "TIERS": (tuple(sorted(config.TIERS)), tuple(sorted(Tier))),
    "CALL_TYPES": (tuple(sorted(config.CALL_TYPES)), tuple(sorted(CallType))),
    "TERMINAL_STATES": (tuple(sorted(config.TERMINAL_STATES)), tuple(sorted(TerminalState))),
}
for _name, (_literal, _members) in _MISMATCHES.items():
    if _literal != _members:
        raise ImportError(
            f"protean.config.{_name} and its StrEnum have diverged: "
            f"{_literal} vs {_members} — config.py is the owner, fix it there"
        )
del _MISMATCHES, _name, _literal, _members
