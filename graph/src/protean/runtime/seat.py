"""The seat port — the runtime's half of the cortex seam, and nothing of the adapter.

`the build specification (not in this mirror)` § Deliverable 3 → *Idempotency follows from purity, with one
named exception*, and § Deliverable 6 (the wire shape, the request-keyed responder, the router).

**The runtime holds the port; `src/protean/cortex/` holds the adapters.** This module declares
what the runtime calls and what it does with the answer:

* `SeatPort` — an **addressee** plus that addressee's request model in, a `SeatEnvelope` out.
  One callable, no session handling, no addressee choice, no result parsing. **Its callers are
  now the cortex step and every outer node's think, escalate and delegate**
  (`the build specification (not in this mirror)` § Deliverable 2, decision 10): the addressee is a
  `Tier` for a seat call and a **call type** — `think`, `escalate`, `delegate` or `dispatch` —
  for everything else, so one signature and one decode path carry every call in the tick. Three
  callers, never three ports: a second port would give containment, the caps and the journal a
  second code path, which is what decision 10 exists to forbid. **The runtime is the only thing
  that ever spawns**, and no seat process spawns a child. From build A.1.i the fifth optional seam,
  `spawns`, is how it spawns tier three: `spawn_desk_of(layer, task, tick, workspace)` answers the
  tick's one `SpawnDesk`, memoized per `(task, tick)`, one port instance per spawn — and it is
  still the runtime, through that desk, that spawns them (`the build specification (not in this mirror)`
  § Deliverable 4).
* `TierSelector` — the router's shape: workspace signals in, a `SeatSelection` out. It runs
  **every** tick, including one whose seat call is skipped: § Deliverable 3's two conditions
  skip the *call*, and selecting a tier is a pure function of workspace signals that costs
  nothing. Rung 1 of the ladder is always the manager (build A.1: the planner pair renamed, the
  executor seat removed), so there is always a tier to name.
  § Deliverable 6 puts the router's thresholds in `brain/nodes/*/weights.yaml` and its code in
  the cortex layer, so the runtime declares the seam and implements neither side.
* `SeatSelection` — which tier, and **why**: the escalation that fired, the unit it is about,
  and the trap evidence. The runtime builds `DirectorRequest` / `ManagerRequest` from it, so
  binding contract 2's request shapes are constructed in one
  place.
* `SeatCallFacts` — what one *invocation* was, as opposed to what it returned (build 2,
  folded: S-18). The port's signature has no room for it and `SeatEnvelope` is the wire, so a
  live call's own facts leave the layer through a second seam, `SeatLayer.calls()`, in the
  same shape S8-1 gave `sessions`: the runtime reads them after the port call and writes the
  record at the boundary, where `ref` exists. A retry yields two.
* `HabitFacts` — what one *habit-answered* tick was, when a compiled procedure answered and no
  call was made at all (build 3, P3). It leaves the layer through a third optional seam,
  `SeatLayer.habits`, and the runtime writes `habit_hits.jsonl` from it at the same boundary.

**Decoding the envelope is the runtime's, not the adapter's.** A replayed tick restores the
journaled envelope and never calls the adapter, so a decoder that lived in the adapter would
leave a replay with no result model at all. `decode_seat_result()` is therefore the same code
path on a live call and on a restore — which is the whole content of "a re-run restores it
instead of re-invoking the seat".

**Nothing here knows how a seat is executed.** No process is spawned, no binary is named, and
no module under `src/protean/` outside `src/protean/cortex/` and `src/protean/oracle/` may name
one — the **two** licensed packages build 2 landed, which is exactly what
`tests/test_zero_calls.py` pins (folded: S-A21). A.1 multiplied the *callers* and the list did
not grow.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any, Protocol, runtime_checkable

from pydantic import ValidationError

from protean.runtime.errors import SeatLayerUnavailable
from protean.state.calls import NodeCall, SpawnAudit
from protean.state.enums import Addressee, CallType, Escalation, NodeName, Tier
from protean.state.primitives import TrapScalar
from protean.state.seats import (
    DelegateReturn,
    DirectorDirection,
    ExecutorSummary,
    ManagerPlan,
    ManagerReply,
    SeatEnvelope,
    ThinkResult,
    WaveMember,
)
from protean.state.workspace import (
    DirectorRequest,
    ManagerRequest,
    Workspace,
)

#: What the runtime hands the port: a seat's own request model for a seat call, the C1
#: `NodeCall` itself for a think, escalate or delegate — which is what § Scaffold clause item 3
#: calls it, "one think/escalate/delegate **request**, its type, its caller and its `call#`" —
#: and a **`WaveMember`** for one member of the manager's dispatch wave, which is the member's
#: request model contract 2's third amendment names (§ Deliverable 3's table). No fourth shape
#: and no wrapper around the member: the workspace a member sees is filled by the **runtime**
#: from the tick context, never by a value the manager's own output carries, which is the whole
#: reason `ExecutorRequest`'s `workspace_path` was retired (§ Deliverable 4).
SeatRequest = DirectorRequest | ManagerRequest
PortRequest = SeatRequest | NodeCall | WaveMember

#: Every shape an envelope decodes to, seats and non-seat returns alike.
SeatResultModel = (
    DirectorDirection | ManagerPlan | ThinkResult | ManagerReply | DelegateReturn | ExecutorSummary
)

#: **One decode path, two tables** (§ Deliverable 2, folded: S-A1). Seats by `Tier` — tier three
#: is not a seat, so a dispatch has no row here — and the non-seat returns by call type. The
#: split is two tables rather than two paths on purpose: `decode_seat_result()` resolves the
#: model through whichever table the addressee belongs to and then runs the same code for a live
#: call, a habit hit and a journal restore alike.
_RESULT_MODELS: dict[Tier, type[SeatResultModel]] = {
    Tier.DIRECTOR: DirectorDirection,
    Tier.MANAGER: ManagerPlan,
}

_CALL_RESULT_MODELS: dict[CallType, type[SeatResultModel]] = {
    CallType.THINK: ThinkResult,
    CallType.ESCALATE: ManagerReply,
    CallType.DELEGATE: DelegateReturn,
    CallType.DISPATCH: ExecutorSummary,
}

#: The dotted path the operator surface resolves a seat layer from. W3 lands it; build 1's
#: seats are scripted, and nothing in this package imports it at module scope.
SEAT_LAYER_MODULE = "protean.cortex.layer"


@dataclass(frozen=True, slots=True)
class SeatSelection:
    """Which tier runs this tick, and the reason the router chose it.

    `escalation` is carried for both seats, so the recorded escalation sequence a stuck
    scenario is graded on is readable off the selections alone. **It is `None` on the
    fall-through arm** — the non-escalated acting tick A.1 moved from the deleted executor seat
    to the manager — and `ManagerRequest.escalation` is optional for exactly that tick
    (contract 2's fourth amendment, folded: D3-4). Every other arm still names the rung.
    """

    tier: Tier
    escalation: Escalation | None = None
    unit_id: str | None = None
    trap_evidence: tuple[TrapScalar, ...] = field(default_factory=tuple)


@runtime_checkable
class SeatPort(Protocol):
    """Addressee + that addressee's request in, `SeatEnvelope` out. Implemented in `cortex/`.

    A `Tier` for a seat call and a **call type** for everything else (§ Deliverable 2,
    decision 10). The signature generalized rather than multiplied because a call type cannot
    travel a `Tier`-typed port and a second port would be a second code path for containment,
    the caps and the journal.
    """

    def __call__(
        self, addressee: Addressee, request: PortRequest
    ) -> SeatEnvelope:  # pragma: no cover
        ...


@runtime_checkable
class TierSelector(Protocol):
    """The router's shape: workspace signals in, the tier this tick belongs to out."""

    def __call__(self, workspace: Workspace) -> SeatSelection:  # pragma: no cover
        ...


@runtime_checkable
class SeatSessions(Protocol):
    """The layer's seat session handles, read at a boundary and handed back on a resume.

    § Deliverable 6's *fresh per task, cached within task* ends "checkpointed in
    `BrainState.seat_sessions` so a resume in a new process reuses them". Minting belongs to the
    adapter and the checkpoint belongs to the runtime, so the two need one seam and no more:
    the runtime reads the open task's two seat handles at the boundary it commits, and hands the
    restored three back before the first tick of a resume. Nothing else crosses it.
    """

    def for_task(self, task_id: str) -> dict[str, str]:  # pragma: no cover
        ...

    def restore(self, task_id: str, handles: Mapping[str, str]) -> None:  # pragma: no cover
        ...


#: `SeatCallFacts.outcome`, the closed set (build 2, folded: S-7, folded: S-8).
#:
#: `ok`            — the invocation returned an answer that decoded.
#: `decode_retry`  — its answer did not decode and a second invocation followed.
#: `unavailable`   — it produced no usable answer and none follows: a refusal, or the second
#:                   decode failure, which raises rather than retrying again.
OUTCOME_OK = "ok"
OUTCOME_DECODE_RETRY = "decode_retry"
OUTCOME_UNAVAILABLE = "unavailable"
SEAT_CALL_OUTCOMES: tuple[str, ...] = (OUTCOME_OK, OUTCOME_DECODE_RETRY, OUTCOME_UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class SeatCallFacts:
    """One live invocation, as fact rather than as answer (build 2 § Deliverable 1, S-18).

    **Not a record.** `protean.state.seat_calls.SeatCallRecord` is the persisted artifact and
    the runtime composes it at the boundary, where `task`, `tick` and `ref` are known; this
    carries only what the *adapter* knows and nobody else can reconstruct — the argv as run,
    the resolved binary version, which session answered, what the seat was asked, how long it
    took, how it ended, and the envelope's own counters.

    It is a dataclass rather than a pydantic model on purpose: nothing persists it, and
    `protean.state` is where persisted contracts live.
    """

    tier: str
    argv: tuple[str, ...] = ()
    cli_version: str = ""
    session_handle: str = ""
    model: str = ""
    effort: str = ""
    permission_mode: str | None = None
    request: Mapping[str, Any] = field(default_factory=dict)
    wall_seconds: float = 0.0
    outcome: str = OUTCOME_OK
    usage: Mapping[str, Any] = field(default_factory=dict)
    model_usage: Mapping[str, Any] = field(default_factory=dict)
    num_turns: int | None = None
    error: str = ""
    # ------------------------------------------------------------------------------
    # **A spawn's own four, and the fifth that is not a receipt column**
    # (`the build specification (not in this mirror)` § Deliverable 6, folded: S-i4, folded: S-i57)
    # ------------------------------------------------------------------------------
    #
    # A per-member instance's facts are the **only** carrier between the spawn and the boundary: a
    # receipt composed from the single construction-time port instance sees no per-spawn instance at
    # all. So the four columns `SeatCallRecord` gains ride here, and `from_call()` reads them off
    # this object exactly as it reads `usage` and `argv`. **The port's signature does not move.**
    #
    # The first two are the **effective caps as they ran**; the last two are the witness. All four
    # are filled by the spawn desk (`protean.cortex.live.wave.SpawnDesk`), which is the one place
    # that holds the resolved kind block, the returned envelope and the tick's baseline together.
    #: The kind block's `max_call_usd` as this spawn ran under it.
    max_call_usd: float | None = None
    #: The kind block's `timeout_seconds` as this spawn ran under it.
    timeout_seconds: float | None = None
    #: The envelope's own `permission_denials`, as received.
    permission_denials: tuple[Mapping[str, Any], ...] = ()
    #: The four derived audit lists (I4 `SpawnWitness`'s `audit` half).
    audit: SpawnAudit | None = None
    #: **The fifth, and it is not a receipt column** (folded: S-i57, resolving W4's `BLOCKED` D9-3):
    #: the process **group** the child led, captured by `invoke.py`'s `_spawn()` off the
    #: `start_new_session=True` process it creates. The desk reads the group's live members off it at
    #: the join, which is the only witness there is of a grandchild that named the binary by absolute
    #: path (§ Named assumptions 7, row B51). `0` is "no process existed".
    pgid: int = 0
    #: **The directory the invocation ran in** (`the build specification (not in this mirror)`
    #: § Deliverables 1 and 4, § Scaffold clause 2(b)): a seat's per-task directory, a `calls:`
    #: block's throwaway, a spawn's scaffold or its workspace. The adapter's own fact, like the pgid:
    #: not persisted, and never a receipt column.
    cwd: str = ""


@runtime_checkable
class SeatCalls(Protocol):
    """The layer's second seam: the invocations the last port call made, in order.

    The same shape S8-1 gave `sessions` — a callable the layer exposes and the runtime reads at
    the boundary. A scripted layer has none; a live one returns one entry per invocation, so a
    decode retry returns two and a replayed tick (which makes no port call) returns nothing.
    """

    def __call__(self) -> tuple[SeatCallFacts, ...]:  # pragma: no cover
        ...


@dataclass(frozen=True, slots=True)
class HabitFacts:
    """One tick answered by a compiled habit rather than by a call (build 3, P3).

    `the build specification (not in this mirror)` § Deliverable 4. `SeatCallFacts` is its mirror image on
    the live side, and the split is the same: this carries only what the *matcher* knows, and
    the runtime composes `protean.state.habit_hits.HabitHit` at the boundary, where `task`,
    `tick` and `ref` are in hand.

    `envelope` is an ordinary `SeatEnvelope` and travels the ordinary path — one
    `decode_seat_result()` on a live call, on a journal restore and on a habit hit alike
    (§ Directional decisions 3). `procedure_id` and `matched_condition` are the two P3 fields an
    envelope has no room for, and `avoided_model` is what the answer stood in for.
    """

    tier: str
    envelope: SeatEnvelope
    procedure_id: str
    matched_condition: Mapping[str, Any] = field(default_factory=dict)
    avoided_model: str = ""


@runtime_checkable
class SeatHabits(Protocol):
    """The layer's third seam: the procedure set this task opened with, consulted before the port.

    Optional exactly as `sessions` and `calls` are, and read the same way — through the
    `*_of()` accessor below, never by asking the layer what kind of layer it is. A layer
    without it matches nothing and writes no `habit_hits.jsonl`.

    **It takes the request where `calls()` takes nothing**, because a habit is decided *before*
    the call rather than reported after it: the seat step consults it with the tier and the
    request and gets an answer or nothing (folded: S-18, ledger `D19-2`). The set it holds is
    loaded once at task open or resume and never changes under a task — a sleep run mid-task is
    refused (§ Directional decisions 16) — and the matcher behind it is pure.
    """

    def __call__(
        self, tier: Tier, request: SeatRequest, selection: SeatSelection | None = None
    ) -> HabitFacts | None:  # pragma: no cover
        ...


@dataclass(frozen=True, slots=True)
class PlannedCall:
    """One call a node's step makes this tick: the type, and the payload it carries.

    **The runtime declares the seam and implements neither side** — the same split
    `SeatCallFacts` and `HabitFacts` already take. A `PlannedCall` is turned into a C1
    `NodeCall` by `protean.cortex.calls`, which assigns the `call#` and addresses it; nothing
    here knows what a payload means.

    **What decides that a node calls is the runtime's call policy**
    (`the build specification (not in this mirror)` § Deliverable 1): `protean.runtime.triggers` produces a
    node's `PlannedCall`s each tick and the step hands them to the desk through the optional seam
    below. A fixture's plan still drives the scripted battery and **outranks the policy** for the
    node it names, and a layer without the seam plans nothing.
    """

    type: CallType
    payload: Mapping[str, Any] = field(default_factory=dict)
    #: The name of the model `payload` was dumped from, carried onto `NodeCall.payload_model`.
    payload_model: str = ""


@runtime_checkable
class TickCalls(Protocol):
    """One tick's node-call desk: what a node's step calls beside its body.

    `run()` issues that node's planned calls through the one port, in `call#` order, and hands
    back what each returned — an answer or a refusal. **The runtime never learns what a payload
    means**: the desk is `protean.cortex.calls`', exactly as the port is the adapters'.

    `handed` is the one optional parameter build A.2.i adds (`the build specification (not in this mirror)`
    § Scaffold clause item 2(a)): the plan the runtime's call policy made for this node this
    tick, a sequence of `PlannedCall`, defaulting to none handed. A desk issues its own static
    plan for a node that plan names, and otherwise exactly what it was handed.
    """

    def run(  # pragma: no cover
        self, node: NodeName, handed: Sequence[PlannedCall] = ()
    ) -> Sequence[Any]:
        ...


@runtime_checkable
class NodeCalls(Protocol):
    """The layer's fourth optional seam: the desk one tick's node calls are made through.

    Optional exactly as `sessions`, `calls` and `habits` are, and read the same way — through
    the `*_of()` accessor below, never by asking the layer what kind of layer it is. It is a
    **factory** rather than the desk itself because `call#` is per node *within a tick*, so the
    counter cannot outlive one.
    """

    def __call__(self, task: str, tick: int) -> TickCalls:  # pragma: no cover
        ...


@runtime_checkable
class TickSpawns(Protocol):
    """One tick's spawn desk: the tier-three processes this tick creates, and their facts.

    `the build specification (not in this mirror)` § Deliverable 4, seam contract **I5**. The desk is
    `protean.cortex.live.wave`'s, exactly as the port is the adapters' and the node-call desk is
    `protean.cortex.calls`': the runtime hands it a wave and reads its facts back, and **learns
    nothing about a kind block**.

    `dispatch_wave()` takes the members keyed by `member#` — assigned before anything starts,
    from the order the `ManagerPlan` listed them — plus the journal key's other two components,
    and, from `run_wave`, `units` — each member's unit id mapped to that unit's `intent`, the one
    keyword A.2 adds to this contract (`the build specification (not in this mirror)` § Deliverable 7, L20);
    `None` sends the two seed halves alone —
    and answers each member's envelope or that member's own fault as a value. The three
    pre-process refusals are raised instead, because they are facts about the wave rather than
    about one member.

    `spawns_of()` is the witness's only carrier and is keyed by the journal's own
    `(node, call#, member#)` rather than positionally (folded: S-i42): a receipt composed from
    the single construction-time port instance sees no per-spawn instance at all, and a
    pre-cortex delegate read positionally would meet a later member's facts.
    """

    def dispatch_wave(  # pragma: no cover
        self,
        members: Mapping[int, WaveMember],
        *,
        node: str = ...,
        call_number: int = ...,
        order: Sequence[int] = (),
        units: Mapping[str, str] | None = None,
    ) -> Mapping[int, Any]:
        ...

    def delegate(self, call: NodeCall) -> SeatEnvelope:  # pragma: no cover
        ...

    def spawns_of(self) -> Mapping[tuple[str, int, int | None], Any]:  # pragma: no cover
        ...


@runtime_checkable
class Spawns(Protocol):
    """The layer's **fifth** optional seam: the desk one tick's spawns are opened on (I5).

    Optional exactly as `sessions`, `calls`, `habits` and `node_calls` are, and read the same way
    — through the `*_of()` accessor below, never by asking the layer what kind of layer it is. A
    layer without it spawns nothing and writes no `SubagentSpawn` (row M3).

    It is a **factory** on `NodeCalls`' precedent, because a desk cannot outlive the tick that
    opened it — **with the one departure that makes the desk's identity a rule rather than a
    hope** (folded: S-i36): the seam is **memoized per `(task, tick)`** and hands the same desk
    back to every caller, where `NodeCalls` mints a fresh desk per call. A second resolution
    inside one tick therefore opens no second desk.

    `workspace` is the tick's own — `TickContext.workspace_path`, the only channel a path reaches
    a spawn on (folded: S-i22) — and it is honoured on the first resolution of a tick, which is
    what "handed the tick's workspace at open, from whichever caller opened it" means.
    """

    def __call__(  # pragma: no cover
        self, task: str, tick: int, workspace: str = ""
    ) -> TickSpawns:
        ...


@dataclass(frozen=True, slots=True)
class SeatLayer:
    """What the operator surface needs to run a tick: a router and a port, both W3's.

    `sessions` is optional because a layer that mints nothing has nothing to carry: `None` means
    the runtime writes no `seat_sessions` and restores none, which is exactly a hand-driven stub.
    `calls` is optional for the same reason: a scripted seat makes no invocation, so there is
    nothing for the boundary to record and `calls_of()` reads an empty tuple. `habits` is build
    3's and is optional for the third version of the same reason: a root with no compiled
    procedure has nothing to consult, so `habit_of()` answers `None` and no `habit_hits.jsonl`
    is ever written. It is filled by the **runtime** at task open, never by `build()`, which
    takes no argument and runs before a task exists (folded: S-18).
    """

    router: TierSelector
    port: SeatPort
    sessions: SeatSessions | None = None
    calls: SeatCalls | None = None
    habits: SeatHabits | None = None
    #: A.1's fourth optional seam: the calls a node's step makes. A layer without it makes
    #: none, which is why the whole landed battery keeps the tick it had.
    node_calls: NodeCalls | None = None
    #: A.1.i's **fifth** optional seam, contract I5: the desk a tick's tier-three spawns are
    #: opened on. Optional for the same reason the other four are — a layer without it spawns
    #: nothing and writes no `SubagentSpawn` (row M3) — and memoized per `(task, tick)`, so the
    #: tick has exactly one desk however many callers ask for it.
    spawns: Spawns | None = None


def calls_of(layer: SeatLayer) -> tuple[SeatCallFacts, ...]:
    """`layer.calls()` when the layer has the seam, else nothing.

    The runtime never asks a layer whether it is live; it asks whether the seam is there. That
    is what keeps the scripted path and the live path one code path at the boundary.
    """
    return () if layer.calls is None else tuple(layer.calls())


def habit_of(
    layer: SeatLayer,
    tier: Tier,
    request: SeatRequest,
    selection: SeatSelection | None = None,
) -> HabitFacts | None:
    """`layer.habits(...)` when the layer has the seam, else nothing.

    `calls_of()`'s rule one seam over: the seat step asks whether the seam is there, never
    whether the layer is live, scripted or habit-bearing — which is what keeps all three one
    code path through the port.
    """
    return None if layer.habits is None else layer.habits(tier, request, selection)


def tick_calls_of(layer: SeatLayer, task: str, tick: int) -> TickCalls | None:
    """`layer.node_calls(task, tick)` when the layer has the seam, else nothing.

    `calls_of()`'s rule a third seam over: a layer without it opens no desk, so a node's step
    reaches the cortex only where something said it should — which is every landed tick in the
    battery, unchanged.
    """
    return None if layer.node_calls is None else layer.node_calls(task, tick)


def spawn_desk_of(
    layer: SeatLayer, task: str, tick: int, workspace: str = ""
) -> TickSpawns | None:
    """`layer.spawns(task, tick, workspace)` when the layer has the seam, else nothing.

    `tick_calls_of()`'s rule a fourth seam over, **with that factory's one departure**
    (`the build specification (not in this mirror)` § Deliverable 4, folded: S-i36): the seam is
    memoized per `(task, tick)`, so this answers **the tick's one `SpawnDesk`** and a second call
    inside one tick opens no second desk. `None` where the seam is absent, which is every
    scripted layer and every tick builds 1, 2 and 3 ran (row M3).

    `workspace` is the tick's own value and is honoured by the **first** resolution of a tick, so
    whichever of the two openers reaches the desk first is the one that hands it the workspace.
    Resolving the desk **constructs** it and refuses nothing; the two pre-process refusals belong
    to the open the openers perform before their first spawn, which is why a tick with no wave
    and no delegate call refuses nothing at all.
    """
    if layer.spawns is None:
        return None
    return layer.spawns(task, tick, workspace)


class SeatDecodeError(ValueError):
    """A `SeatEnvelope.result` that does not validate against its tier's result model.

    Raised rather than tolerated: the envelope is extra-tolerant at the *wire*, but the result
    model inside it is an ordinary forbid-extras contract, and a seat that returned a shape the
    contract does not name is the mock shaping the contract — a blocker, not a warning.
    """


class IllegalReturn(ValueError):
    """A **legal shape at the wrong addressee** — refused by the table before the decoder.

    § Deliverable 4: "A shape-only check would pass an `ExecutorSummary` arriving on a
    **delegate**, which G5a must refuse." It is deliberately **not** a `SeatDecodeError`, and
    that is the whole of the retry rule: "the one decode retry runs before the table, for every
    call … a **legal** shape addressed to the wrong call type is not a decode failure and earns
    no retry — it is refused outright, which is what makes the positive control a refusal rather
    than a second spend." Build 2's single retry catches `SeatDecodeError` and this is not one,
    so no second invocation follows.
    """


class MemberUnfinished(ValueError):
    """A cap exceeded or a **timeout** on a `dispatch` member — the one member fault that is
    not `SeatUnavailable`.

    § Deliverable 4's third refusal class: "A cap exceeded or a timeout on a `dispatch` member →
    the **member** is marked failed and the wave is **partial**; the tick does not stop." It is
    declared here, with the rest of the seam, because the runtime is what reads it: the wave's
    merge turns a failed member into a `partial` observation, and the monitor grades no
    predicate at all against one. The site that **enforces** a cap is the `calls:` loader's
    (order W3, row G10); this is the class it refuses under for a member.

    **A.1.i gives it the producer A.1 declared and never wrote**
    (`the build specification (not in this mirror)` § Deliverable 4, folded: S-i41): the spawn desk
    re-raises a member's `CallCapExceeded` — a kill at the wall cap, or the dollar cap crossed —
    as this class, because `CallCapExceeded` is a `SeatConfigError` and **nothing in the tick
    catches that class**, so a member fault would otherwise tear the tick instead of failing one
    member. A **delegate's** is left alone: it is the calling node's refusal signal, not a wave
    fault.
    """


#: **The call type × shape legality table** (§ Deliverable 4), as one artifact: all four call
#: types **and** the two seats. A two-row table would refuse every think and escalate return,
#: which is the opposite of what the check exists for. Anything outside it is refused before it
#: reaches the decoder — which `addressee_of()` does, since a name that is neither a tier nor a
#: call type resolves to no row at all.
LEGAL_RETURNS: dict[Addressee, type[SeatResultModel]] = {**_RESULT_MODELS, **_CALL_RESULT_MODELS}

#: The field every return model carries its own name in — `manager`, `director`, `think`,
#: `escalate`, `delegate`, `dispatch`. It is the discriminator the table reads, because it is
#: what a return says it *is* before anything validates it.
EMITTER_FIELD = "emitter"


def legal_return(addressee: Addressee | str) -> type[SeatResultModel]:
    """The one shape this addressee may return. The table, as a lookup."""
    return LEGAL_RETURNS[addressee_of(addressee)]


def emitter_of(model: type[SeatResultModel]) -> str:
    """The literal one result model's `emitter` is pinned to — read off the model, never listed.

    A second list of emitter names would be a table that can disagree with the models it
    describes; this reads the `Literal` the contract already declares.
    """
    return str(model.model_fields[EMITTER_FIELD].default)


def check_legal_return(addressee: Addressee | str, payload: Any) -> None:
    """Refuse a return whose shape is not this addressee's, **before** it is decoded.

    The check is the addressee's row against what the return says it is. A payload carrying no
    `emitter` at all is a live seat's narrowed answer — the runtime fills the literal in
    `decode_seat_result()` — and reaches the decoder, where build 2's shape check and its one
    retry are unchanged. A payload that names a *different* addressee's shape is refused here,
    with no retry, however well formed it is.
    """
    resolved = addressee_of(addressee)
    expected = emitter_of(legal_return(resolved))
    if not isinstance(payload, Mapping):
        return
    declared = payload.get(EMITTER_FIELD)
    if declared is None or str(declared) == expected:
        return
    raise IllegalReturn(
        f"{resolved} may return a {expected!r} shape and nothing else; this return names "
        f"{str(declared)!r} — refused before the decoder, and a legal shape at the wrong "
        f"addressee earns no retry"
    )


def addressee_of(addressee: Addressee | str) -> Addressee:
    """A `Tier` or a `CallType`, resolved from either enum or from its own literal.

    One resolver rather than two call sites guessing: `config.ADDRESSEES` is `TIERS + CALL_TYPES`
    and the two sets are disjoint, so a name resolves to exactly one of them.
    """
    if isinstance(addressee, (Tier, CallType)):
        return addressee
    name = str(addressee)
    try:
        return Tier(name)
    except ValueError:
        pass
    try:
        return CallType(name)
    except ValueError:
        raise KeyError(f"{name!r} is not an addressee: a tier for a seat call, a call type otherwise")


def result_model(addressee: Addressee | str) -> type[SeatResultModel]:
    """The result model this addressee's envelope decodes to — one path, two tables."""
    resolved = addressee_of(addressee)
    if isinstance(resolved, Tier):
        return _RESULT_MODELS[resolved]
    return _CALL_RESULT_MODELS[resolved]


def decode_seat_result(
    tier: Addressee | str, envelope: SeatEnvelope, tick: int | None = None
) -> SeatResultModel:
    """`SeatEnvelope.result` → the addressee's typed result model.

    **The call type × shape legality table is checked first, before the decode**
    (`the build specification (not in this mirror)` § Deliverable 4): `check_legal_return()` refuses a
    return that names another addressee's shape, and it raises `IllegalReturn` rather than
    `SeatDecodeError` precisely so that build 2's one retry — which catches the latter — does
    not fire on it.

    **The addressee resolves the model and fills the `emitter`** (§ Deliverable 2,
    folded: S-A1): a `Tier` reaches the seat table, a call type the non-seat one, and the
    literal every return carries — `manager`, `think`, `escalate`, `delegate`, `dispatch` — is
    the addressee's own name. That is why `ExecutorSummary.emitter` moved to
    `Literal["dispatch"]` when its tier died: contract 2 lost a tier, not a model.

    Identical on a live call and on a journal restore. Any `InterruptRequest` the seat raised
    travels inside `result` (folded: U-2) and arrives on the result model's `interrupt` slot,
    which is how a seat raises without writing the mailbox.

    **`tick` is build 2's argument, and the decoder is where the runtime-owned fields are
    filled** (§ Directional decisions 10, folded: S-17, folded: S-36). A live seat is handed a
    *narrowed* schema — its result model minus `tick` and `emitter` — so its answer carries
    neither, while a scripted envelope carries both. Filling them here, before validation,
    is what makes those two envelopes decode to the same result model on the same code path.
    The CLI's raw envelope stays the record: nothing is written back to it.

    `tick=None` is the build-1 call: nothing is filled and an answer that omits `tick` is the
    decode failure it was then. Passing the tick never *loosens* the contract — an answer that
    named a different tick is overwritten by the runtime's, which is the same normalization the
    seat step already applied to `latest`.
    """
    resolved = addressee_of(tier)
    model = result_model(resolved)
    payload = envelope.parsed_result()
    # **The legality table runs here, before anything validates** (§ Deliverable 4): one place,
    # so a live call, a habit hit and a journal restore are all held to it, and so the `emitter`
    # the runtime fills below cannot overwrite the discriminator the check reads.
    check_legal_return(resolved, payload)
    if tick is not None and isinstance(payload, Mapping):
        payload = {**payload, "tick": tick, "emitter": str(resolved)}
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise SeatDecodeError(f"{model.__name__}: {exc}") from exc


def build_request(selection: SeatSelection, *, workspace: Workspace) -> SeatRequest:
    """The per-seat request, built by the runtime from the router's selection.

    Director: the compressed workspace only. Manager: the workspace, the escalation that fired —
    **or `None` on the fall-through, the non-escalated acting tick, which means "assemble the
    pending unit's wave"** (contract 2's fourth amendment, folded: D3-4) — and the unit's trap
    evidence.

    **There is no third branch** (§ Deliverable 3): the executor seat is gone, a dispatch is not
    a seat call, and its member requests are `WaveMember`s the **runtime** fills the workspace
    for — the manager's own output never names a path. Building one is order W8's.
    """
    tier = Tier(selection.tier)
    if tier is Tier.DIRECTOR:
        return DirectorRequest(workspace=workspace)
    return ManagerRequest(
        workspace=workspace,
        escalation=selection.escalation,
        unit_id=selection.unit_id,
        trap_evidence=list(selection.trap_evidence),
    )


def escalation_sequence(selections: Sequence[SeatSelection]) -> tuple[str, ...]:
    """The recorded tier climb across a run — the artifact a ladder scenario is graded on."""
    return tuple(str(item.tier) for item in selections if item is not None)



def resolve_seat_layer() -> SeatLayer:
    """Import the installed cortex seat layer, or refuse by name.

    Lazy and by dotted path because `src/protean/cortex/` is a separate order's package: a
    checkout without it can still `status` and `resume --abandon`, neither of which runs a node.
    """
    try:
        module = import_module(SEAT_LAYER_MODULE)
    except ImportError as exc:
        raise SeatLayerUnavailable(f"{SEAT_LAYER_MODULE} is not importable ({exc})") from exc
    builder = getattr(module, "build", None)
    if builder is None:
        raise SeatLayerUnavailable(f"{SEAT_LAYER_MODULE} exposes no `build()`")
    layer = builder()
    if not isinstance(layer, SeatLayer):
        raise SeatLayerUnavailable(f"{SEAT_LAYER_MODULE}.build() did not return a SeatLayer")
    return layer
