"""`SeatScript` — the request-keyed responder build 1's three seats answer from.

`the build specification (not in this mirror)` § Deliverable 6 → *Seat scripts are request-keyed responders,
never turn lists* (folded: A1-10): "a `SeatScript` fixture is `tier → ordered queue of
responses`, each optionally conditioned on fields of the incoming request (the unit id, the
escalation that fired, the trap in the evidence); the runtime takes the first response whose
condition matches. A tick-indexed turn list would hardcode the very tick counts the thresholds
decide."

**Nothing here is keyed by call order and nothing here counts.** A response is chosen by
matching the incoming request; the same request always draws the same response, which is also
what makes a replayed tick and a live tick agree about what the seat said. The queue is
*ordered* so that the most specific condition can be written first; it is not consumed.

**A condition names only what the tick handed the seat.** Three keys are the ones
§ Deliverable 6 lists — the unit id, the escalation that fired, the trap in the evidence — and
one more, `resolved`, reads `Workspace.resolved_interrupts`, which is how "the answer lands in
committed state before the next tick runs" becomes something a script can respond to. Build 3
adds a fifth, `goal_digest`, the one key a *compiled* habit may be keyed on
(`the build specification (not in this mirror)` § Deliverable 4, folded: S-3). An empty condition matches
every request for its tier, and every key stays optional, so a script written before the fifth
key existed loads unchanged.

**The escalation reaches a director response through the router's selection.**
`ManagerRequest` carries `escalation` and `trap_evidence` as fields, because a manager call with
no rung is a router bug the model refuses to express; `DirectorRequest` carries only the
compressed workspace, by decision 25's per-tier asymmetry. So the reason the router named a tier
is read off the request when the request has it and off the `SeatSelection` otherwise — the same
fact either way, since the runtime builds the request from that selection.

**A dispatch member is answered by a scripted return with no process behind it**
(`the build specification (not in this mirror)` § Deliverable 4). The request is the `WaveMember` the
manager's plan listed, so a response for `tier: dispatch` is matched on the member's own
fields — its **kind**, which is the one thing that tells two members of one wave apart, and the
unit the wave is about. **No kind process exists**: the return is a scripted `ExecutorSummary`
and nothing is spawned, which is what row G12 asserts of every A.1 fixture.

**From A.1 a script answers an addressee rather than a tier** (`the build specification (not in this mirror)` § Deliverable 2). The port's first argument is a `Tier` for a seat call and a **call
type** for everything else, so a response's `tier:` key carries either — the key keeps its name
because every landed fixture writes it and because a response still names *who it answers for*,
which is now one of six addressees rather than one of three tiers. A script may also carry an
optional top-level **`calls:`** plan — `node`, `type` and `payload` per entry — which is how a
*fixture* drives the three call types without this module deciding that a node calls: the
runtime's call policy decides that (`the build specification (not in this mirror)` § Deliverable 1), and
**a fixture's `calls:` plan outranks the policy for the node it names**, so every scripted call
test keeps the tick its fixture wrote.

**A script never writes a tick number and never writes a threshold.** `tick` is stamped onto
the result by this module from the request itself, so no fixture contains one; a threshold is
never restated because the *escalation* the router computed already carries the fact that a
threshold fired. Two placeholders — `$goal` and `$unit` — stand in for the ids the runtime
mints at task start, which a hand-authored file cannot know.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from protean.cortex.calls import parse_plan
from protean.cortex.subagents import member_facts
from protean.runtime.seat import PlannedCall, SeatSelection, addressee_of
from protean.state.calls import NodeCall
from protean.state.enums import Addressee, Escalation, TrapDetector
from protean.state.seats import WaveMember
from protean.state.workspace import DirectorRequest, ManagerRequest

#: The placeholder a script writes where the runtime-minted goal id belongs.
GOAL_PLACEHOLDER = "$goal"

#: The placeholder a script writes where the manager-minted work-unit id belongs.
UNIT_PLACEHOLDER = "$unit"

#: The result field the responder stamps from the request rather than from the file.
STAMPED_FIELD = "tick"

#: What the responder stamps for a request that carries no tick of its own — a wave member,
#: whose model is the manager's output and not a per-tick request. The runtime's decode
#: overwrites it with the real tick on every path (`decode_seat_result()`), so the value is a
#: placeholder rather than a fact, and a fixture still never writes a tick number.
UNSTAMPED_TICK = 0

#: The five condition keys a response may carry. Every one of them reads a field of the
#: incoming request; there is deliberately no key that reads a counter or a call index.
#:
#: `goal_digest` is build 3's one addition (`the build specification (not in this mirror)` § Deliverable 4,
#: folded: S-3) — `sha256[:16]` of the text of the goal the tier is serving. It is the key a
#: *compiled* habit binds, because `unit_id` is minted per task and never recurs across tasks;
#: it is **optional** in a condition like the other four, so every hand-authored script and the
#: whole dry battery keep loading unchanged.
CONDITION_KEYS: tuple[str, ...] = (
    "unit_id",
    "escalation",
    "trap",
    "resolved",
    "goal_digest",
    "kind",
)

#: How many hex characters of the goal's sha256 a `goal_digest` carries. Short because it is a
#: key in a hand-readable YAML condition, not a collision-proof identifier.
GOAL_DIGEST_LENGTH: int = 16


def goal_digest_of(text: str) -> str:
    """`sha256[:16]` of a goal's text — the ONE implementation both sides of a habit call.

    `facts_of()` calls it on the request's workspace goal stack; `protean.sleep.habits` calls it
    on the run's committed goal stack when it compiles. A second copy of this arithmetic would be
    a habit that never matches for a reason no test could see.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:GOAL_DIGEST_LENGTH]


