"""`BrainState` v2 — binding contract 1: the fixed core, and refuse-never-migrate.

`the build specification (not in this mirror)` § Deliverable 2's state table, decision 10. This is one of
the five contracts inherited from build 1. A.1's § Scaffold clause item 2 amends the latest
slots and seat-session key set and raises the state version to 2; the remaining core stays fixed.

**One fixed pydantic object owned by the runtime.** Adaptation is data, not a wider core:
a project extends state through the namespaced `extensions` registry, each with its own
version, and a core or extension version mismatch on resume is **refused, never migrated**.

Three fields exist because a slot no artifact carries does not survive a resume:

* **`window_len`** is set once at task start as `max(...) + 1` over the anterior cingulate's
  own weights (`protean.state.enums.window_len`) — derived from the thresholds the detectors
  read, never a literal, so retuning a threshold retunes the window.
* **`trap_dismissals`** and `GoalItem`'s `replan_count` / `redirect_count` are the ladder's
  rungs counted somewhere durable; without them a resume forgets how far it climbed and the
  climb restarts.
* **`terminal`** is a **committed field, not a return value** (folded: A1-16). A terminal
  detected mid-tick is written at the boundary and the exit follows the commit — which is why
  it lives here rather than in the runtime's control flow.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from protean import config
from protean.state.base import ProteanModel
from protean.state.enums import TerminalState
from protean.state.interrupts import OpenInterrupt, ResolvedInterrupt
from protean.state.primitives import (
    CeilingOverrides,
    Constraint,
    CostCounters,
    GoalItem,
    Modulators,
    PathBaseline,
    ProjectExtension,
    UnitObservation,
    WorkUnit,
)
from protean.state.workspace import LatestOutputs


class BrainState(ProteanModel):
    """The fixed core at v2, with A.1's enumerated slot and seat-set amendments."""

    # identity — the checkpoint's key and the dedupe key of every record
    schema_version: int = config.BRAIN_STATE_SCHEMA_VERSION
    task_id: str
    tick: int = 0

    # goal stack — authoritative; the workspace's copy is a projection
    goals: list[GoalItem] = Field(default_factory=list)

    # work-unit stack — ids minted by the manager and kept across a re-plan
    units: list[WorkUnit] = Field(default_factory=list)

    # latest outputs — one typed, tick-stamped slot per node and per tier
    latest: LatestOutputs = Field(default_factory=LatestOutputs)

    # per-unit history — the six trap detectors read this and nothing else
    unit_windows: dict[str, list[UnitObservation]] = Field(default_factory=dict)

    # per-unit baseline — what `change_bytes` is derived against
    path_baselines: dict[str, dict[str, PathBaseline]] = Field(default_factory=dict)

    # window sizing — derived from the weights the detectors read
    window_len: int = 1

    # ladder counters — `no_progress_ticks` is DERIVED, never stored (folded: T-10)
    trap_dismissals: dict[str, dict[str, int]] = Field(default_factory=dict)

    # interrupts — a list, not a singular reference: one tick may carry several requests
    open_interrupts: list[OpenInterrupt] = Field(default_factory=list)
    resolved_interrupts: list[ResolvedInterrupt] = Field(default_factory=list)

    # seats — one session id per tier, both minted per task (folded: S-14). Build A.1 shrank
    # the key set by shrinking `config.TIERS` and by nothing else: a call that is not a seat
    # call is session-less and writes no entry here (folded: S-A31).
    seat_sessions: dict[str, str] = Field(default_factory=dict)

    # budget — written by the runtime at the boundary, never self-reported
    cost: CostCounters = Field(default_factory=CostCounters)
    ceiling_overrides: CeilingOverrides = Field(default_factory=CeilingOverrides)

    # channels — the director's only nudge surface
    modulators: Modulators = Field(default_factory=Modulators)
    constraints: list[Constraint] = Field(default_factory=list)

    # terminal — a committed field, not a return value
    terminal: TerminalState | None = None

    # extensions — adaptation is data
    extensions: dict[str, ProjectExtension] = Field(default_factory=dict)

    @field_validator("seat_sessions")
    @classmethod
    def _sessions_are_keyed_by_tier(cls, value: dict[str, str]) -> dict[str, str]:
        """Two seats — a third key is a contract break, not a typo.

        The validator is unchanged from build 1 and is the whole of contract 1's session-key
        amendment: it already refuses any key outside `config.TIERS`, so the key set became the
        two tiers by `TIERS` shrinking (`the build specification (not in this mirror)` § Scaffold clause
        item 2, folded: S-A27).
        """
        unknown = sorted(set(value) - set(config.TIERS))
        if unknown:
            raise ValueError(f"seat_sessions is keyed by tier; unknown keys {unknown}")
        return value

    def open_goals(self) -> list[GoalItem]:
        """"Goal stack empty" means no `open` goal; closed items are retained."""
        return [goal for goal in self.goals if goal.status == "open"]

    def occupies_root(self) -> bool:
        """A task whose committed `terminal` is anything but `done` occupies the brain root."""
        return self.terminal is not TerminalState.DONE
