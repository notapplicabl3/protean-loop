"""The three call types — think, escalate and delegate — as three callers of the one port.

`the build specification (not in this mirror)` § Deliverable 2 (the three-type table, C1 `NodeCall`, the
addressee-keyed port, "a call mints no cortex prediction", session-lessness, and every fault on
a think/escalate/delegate being a signal) and § Directional decisions 4, 6 and 10.

**Three callers, never three ports** (decision 10, folded: A1-1). Each type builds a typed
payload, wraps it in W1's C1 `NodeCall` — which § Scaffold clause item 3 calls "one
think/escalate/delegate **request**" and which is therefore what travels the port's second
argument — and reaches the model through the one
`(addressee, request) -> SeatEnvelope`. A second port would give containment, the caps and the
journal a second code path, which is exactly what decision 10 exists to forbid.

**Nothing here spawns, opens a file or names a binary.** The desk holds a port and a counter.
The runtime carries the call; the calling node stays the pure callable it was.

**`call#` is per node within the tick, numbered from 1.** The node's own output entry is the
reserved `call# = 0` (§ Deliverable 6, folded: S-A76) and that reservation is order W4's, so
nothing here ever hands out a zero.

**`ref` is `None` for all three** (folded: S-A9). The cortex trace keeps one prediction per seat
per tick, minted at the seat call; think, escalate and delegate are the *calling node's* calls
and that node already records its one prediction for the tick, so N calls per node per tick
never contend for a single `ref`. `CallRecord.ref` is the field that says so, and it is `None`
by construction rather than by a writer remembering.

**Every fault is a signal, not a stop** (folded: S-A10, folded: S-A58). A cap exceeded, an
illegal return, a missing configuration and a call failure alike return a `CallRefusal` **to the
calling node**, which proceeds without the answer. The two classes that end the task — a fault
on a seat call, and a fault on a `dispatch` member — are order W8's; an advisory call never
reaches `SeatUnavailable`, because this module catches it and hands back a refusal.

**What is not here.** The `calls:` configuration blocks and their containment are order W3's;
journalling each call is order W4's and counting its spend is W5's; the call type × shape
legality table, the wave and the dispatch refusal classes are order W8's; a `kinds:` block and
any spawn path at all are build A.1.i's (§ Out of scope).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from protean.cortex.subagents import spawns_in
from protean.runtime.errors import SeatUnavailable
from protean.runtime.seat import (
    IllegalReturn,
    PlannedCall,
    SeatDecodeError,
    SeatPort,
    SeatResultModel,
    Spawns,
    TickSpawns,
    decode_seat_result,
)
from protean.state.base import ProteanModel
from protean.state.calls import NodeCall
from protean.state.enums import CallType, NodeName
from protean.state.seats import SeatEnvelope

#: The three an **outer node** may use, and no fourth (decision 6). `dispatch` is the manager's
#: own wave and is addressed at the cortex step, not from a node's, which is why it is not here.
NODE_CALL_TYPES: Final[tuple[CallType, ...]] = (
    CallType.THINK,
    CallType.ESCALATE,
    CallType.DELEGATE,
)

#: The four faults § Deliverable 2 names, as the refusal classes they return under. All four
#: are **signals**: the calling node proceeds without its answer and the tick continues.
#:
#: `cap_exceeded` is raised where the cap is enforced — the `calls:` blocks' loader, order W3's
#: row G10 — and carried here so the class set is closed at the deliverable's own four rather
#: than at what this order happens to be able to trigger.
REFUSAL_CAP_EXCEEDED: Final[str] = "cap_exceeded"
REFUSAL_ILLEGAL_RETURN: Final[str] = "illegal_return"
REFUSAL_NO_CONFIGURATION: Final[str] = "missing_configuration"
REFUSAL_CALL_FAILED: Final[str] = "call_failed"
REFUSAL_CLASSES: Final[tuple[str, ...]] = (
    REFUSAL_CAP_EXCEEDED,
    REFUSAL_ILLEGAL_RETURN,
    REFUSAL_NO_CONFIGURATION,
    REFUSAL_CALL_FAILED,
)


class CallConfigurationError(LookupError):
    """The layer has no answer configured for this addressee at all.

    A `missing_configuration` refusal rather than a crash: § Deliverable 2 lists it beside the
    other three faults, and a node whose think seam is unconfigured simply gets no answer.
    """


# --------------------------------------------------------------------------------------
# The typed payloads — one per call type
# --------------------------------------------------------------------------------------


class ThinkPayload(ProteanModel):
    """What a node asks itself a model about: its own question, on its own account.

    "the node calls a model for judgment or analysis on its own question" (§ Deliverable 2).
    The answer comes back as a `ThinkResult` and is a **signal**, never a decision about the
    workspace.
    """

    question: str
    context: str = ""


class EscalatePayload(ProteanModel):
    """What a node says to the manager: an overarching concern, or a proposal to reconsider.

    The reply may change the workspace **through the manager's own dispatch**, never through the
    escalating node, so nothing here names a path or an action.
    """

    concern: str
    unit_id: str | None = None
    proposal: str = ""


class DelegatePayload(ProteanModel):
    """What a node asks a specialized subagent for: information or a verdict (Option A).

    `kind` names the subagent kind asked for. **Which kinds exist, and how one is spawned and
    contained, is build A.1.i's** (§ Out of scope): in A.1 every delegate return is scripted.
    """

    kind: str
    question: str
    context: str = ""


_PAYLOAD_MODELS: Final[dict[CallType, type[ProteanModel]]] = {
    CallType.THINK: ThinkPayload,
    CallType.ESCALATE: EscalatePayload,
    CallType.DELEGATE: DelegatePayload,
}


def payload_model(call_type: CallType) -> type[ProteanModel]:
    """The payload model one call type carries. The third table this build has, and the smallest."""
    return _PAYLOAD_MODELS[CallType(call_type)]


# --------------------------------------------------------------------------------------
# What a call returns: an answer, or a refusal to the calling node
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CallRefusal:
    """A fault, returned to the calling node rather than raised past it.

    It is a dataclass and not a pydantic model for `SeatCallFacts`' reason: nothing persists it.
    What *is* persisted is the journal entry order W4 writes for the call, which records that
    the call was refused.
    """

    call: NodeCall
    reason: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.reason not in REFUSAL_CLASSES:
            raise ValueError(
                f"a refusal carries one of {list(REFUSAL_CLASSES)}; got {self.reason!r}"
            )


@dataclass(frozen=True, slots=True)
class CallRecord:
    """One call, as the tick saw it: what was sent, what came back, and what it decoded to.

    **Journalling it is order W4's and counting its spend is W5's.** The desk keeps the records
    in the order the calls were made so that both orders have one place to read them from,
    rather than each re-deriving the tick's calls from somewhere else.
    """

    call: NodeCall
    envelope: SeatEnvelope | None = None
    result: SeatResultModel | None = None
    refusal: CallRefusal | None = None
    #: **Always `None`** for think, escalate and delegate: the three mint no cortex prediction
    #: (folded: S-A9). The field exists so the fact is readable off the record rather than
    #: asserted about the absence of one.
    ref: str | None = None

    @property
    def refused(self) -> bool:
        return self.refusal is not None


CallAnswer = SeatResultModel | CallRefusal


# --------------------------------------------------------------------------------------
# The desk: one port, a per-node counter, and the three constructors
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class NodeCallDesk:
    """One tick's desk: the one port, the tick's plan, and `call#` per node.

    Opened once per tick through the layer's fourth optional seam and handed the layer's port.
    It holds no state that outlives a tick — the counter is per node within **this** tick,
    which is what the journal key `(task, tick, node, call#)` means.

    **It is the layer's and not the runtime's**, for `SeatUnavailable`'s own reason: a
    `runtime/cycle.py` that imported `protean.cortex` to build a desk would invert the seam the
    whole build is built on. The runtime opens it through `seat.tick_calls_of()` and calls
    `run()` at each outer node's step, learning nothing about what a payload means.
    """

    port: SeatPort
    task: str
    tick: int
    #: The **static** plan, keyed by node name: the scripted layer's, which a fixture supplies. The
    #: live plan is not here — the runtime's call policy hands it per tick through `run()`
    #: (`the build specification (not in this mirror)` § Deliverable 1) — and a node this plan names issues
    #: this plan whatever it is handed, so nothing here decides that a node calls.
    plan: Mapping[str, tuple[PlannedCall, ...]] = field(default_factory=dict)
    #: **The tick's one spawn desk, or nothing** (A.1.i § Deliverable 4, seam contract I5). It is
    #: the desk `SeatLayer.spawns` resolved for *this* tick — the desk itself and not the seam,
    #: because a tick's desk exists by the time this desk is constructed — and it is what the
    #: `delegate` arm opens one spawn per call on. `None` is a layer without the fifth seam: the
    #: arm falls back to the one port, which is every landed tick and every scripted layer.
    #:
    #: It is **`spawn_desk` and not `spawns`**, because `spawns()` below is the landed journal-half
    #: record writer this build does not touch, and a field of that name would shadow the method.
    spawn_desk: TickSpawns | None = None
    counters: dict[str, int] = field(default_factory=dict)
    records: list[CallRecord] = field(default_factory=list)
    #: The call types the gate's veto inhibited for the rest of this tick (§ DoD row G2). A
    #: `no_go` inhibits the dispatch wave and **every delegate for the pending unit**, while
    #: think and escalate stay allowed; an inhibited call is not issued at all, so it makes no
    #: call, journals no entry and refuses nothing — there was no fault.
    inhibited: set[CallType] = field(default_factory=set)
    #: **The per-tick delegate bound, published** (`the build specification (not in this mirror)`
    #: § Deliverable 1): `cycle.py` reads it through this accessor and hands it to the call policy,
    #: which applies it when the plan is made — the desk counts nothing. `None` publishes no bound,
    #: which is the scripted layer's case, and plans unbounded.
    delegate_bound: int | None = None

    def planned(self, node: NodeName) -> tuple[PlannedCall, ...]:
        """This node's planned calls for this tick, in the order the plan wrote them."""
        return tuple(self.plan.get(str(node), ()))

    def inhibit(self, call_type: CallType) -> None:
        """Stop issuing this call type for the rest of the tick — the gate's veto, in effect.

        The runtime calls it through the accessor rather than by importing this module, exactly
        as it reads `calls_for()`, so a desk without it is simply a desk nothing inhibited.
        """
        self.inhibited.add(CallType(call_type))

    def run(
        self, node: NodeName, handed: Sequence[PlannedCall] = ()
    ) -> tuple[CallAnswer, ...]:
        """`protean.runtime.seat.TickCalls` — issue this node's calls this tick, in `call#` order.

        **Which calls** (`the build specification (not in this mirror)` § Scaffold clause item 2(a)): for a
        node the static `plan` names, that plan, whatever was handed — a fixture's plan outranks
        the runtime's call policy, so every landed call test keeps the tick it had; for any other
        node, exactly the plan the runtime `handed`, which is empty unless a trigger is on.
        **Before anything is issued**, a handed `PlannedCall` whose type is outside
        `NODE_CALL_TYPES` is refused by name, exactly as `parse_plan` refuses a fixture's (F18): a
        `dispatch` is the manager's own wave, never an outer node's call, on either path.

        The answer is handed back to the step that asked. **Folding it into the node's own
        output is not built here**: no node output model carries a call answer, and widening one
        is not an amendment § Scaffold clause item 2 enumerates. What A.1 owes is the call, its
        key and its refusal path; the node's step is where the answer arrives.

        **An inhibited type is skipped rather than refused**: the gate vetoed the unit, so the
        call is never made and never numbered — a refusal would say a call happened and failed.
        """
        for planned in handed:
            if planned.type not in NODE_CALL_TYPES:
                raise CallConfigurationError(
                    f"an outer node's call is one of {[str(item) for item in NODE_CALL_TYPES]}; "
                    f"{node} was handed {planned.type} — a dispatch is the manager's own wave "
                    f"(order W8)"
                )
        issued = self.planned(node) if str(node) in self.plan else tuple(handed)
        return tuple(
            self.issue(node, planned)
            for planned in issued
            if planned.type not in self.inhibited
        )

    # ---- the three constructors, each a caller of the one port ----

    def think(self, node: NodeName, question: str, context: str = "") -> CallAnswer:
        """`think` — the node's own question, answered as a signal it folds into its output."""
        return self.call(node, CallType.THINK, ThinkPayload(question=question, context=context))

    def escalate(
        self, node: NodeName, concern: str, unit_id: str | None = None, proposal: str = ""
    ) -> CallAnswer:
        """`escalate` — the node talks to the manager, which may dispatch; the node may not."""
        return self.call(
            node,
            CallType.ESCALATE,
            EscalatePayload(concern=concern, unit_id=unit_id, proposal=proposal),
        )

    def delegate(
        self, node: NodeName, kind: str, question: str, context: str = ""
    ) -> CallAnswer:
        """`delegate` — the node asks a specialized subagent for information or a verdict.

        **From A.1.i this arm reaches a kind block rather than no block at all**
        (`the build specification (not in this mirror)` § Deliverable 4): where the fifth seam is
        attached, `_send()` below resolves `(delegate, payload.kind)` through `SeatsConfig.kind()`
        and opens **one spawn per call** on the tick's one `SpawnDesk`, with **no `member#`**,
        because a delegate is not a wave member. The calling node is the `NodeCall`'s own `node`.

        **On a live root it is reachable once a rule plans a delegate** (A.2.i § Deliverable 1):
        `build_live_layer()` attaches `node_calls` over the same `SpawnDesks` as `spawns`, and the
        runtime's call policy plans delegates **bounded per tick** by the bound this desk
        publishes. The shipping seed defines one `delegate` kind since A.2; with every trigger off,
        no rule plans one.
        """
        return self.call(
            node, CallType.DELEGATE, DelegatePayload(kind=kind, question=question, context=context)
        )

    def issue(self, node: NodeName, planned: PlannedCall) -> CallAnswer:
        """One `PlannedCall` from the layer's seam, built into a `NodeCall` and sent.

        The seam hands the runtime *what* to ask; the three constructors above are the same
        thing with the payload typed at the call site. Both land on `call()`.
        """
        model = payload_model(planned.type)
        return self.call(node, planned.type, model.model_validate(dict(planned.payload)))

    # ---- the one path all three take ----

    def next_call_number(self, node: NodeName) -> int:
        """The node's next `call#` in this tick, from 1 — `call# = 0` is the output entry's."""
        key = str(node)
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def build_call(
        self, node: NodeName, call_type: CallType, payload: ProteanModel
    ) -> NodeCall:
        """The C1 `NodeCall` one call is, addressed to its own type.

        The payload travels as the model dumped to JSON with the model it came from named beside
        it (folded: D3-2), because a contract under `protean.state` may not import the request
        models — and a mapping whose sender names its type stays reconstructable without one.
        """
        resolved = CallType(call_type)
        return NodeCall(
            type=resolved,
            node=NodeName(node),
            tick=self.tick,
            call_number=self.next_call_number(node),
            payload=payload.model_dump(mode="json"),
            payload_model=type(payload).__name__,
            addressee=resolved,
        )

    def call(self, node: NodeName, call_type: CallType, payload: ProteanModel) -> CallAnswer:
        """Build the call, send it through the one port, decode it on the one path.

        Every fault becomes a `CallRefusal` **returned** rather than raised: an advisory call
        never ends the task, and it never reaches `SeatUnavailable` past this frame.
        """
        node_call = self.build_call(node, call_type, payload)
        try:
            envelope = self._send(node_call)
        except Exception as fault:  # noqa: BLE001 — every fault on these three is a signal
            return self._refuse(node_call, fault)
        try:
            decoded = decode_seat_result(node_call.addressee, envelope, self.tick)
        except (SeatDecodeError, IllegalReturn) as fault:
            # An illegal return is one of § Deliverable 2's four faults on a think, escalate or
            # delegate — a **signal** to the calling node, never a stop. The table refused it
            # before the decoder and earned it no retry, which is the only thing that
            # distinguishes it from a shape that did not validate.
            return self._refuse(node_call, fault, envelope=envelope)
        self.records.append(CallRecord(call=node_call, envelope=envelope, result=decoded))
        return decoded

    def _send(self, node_call: NodeCall) -> SeatEnvelope:
        """One call out: through the tick's spawn desk for a delegate, else through the port.

        **The delegate arm is the fifth seam's second opener** (A.1.i § Deliverable 4): a
        `delegate` is a tier-three call with a kind process behind it, so where the seam is
        attached it goes to the desk — which resolves the kind, composes the profile, builds the
        argv and spawns — and where it is not, it goes to the one port exactly as A.1 left it.
        Think and escalate are `calls:` blocks and never reach the desk at all.

        Every fault this raises is classified by the caller: the desk's own refusals arrive as
        A.1's four classes and never as a stop, because `call()` above catches everything.
        """
        if node_call.addressee is CallType.DELEGATE and self.spawn_desk is not None:
            return self.spawn_desk.delegate(node_call)
        return self.port(node_call.addressee, node_call)

    def refuse(
        self, call: NodeCall, reason: str, detail: str = "", envelope: SeatEnvelope | None = None
    ) -> CallRefusal:
        """Record a refusal under one of the four classes and hand it to the calling node.

        Public because the cap class is produced where the cap is enforced (order W3, row G10):
        the class set is the deliverable's, not this module's ability to trigger it.
        """
        refusal = CallRefusal(call=call, reason=reason, detail=detail)
        self.records.append(CallRecord(call=call, envelope=envelope, refusal=refusal))
        return refusal

    def _refuse(
        self, call: NodeCall, fault: Exception, envelope: SeatEnvelope | None = None
    ) -> CallRefusal:
        return self.refuse(call, classify(fault), detail=str(fault), envelope=envelope)

    # ---- what the tick reads back ----

    def calls_for(self, node: NodeName) -> tuple[CallRecord, ...]:
        """Every record this node made this tick, in `call#` order."""
        return tuple(item for item in self.records if item.call.node == NodeName(node))

    def answers(self) -> tuple[CallRecord, ...]:
        """Every record of the tick, in the order the calls were made."""
        return tuple(self.records)

    def spawns(self) -> tuple[Any, ...]:
        """The C2 `SubagentSpawn` record of every **tier-three** call this desk made.

        Row M3's spawn half: a desk that issued no delegate answers an empty tuple, so a layer
        without the delegate seam writes no `SubagentSpawn` — exactly as a layer without `calls`
        writes no `SeatCallRecord`. The composition is `protean.cortex.subagents`', which is
        where the tier-three seam lives (§ Deliverable 4).
        """
        return spawns_in(self.records, task=self.task)