class SeatScriptError(ValueError):
    """A script file that is not a `SeatScript`. Refused at load, never at the seat."""


@dataclass(frozen=True, slots=True)
class RequestFacts:
    """The fields of one incoming request a condition may be written against.

    `tier` is the **addressee** from A.1 on — a `Tier` for a seat call, a `CallType` otherwise.
    The name is kept because it is what every response and every landed fixture writes.
    """

    tier: Addressee
    tick: int
    unit_id: str | None = None
    escalation: Escalation | None = None
    traps: frozenset[str] = frozenset()
    resolved_kinds: frozenset[str] = frozenset()
    goal_id: str | None = None
    #: `sha256[:16]` of the served goal's **text**, never of the request and never of its id —
    #: `None` for a request that carries no workspace goal stack.
    goal_digest: str | None = None
    #: The subagent **kind** a dispatch member asked for — build A.1's one added key, and the
    #: only thing that tells two members of one wave apart: `unit_id` is identical across every
    #: member by the merge rule (§ Deliverable 3), so a condition keyed on it alone could not
    #: give a two-member wave two different returns. `None` for every request that is not a
    #: wave member, so every landed script and every landed condition loads unchanged.
    kind: str | None = None


def facts_of(
    tier: Addressee, request: object, selection: SeatSelection | None = None
) -> RequestFacts:
    """The request's own fields, with the router's reason filled in where the model has no slot."""
    escalation = None if selection is None else selection.escalation
    if isinstance(request, WaveMember):
        # **A dispatch member's request is the `WaveMember` itself** (§ Deliverable 3's model
        # table): the kind, the unit id and the admitted-context reference, and no path — the
        # workspace a member sees is the runtime's to fill. It carries no tick, and it needs
        # none: `decode_seat_result()` stamps the runtime's tick over whatever the responder
        # wrote, so the stamp below is a placeholder the decoder always replaces.
        facts = member_facts(request)
        return RequestFacts(
            tier=addressee_of(tier),
            tick=UNSTAMPED_TICK,
            unit_id=facts.unit_id,
            kind=facts.kind,
        )
    if isinstance(request, NodeCall):
        # A think, escalate or delegate: the C1 record **is** the request (§ Scaffold clause
        # item 3), so the only facts it carries are its own. It names no unit and serves no
        # goal — it is the calling node's question, not the tick's work — so a response for a
        # call type is matched on its addressee alone, which is what an empty condition does.
        return RequestFacts(tier=addressee_of(tier), tick=request.tick)
    selected_traps = frozenset(
        str(scalar.detector)
        for scalar in (() if selection is None else selection.trap_evidence)
        if scalar.fired
    )
    if isinstance(request, ManagerRequest):
        served = _served_goal(request.workspace)
        return RequestFacts(
            tier=tier,
            tick=request.workspace.tick,
            unit_id=request.unit_id,
            escalation=request.escalation,
            traps=frozenset(
                str(scalar.detector) for scalar in request.trap_evidence if scalar.fired
            ),
            resolved_kinds=frozenset(
                str(item.kind) for item in request.workspace.resolved_interrupts
            ),
            goal_id=None if served is None else served.id,
            goal_digest=None if served is None else goal_digest_of(served.text),
        )
    if isinstance(request, DirectorRequest):
        served = _served_goal(request.workspace)
        return RequestFacts(
            tier=tier,
            tick=request.workspace.tick,
            escalation=escalation,
            traps=selected_traps,
            resolved_kinds=frozenset(
                str(item.kind) for item in request.workspace.resolved_interrupts
            ),
            goal_id=None if served is None else served.id,
            goal_digest=None if served is None else goal_digest_of(served.text),
        )
    # There is no further branch: the executor seat is gone, and the three request shapes above
    # — a seat request, a `NodeCall` and a `WaveMember` — are every shape the one port takes
    # (`the build specification (not in this mirror)` § Deliverable 3).
    raise SeatScriptError(f"unrecognised seat request {type(request).__name__}")


