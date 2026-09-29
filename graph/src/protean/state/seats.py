"""The seat wire shape and the per-**addressee** result models — binding contract 2.

**Build A.1 amends this contract in three named ways and no others** (`the build specification (not in this mirror)`
§ Scaffold clause item 2). (a) The result literals become **per-addressee rather than per-tier**:
`ExecutorSummary.emitter` moves from `Literal["executor"]` to `Literal["dispatch"]`, and the decode
table gains the non-seat returns `ThinkResult`, `ManagerReply` and `DelegateReturn` beside it.
(b) The planner pair becomes the **manager pair** — `PlannerPlan` → `ManagerPlan`, the payload kept
whole. (c) **`WaveMember` replaces `ExecutorRequest`** as the dispatch member's request model, and
`ExecutorRequest` is retired. **The wire shape is unchanged**: one envelope, one decode path, the
same required facts.

`the build specification (not in this mirror)` § Deliverable 2's contract table and § Deliverable 6's
wire-shape bullets. Nothing in this module is a builder's default: the per-tier request and
result models and the `SeatEnvelope` wire shape are one of the five contracts build 2
inherits unchanged (§ Scaffold clause).

**`SeatEnvelope` is the one extra-tolerant model in the build.** It models the
`--output-format json` envelope a CLI seat returns, and § Deliverable 6 fixes four *measured*
facts as required fields so that a mock cannot be tidier than the thing it stands in for:

1. `stop_reason` is present, and `"tool_use"` is what structured success looks like — a seam
   that accepted only `end_turn` would raise on every success;
2. `result` is a JSON **string** that must parse before validation, never a parsed object;
3. `modelUsage` is present and carries a second, haiku-tier overhead entry beside the
   first-party call — an assertion about model calls reads "no model *beyond* the overhead
   call", which is why `first_party_models()` takes the overhead prefix as an argument;
4. `usage.cache_read_input_tokens` is present, so a cache receipt exists in the envelope.

**The overhead model prefix is not a literal in this module, and that is M21's doing.** No
module under `src/protean/` outside the licensed `cortex/` and `oracle/` packages may name
the CLI binary or its model ids. The seat adapters own this literal and pass it in; the state
layer states the *fact* without owning the model string.

Unknown fields are accepted **and preserved**, because build 2 captures a real envelope and
*diffs* it against this model; a model that rejected the first unexpected field would turn
that measurement into a crash. The tolerance is asymmetric on purpose: an envelope missing
any of the four facts is still refused. `tests/state/test_seat_envelope.py` holds both halves.

The field is spelled `modelUsage`, not `model_usage`, because it is a wire key rather than a
Python name — renaming it would put a translation layer between the mock and the thing it is
supposed to be identical to.

**Every result model carries the interrupt slot** (§ Deliverable 5): a seat's request travels
inside `SeatEnvelope.result` and is lifted onto the result model by the adapter (folded: U-2).
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import Field, JsonValue, field_validator

from protean.state.base import ExtraTolerantModel, ProteanModel
from protean.state.enums import MismatchClass, TrapDetector
from protean.state.interrupts import InterruptRequest
from protean.state.primitives import (
    Constraint,
    GoalItem,
    Modulators,
    WorkspaceObservation,
    WorkUnit,
)

#: What structured success looks like: `--json-schema` is a forced tool call.
STRUCTURED_SUCCESS_STOP_REASON = "tool_use"

#: The cache receipt § Deliverable 6 requires to exist in the envelope.
CACHE_READ_KEY = "cache_read_input_tokens"


class SeatEnvelope(ExtraTolerantModel):
    """The seat's `--output-format json` envelope. Four facts required, extras preserved."""

    stop_reason: str
    result: str
    modelUsage: dict[str, dict[str, JsonValue]]
    usage: dict[str, JsonValue]

    @field_validator("result")
    @classmethod
    def _result_parses_as_json(cls, value: str) -> str:
        """Fact 2: a JSON string that must parse *before* validation, never a parsed object."""
        try:
            json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"result must be a JSON string that parses before validation: {exc}"
            ) from exc
        return value

    @field_validator("usage")
    @classmethod
    def _usage_carries_the_cache_receipt(
        cls, value: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        """Fact 4: `usage.cache_read_input_tokens` is present, so a cache receipt exists."""
        if CACHE_READ_KEY not in value:
            raise ValueError(f"usage must carry {CACHE_READ_KEY!r}; got keys {sorted(value)}")
        return value

    def parsed_result(self) -> JsonValue:
        """`result`, parsed. The string is what is stored; this is what a caller reads."""
        return json.loads(self.result)

    def first_party_models(self, overhead_prefix: str) -> tuple[str, ...]:
        """Every `modelUsage` key that is not the overhead call — fact 3's assertion surface.

        `overhead_prefix` is required rather than defaulted: the literal is the seat adapters'
        to hold, and no module here may name it (M21).
        """
        return tuple(sorted(m for m in self.modelUsage if not m.startswith(overhead_prefix)))

    def is_structured_success(self) -> bool:
        """Fact 1, as a question rather than a constraint on the field."""
        return self.stop_reason == STRUCTURED_SUCCESS_STOP_REASON


class SeatResult(ProteanModel):
    """The shape every addressee's result shares. Not itself a contract — never instantiated."""

    tick: int
    interrupt: InterruptRequest | None = None


class DirectorDirection(SeatResult):
    """Director seat → runtime (folded: S-11). The only slice a director writes.

    Goal-stack edits, constraints and modulator fields — it never conducts a dispatch wave and
    never approves an action (`DIGEST:64`). `redirect_of` is what rung 3 counts.
    """

    emitter: Literal["director"] = "director"
    goals_pushed: list[GoalItem] = Field(default_factory=list)
    goals_closed: list[str] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    modulators: Modulators | None = None
    redirect_of: str | None = None
    cited_ids: list[str] = Field(default_factory=list)


class WaveMember(ProteanModel):
    """One member of the tick's dispatch wave — contract 2's third amendment (folded: S-A68).

    The kind, the unit id and a **reference** to this tick's admitted context, and **no path
    field**. The retired `ExecutorRequest`'s required `workspace_path` is the reason: a member
    request that *can* name a directory is one a later build has to defend, because `--add-dir`
    follows whatever value reaches the spawn. The workspace a member sees is filled by the
    **runtime** from the tick context; the manager's own output never names one.

    **The refusal at the spawn is landed** (`the build specification (not in this mirror)`
    § Deliverable 3, route row R15, folded: S-i22): a member payload carrying a fourth key — or any
    key naming a path, at any depth — is refused **before any process is created**, and `--add-dir`
    is built from the **runtime's own workspace value**, there being no payload channel for one to
    arrive on. A.1 owed the shape half, which is the field that value would have travelled in,
    removed (§ Deliverable 4); this model still carries **exactly three fields**.
    """

    kind: str
    unit_id: str
    #: A reference to this tick's `AdmittedContext`, never the context itself and never a path.
    admitted_ref: str


class ManagerPlan(SeatResult):
    """Manager seat → runtime (folded: S-11, folded: S-12, folded: S-A27).

    Build 1's `PlannerPlan`, **renamed rather than replaced** because the payload survives the
    rename whole: work units with ids minted here and kept across re-plans; the mismatch
    classification the monitor never makes; and `trap_dismissed`, which resets a detector's
    window for a unit and is itself a prediction the manager is graded on (Ruling 16 (a) and
    (c)).

    **Plus the tick's dispatch wave**, an ordered `list[WaveMember]` (§ Deliverable 3). One
    wave per tick and **only the manager assembles it**, which is what makes the
    one-observation-per-unit rule well-defined: one producer per tick, so nothing to fold
    across waves. An escalate reply to a pre-cortex node **proposes** members; the manager
    includes or drops each proposal at its own step. On a director tick no wave is assembled at
    all. **Dispatching the wave is order W8's**; the field is authored here with the model.
    """

    emitter: Literal["manager"] = "manager"
    units: list[WorkUnit] = Field(default_factory=list)
    goals_satisfied: list[str] = Field(default_factory=list)
    mismatch_class: MismatchClass | None = None
    trap_dismissed: list[TrapDetector] = Field(default_factory=list)
    cited_ids: list[str] = Field(default_factory=list)
    #: The tick's single dispatch wave, in the order the runtime hands the members to the seam —
    #: which is the order `member#` is assigned in (§ Deliverable 4).
    wave: list[WaveMember] = Field(default_factory=list)


class ManagerReply(SeatResult):
    """The **escalate** return: a short answer to one node's escalation (§ Deliverable 3).

    A separate small model rather than a `ManagerPlan` with most fields empty, deliberately: a
    return shaped like a plan would invite one to be returned by a tool-less call that decides
    nothing about the workspace. **It is not a plan and it authorizes no spawn** — the members
    it carries are *proposals*, which the manager includes or drops at its own step. Option A
    would be a slogan if a reply could spawn.
    """

    emitter: Literal["escalate"] = "escalate"
    answer: str = ""
    #: Proposed wave members, never authorized ones. A pre-cortex node's proposals reach this
    #: tick's wave; the monitor's, post-cortex, reach the next manager tick's.
    proposed: list[WaveMember] = Field(default_factory=list)


class ThinkResult(SeatResult):
    """The **think** return: an answer the calling node folds into its own output as a signal.

    § Deliverable 3's table names its four fields and folded: S-A84 closes the shape: "Like
    every other return it is a `SeatResult`, so it carries that frame's `tick` and its optional
    `interrupt` and adds nothing else."
    """

    emitter: Literal["think"] = "think"
    answer: str = ""
    confidence: float = 0.0
    cited_ids: list[str] = Field(default_factory=list)


class DelegateReturn(SeatResult):
    """The **delegate** return: information or a verdict, and **no observation field at all**.

    Option A's refusal is **structural here rather than a check** (folded: S-A84): a return with
    nowhere to put a workspace observation cannot assert a workspace change, which is what makes
    order W8's positive control a shape refusal rather than a threshold. Every change to the
    task's output traces to a manager dispatch; a node that believes the workspace needs
    changing **escalates**.
    """

    emitter: Literal["delegate"] = "delegate"
    #: The subagent kind that answered.
    kind: str = ""
    verdict: str | None = None
    information: str = ""
    cited_ids: list[str] = Field(default_factory=list)


class ExecutorSummary(SeatResult):
    """A manager **dispatch**'s return → runtime. What was done, observed rather than asserted.

    **The executor seat dies; this model lives** (decision 16, folded: A1-6). It is the shape a
    manager dispatch's return carries — an observation of the workspace after the work, still
    *observed, not asserted* — so `path_baselines`, the unit's pass, the monitor's verdict and
    build 3's kept expectations signal, now `dispatch_expectations`, keep their existing
    carrier. **Contract 2 loses a tier, not a model**: `emitter` moves from
    `Literal["executor"]` to `Literal["dispatch"]`, because the addressee it is emitted by is
    now a call type (folded: S-A1).

    `observations` are `WorkspaceObservation`s from the task workspace (folded: A1-15), so
    state derives from the observation and a re-run after a crash inside the seat call
    re-observes rather than trusting the invocation. `cited_ids` is the observable the
    thalamus's and hippocampus's predictions grade against. A wave's members merge into **one**
    of these before the monitor grades (§ Deliverable 3); the merge is order W8's.
    """

    emitter: Literal["dispatch"] = "dispatch"
    unit_id: str
    narrative: str
    observations: list[WorkspaceObservation] = Field(default_factory=list)
    exit_code: int = 0
    expectation_values: dict[str, JsonValue] = Field(default_factory=dict)
    cited_ids: list[str] = Field(default_factory=list)