@dataclass(frozen=True, slots=True)
class CallDesks:
    """`protean.runtime.seat.NodeCalls` — the factory the layer carries, one desk per tick.

    A factory rather than a desk because `call#` is per node **within a tick**: a desk that
    outlived one would number the second tick's first call 2.

    **It holds the `spawns` seam and not a spawn desk** (A.1.i § Deliverable 4, folded: S-i36):
    this object is constructed at layer time, before any tick exists, so a desk is the one thing
    it cannot be given. `NodeCallDesk` below is constructed **per tick** with the desk that seam
    resolves for that tick, beside the port — which is how the delegate arm reaches one at all.
    Resolving the desk constructs it and refuses nothing, and the seam memoizes per
    `(task, tick)`, so this resolution and `run_wave`'s reach the same object.
    """

    port: SeatPort
    plan: Mapping[str, tuple[PlannedCall, ...]] = field(default_factory=dict)
    #: `SeatLayer.spawns`, the fifth optional seam — **the seam, not a desk**. `None` is a layer
    #: that spawns nothing, which is every scripted layer and every landed tick.
    spawns: Spawns | None = None
    #: The per-tick delegate bound each tick's desk publishes — the live layer's is read off the
    #: seed. `None` publishes none, which is every scripted layer.
    delegate_bound: int | None = None
    opened: list[NodeCallDesk] = field(default_factory=list)

    def __call__(self, task: str, tick: int) -> NodeCallDesk:
        desk = NodeCallDesk(
            port=self.port,
            task=task,
            tick=tick,
            plan=dict(self.plan),
            spawn_desk=None if self.spawns is None else self.spawns(task, tick),
            delegate_bound=self.delegate_bound,
        )
        self.opened.append(desk)
        return desk