def _served_goal(workspace):
    """The goal the tier is serving: the first `open` one on the stack, or `None`.

    One selection for both facts — `goal_id` fills `$goal`, `goal_digest` keys a habit — so the
    id a placeholder resolves to and the text a condition matches on always name one goal.
    """
    for goal in workspace.goals:
        if str(goal.status) == "open":
            return goal
    return None


@dataclass(frozen=True, slots=True)
class ResponseCondition:
    """What must be true of the request for a response to be taken. Empty matches everything."""

    unit_id: str | None = None
    escalation: Escalation | None = None
    trap: TrapDetector | None = None
    resolved: str | None = None
    #: The one key a compiled habit binds (folded: S-3). Optional here like every other key,
    #: so an empty condition still matches every request for its tier.
    goal_digest: str | None = None
    #: The subagent kind a dispatch member asked for (build A.1). Optional like the rest.
    kind: str | None = None

    def matches(self, facts: RequestFacts) -> bool:
        if self.unit_id is not None and facts.unit_id != self.unit_id:
            return False
        if self.escalation is not None and facts.escalation is not self.escalation:
            return False
        if self.trap is not None and str(self.trap) not in facts.traps:
            return False
        if self.resolved is not None and self.resolved not in facts.resolved_kinds:
            return False
        if self.goal_digest is not None and facts.goal_digest != self.goal_digest:
            return False
        if self.kind is not None and facts.kind != self.kind:
            return False
        return True

    @classmethod
    def parse(cls, payload: Mapping[str, Any] | None) -> "ResponseCondition":
        source = dict(payload or {})
        unknown = sorted(set(source) - set(CONDITION_KEYS))
        if unknown:
            raise SeatScriptError(
                f"a response condition reads request fields {list(CONDITION_KEYS)}; "
                f"got {unknown} — a condition that is not a request field would make the "
                f"responder something other than request-keyed"
            )
        escalation = source.get("escalation")
        trap = source.get("trap")
        return cls(
            unit_id=None if source.get("unit_id") is None else str(source["unit_id"]),
            escalation=None if escalation is None else Escalation(str(escalation)),
            trap=None if trap is None else TrapDetector(str(trap)),
            resolved=None if source.get("resolved") is None else str(source["resolved"]),
            goal_digest=(
                None if source.get("goal_digest") is None else str(source["goal_digest"])
            ),
            kind=None if source.get("kind") is None else str(source["kind"]),
        )


@dataclass(frozen=True, slots=True)
class ScriptedResponse:
    """One **addressee's** answer to the requests its condition matches.

    `tier` holds the addressee — a `Tier` for a seat call, a `CallType` for a think, escalate,
    delegate or dispatch — and keeps its name because it is the key every landed fixture writes.
    """

    tier: Addressee
    when: ResponseCondition
    result: Mapping[str, Any]
    usage: Mapping[str, int] = field(default_factory=dict)

    @classmethod
    def parse(cls, payload: Mapping[str, Any]) -> "ScriptedResponse":
        if "tier" not in payload:
            raise SeatScriptError("every response names the addressee it answers for")
        result = payload.get("result")
        if not isinstance(result, Mapping):
            raise SeatScriptError("a response carries a `result` mapping")
        if STAMPED_FIELD in result:
            raise SeatScriptError(
                f"a response never writes {STAMPED_FIELD!r}: the responder stamps it from the "
                f"request, so no fixture carries a tick number"
            )
        usage = payload.get("usage") or {}
        if not isinstance(usage, Mapping):
            raise SeatScriptError("a response's `usage` is a mapping of counters")
        return cls(
            tier=addressee_of(str(payload["tier"])),
            when=ResponseCondition.parse(payload.get("when")),
            result=dict(result),
            usage={str(key): int(value) for key, value in usage.items()},
        )


def substitute(value: Any, facts: RequestFacts) -> Any:
    """Replace `$goal` and `$unit` with the ids the runtime minted, everywhere they appear.

    A hand-authored plan has to name the goal its units belong to, and the goal id is minted at
    task start — so without these two the fixture would have to hardcode an id no fixture can
    know, or the runtime would have to accept a plan naming no goal.
    """
    if isinstance(value, str):
        if value == GOAL_PLACEHOLDER:
            return facts.goal_id
        if value == UNIT_PLACEHOLDER:
            return facts.unit_id
        return value
    if isinstance(value, Mapping):
        return {key: substitute(item, facts) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [substitute(item, facts) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class SeatScript:
    """`addressee → ordered queue of responses`, matched on the request, never on the call order.

    **Plus the tick's optional call plan** (§ Deliverable 2): `calls` is what a *fixture* uses
    to make an outer node's step reach the cortex, keyed by node. It is empty for every landed
    script, so the whole dry battery keeps the tick it had.
    """

    name: str
    responses: tuple[ScriptedResponse, ...] = ()
    #: `node → the calls that node's step makes this tick`, parsed by `protean.cortex.calls`.
    calls: Mapping[str, tuple[PlannedCall, ...]] = field(default_factory=dict)

    def for_tier(self, tier: Addressee) -> tuple[ScriptedResponse, ...]:
        """The queue of one **addressee**, in the order the file wrote it.

        The name is build 1's and is kept because `protean.cortex.habits` and the dry battery
        read it; what it takes is the port's first argument, tier or call type alike.
        """
        resolved = addressee_of(tier)
        return tuple(item for item in self.responses if item.tier is resolved)

    def match(self, tier: Addressee, facts: RequestFacts) -> ScriptedResponse:
        """The **first** response whose condition matches — § Deliverable 6's own rule."""
        for response in self.for_tier(tier):
            if response.when.matches(facts):
                return response
        raise SeatScriptError(
            f"script {self.name!r} has no {tier} response matching "
            f"unit_id={facts.unit_id!r} escalation={facts.escalation!r} "
            f"traps={sorted(facts.traps)} resolved={sorted(facts.resolved_kinds)} "
            f"goal_digest={facts.goal_digest!r} kind={facts.kind!r}"
        )

    def respond(
        self, tier: Addressee, request: object, selection: SeatSelection | None = None
    ) -> dict[str, Any]:
        """The matched result payload, placeholders filled and `tick` stamped from the request."""
        facts = facts_of(tier, request, selection)
        response = self.match(tier, facts)
        payload = substitute(dict(response.result), facts)
        payload[STAMPED_FIELD] = facts.tick
        return payload

    def usage_for(
        self, tier: Addressee, request: object, selection: SeatSelection | None = None
    ) -> Mapping[str, int]:
        """The matched response's declared counters, for the envelope the adapter builds."""
        return self.match(tier, facts_of(tier, request, selection)).usage


def parse_script(payload: Mapping[str, Any], *, name: str) -> SeatScript:
    """A loaded mapping → a `SeatScript`, refusing anything the format does not name."""
    responses = payload.get("responses")
    if not isinstance(responses, Sequence) or isinstance(responses, (str, bytes)):
        raise SeatScriptError(f"{name}: a seat script carries a `responses` list")
    planned = payload.get("calls")
    if planned is not None and (
        not isinstance(planned, Sequence) or isinstance(planned, (str, bytes))
    ):
        raise SeatScriptError(f"{name}: a `calls:` plan is a list of {{node, type, payload}}")
    try:
        plan = parse_plan(planned)
    except (LookupError, ValueError) as fault:
        raise SeatScriptError(f"{name}: {fault}") from fault
    return SeatScript(
        name=str(payload.get("name", name)),
        responses=tuple(ScriptedResponse.parse(item) for item in responses),
        calls=plan,
    )


def load_script(path: Path | str) -> SeatScript:
    """Read one hand-authored seat script from `fixtures/seat_scripts/`."""
    source = Path(path)
    loaded = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise SeatScriptError(f"{source}: a seat script is a mapping")
    return parse_script(loaded, name=source.stem)