def classify(fault: Exception) -> str:
    """Which of § Deliverable 2's four classes a fault refuses under.

    `SeatUnavailable` is a **call failure** here and not a stop: the classes that end the task
    are a fault on a seat call and a fault on a `dispatch` member, and neither is one of these
    three (order W8). A cap exceeded arrives through `refuse()` from the site that enforced it —
    **and is named here too** (§ Resolutions D11-3), because an *uncaught* `CallCapExceeded`
    reaching a desk's blanket `except` would otherwise be recorded as a `call_failed`, which is
    the one class it is not: the call did not fail, it was stopped at its own cap.

    The import is function-local on `protean.cortex.habits`'s own precedent (its `load_seats`
    import, `habits.py:198`): `cortex.live.config` imports **this** module for
    `REFUSAL_CAP_EXCEEDED`, so the dependency runs one way at import time and the other way at
    call time.
    """
    from protean.cortex.live.config import CallCapExceeded

    if isinstance(fault, CallCapExceeded):
        return REFUSAL_CAP_EXCEEDED
    if isinstance(fault, (SeatDecodeError, IllegalReturn)):
        return REFUSAL_ILLEGAL_RETURN
    if isinstance(fault, (CallConfigurationError, LookupError)):
        return REFUSAL_NO_CONFIGURATION
    if isinstance(fault, SeatUnavailable):
        return REFUSAL_CALL_FAILED
    return REFUSAL_CALL_FAILED


def parse_plan(entries: Sequence[Mapping[str, Any]] | None) -> dict[str, tuple[PlannedCall, ...]]:
    """`[{node, type, payload}, ...]` → the per-node plan a desk is opened with.

    The parser a fixture's call plan is read through. It validates each payload against its call
    type's own model, so a plan naming a field no payload carries is refused at load rather than
    at the port — the same rule `SeatScript` holds a response to.
    """
    plan: dict[str, list[PlannedCall]] = {}
    for entry in entries or ():
        node = str(NodeName(str(entry["node"])))
        call_type = CallType(str(entry["type"]))
        if call_type not in NODE_CALL_TYPES:
            raise CallConfigurationError(
                f"an outer node's call is one of {[str(item) for item in NODE_CALL_TYPES]}; "
                f"got {call_type} — a dispatch is the manager's own wave (order W8)"
            )
        model = payload_model(call_type)
        payload = model.model_validate(dict(entry.get("payload") or {}))
        plan.setdefault(node, []).append(
            PlannedCall(
                type=call_type,
                payload=payload.model_dump(mode="json"),
                payload_model=model.__name__,
            )
        )
    return {node: tuple(items) for node, items in plan.items()}
