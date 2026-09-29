"""Node -> its call check, and the runtime's one plan of the calls a node makes this tick.

`the build specification (not in this mirror)` § Deliverable 1, the T3 surface: "a pure check per node, and
one policy beside `firing.py`". Build A.1 built three call seams and left unmade what decides that
an outer node calls (its D5-3); this module is that decision. **It decides *that* a call happens
and never makes one**: it spawns nothing, opens no file and names no binary and no kind. A plan is
a tuple of `PlannedCall`s the runtime hands the node-call desk, which issues it through the one
port — and a desk's static fixture plan still outranks it for a node that plan names (§ Scaffold
clause item 2(a)).

**The split is `firing.py`'s own.** Each authored node's call check lives in its node module,
beside its `firing_check` — projected input in, the tuple of `CallType`s it plans out — because a
check is a pure callable over a node's own projection and weights. What lives *here* is the
policy over those answers: which nodes have a rule, which weights key each rule reads, which call
types each can plan, where a call's question comes from, and how its context is cut.

**Two rules are authored, and both ship off.** Homeostasis thinks on its ceiling pressure and the
anterior cingulate on the predicates it grades against a claim. The hippocampus's and the gate's
rules are deferred by ruling (E5, E4) and the thalamus makes no call, so the map names two nodes.
A trigger key at `null`, or absent, plans nothing — the shipping seed — and `check_seeds()`
refuses any other value that is not a positive number, before the task's first tick.

**The question is authored, never generated.** A planned call's `question` (an escalate's
`concern`) is its line in the node's own `NODE.md` `## Calls`, verbatim: the second parsed section
of a `NODE.md` (§ Scaffold clause item 2(d)), read here and nowhere else. Its `context` is the
node's projected input on `predictions.input_signature()`'s own serialization, cut at
`CONTEXT_BOUND`. The payload travels as a mapping with its model *named*, because the runtime may
not import the payload models; the desk validates it on its landed `issue()` path.

**One planned set per node per tick, decided before issue** (decision 3): at most one call of each
type, read off the projection, the node's own weights and `NODE.md`, and the tick's running
delegate count — no clock and no answer from an earlier call — so a torn tick re-derives the same
plan. A delegate is planned only while that count is under the bound the tick's desk publishes;
past it the delegate is simply **not planned**.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from pydantic import BaseModel

from protean import config
from protean.brain.folders import NodeFolder
from protean.nodes import anterior_cingulate, homeostasis
from protean.runtime.seat import PlannedCall
from protean.state.enums import CallType, NodeName
from protean.state.errors import CallsDrift

#: Node name -> its call check. Keyed by the **authored** nodes only, and asserted below to be a
#: subset of `config.DETERMINISTIC_NODES`, on `firing.py`'s own import-time precedent. A test may
#: replace the whole map: `plan()` reads it at call time, never through a captured reference.
CALL_CHECKS: Final[Mapping[str, Callable[[Any], tuple[CallType, ...]]]] = MappingProxyType(
    {
        "homeostasis": homeostasis.call_check,
        "anterior_cingulate": anterior_cingulate.call_check,
    }
)

#: Node name -> the `weights.yaml` key its rule reads. Built from the constants the node modules
#: declare, exactly as `firing.FIRING_KEYS` is, so a key is spelled in one place.
TRIGGER_KEYS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "homeostasis": homeostasis.WEIGHT_THINK_TRIGGER,
        "anterior_cingulate": anterior_cingulate.WEIGHT_THINK_TRIGGER,
    }
)

#: Node name -> the call types its rule can plan — the `## Calls` lines an **on** key requires.
#: One `think` each in this cut: no authored rule plans an escalate or a delegate.
RULE_CALL_TYPES: Final[Mapping[str, tuple[CallType, ...]]] = MappingProxyType(
    {
        "homeostasis": (CallType.THINK,),
        "anterior_cingulate": (CallType.THINK,),
    }
)

#: The three call types an outer node may plan, each with the **name** of the payload model it
#: carries. Named rather than imported: the payload models live in `protean.cortex`, which
#: `runtime/` may not import. A type outside this table is handed to the desk bare, and the
#: desk refuses it by name (F18) — the one guard, not two.
PAYLOAD_MODEL_NAMES: Final[Mapping[CallType, str]] = MappingProxyType(
    {
        CallType.THINK: "ThinkPayload",
        CallType.ESCALATE: "EscalatePayload",
        CallType.DELEGATE: "DelegatePayload",
    }
)

#: How much of a node's serialized projection a planned call carries as its `context`, in
#: characters. A builder's default: what bounds a think's spend is the `calls.think` block's own
#: per-call cap, and this bound keeps the payload a size that cap was set against.
CONTEXT_BOUND: Final[int] = 8000

#: The heading a node's questions sit under, and the pattern one line matches: a bullet, the
#: call type, a delegate's kind, a colon, then the question verbatim.
CALLS_HEADING: Final[str] = "## Calls"
_HEADING = re.compile(r"^##\s+\S")
_LINE = re.compile(
    r"^\s*[-*]\s+(?P<type>"
    + "|".join(re.escape(str(call_type)) for call_type in PAYLOAD_MODEL_NAMES)
    + r")(?:\s+(?P<kind>[A-Za-z0-9_.-]+))?:\s+(?P<text>\S.*?)\s*$"
)

_outside = tuple(name for name in CALL_CHECKS if name not in config.DETERMINISTIC_NODES)
if _outside:  # pragma: no cover - a module-level contract assertion, not a branch
    raise ImportError(
        f"protean.runtime.triggers holds a call check for {list(_outside)}, which "
        f"config.DETERMINISTIC_NODES does not name -- a node that is not on the path cannot call"
    )
_unkeyed = tuple(
    name for name in CALL_CHECKS if name not in TRIGGER_KEYS or name not in RULE_CALL_TYPES
)
if _unkeyed:  # pragma: no cover - a module-level contract assertion, not a branch
    raise ImportError(
        f"{list(_unkeyed)} carry a call check with no trigger key or no call types -- a rule "
        f"that cannot be switched off, or cannot be checked for its questions, is not a rule"
    )
del _outside, _unkeyed


@dataclass(frozen=True, slots=True)
class CallLine:
    """One `## Calls` line: its call type, the kind a delegate line names, and the question."""

    type: CallType
    text: str
    kind: str | None = None


def parse_calls(node_md: str) -> dict[CallType, CallLine]:
    """The lines a `NODE.md`'s `## Calls` section holds, one per call type — the first one wins.

    The section ends at the next `## ` heading. Prose inside it is not a line, and a line naming a
    type outside the three is not one either: `protean.state.reads` parses `## Reads` the same way.
    """
    lines: dict[CallType, CallLine] = {}
    inside = False
    for raw in node_md.splitlines():
        if raw.strip() == CALLS_HEADING:
            inside = True
            continue
        if inside and _HEADING.match(raw):
            break
        if not inside:
            continue
        match = _LINE.match(raw)
        if match is None:
            continue
        call_type = CallType(match.group("type"))
        lines.setdefault(
            call_type, CallLine(type=call_type, text=match.group("text"), kind=match.group("kind"))
        )
    return lines


def _has_line(lines: Mapping[CallType, CallLine], call_type: CallType) -> bool:
    """Whether a planned call of this type has its question — and, for a delegate, its kind."""
    line = lines.get(call_type)
    if line is None:
        return False
    return call_type is not CallType.DELEGATE or bool(line.kind)


def context_of(payload: BaseModel) -> str:
    """The node's projected input as `input_signature()` serializes it, cut at `CONTEXT_BOUND`."""
    body = json.dumps(
        payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return body[:CONTEXT_BOUND]


def _payload(line: CallLine, context: str) -> dict[str, Any]:
    """One call's payload mapping, in the field names of the model `PAYLOAD_MODEL_NAMES` names."""
    if line.type is CallType.ESCALATE:
        return {"concern": line.text}
    if line.type is CallType.DELEGATE:
        return {"kind": line.kind, "question": line.text, "context": context}
    return {"question": line.text, "context": context}


def plan(
    node: NodeName | str,
    payload: BaseModel,
    node_md: str,
    bound: int | None,
    delegates: int,
) -> tuple[PlannedCall, ...]:
    """This node's calls for this tick: the runtime's one call site, asked at a fired node's step.

    `payload` is the node's projected input, `node_md` its own `NODE.md`, `bound` the delegate
    bound the tick's desk publishes (`None` is unbounded) and `delegates` the tick's running count
    of planned delegates. A node with no rule plans nothing. Each type the check answers is planned
    once, in the order it answered; a delegate is dropped once `delegates` has reached `bound`.

    A type the check answers with no `## Calls` line to carry its question is refused by name.
    `check_seeds()` has already refused that for every authored rule whose key is on, so the arm
    is reached only by a check map a test put in place.
    """
    name = str(NodeName(node))
    check = CALL_CHECKS.get(name)
    if check is None:
        return ()
    wanted: list[CallType] = []
    for answered in check(payload):
        call_type = CallType(answered)
        if call_type not in wanted:
            wanted.append(call_type)
    if not wanted:
        return ()

    lines = parse_calls(node_md)
    context = context_of(payload)
    planned: list[PlannedCall] = []
    for call_type in wanted:
        if call_type is CallType.DELEGATE and bound is not None and delegates >= bound:
            continue
        if call_type not in PAYLOAD_MODEL_NAMES:
            planned.append(PlannedCall(type=call_type))
            continue
        if not _has_line(lines, call_type):
            raise CallsDrift(name, missing=(str(call_type),))
        planned.append(
            PlannedCall(
                type=call_type,
                payload=_payload(lines[call_type], context),
                payload_model=PAYLOAD_MODEL_NAMES[call_type],
            )
        )
    return tuple(planned)


def trigger_is_on(value: Any) -> bool:
    """Whether a trigger key's value is on: a positive `int` or `float`, and never a `bool`."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def check_seeds(folders: Mapping[NodeName, NodeFolder]) -> None:
    """Refuse, before any tick, a trigger key the policy cannot plan from — `build_context()`.

    Off is exactly `null` or the key absent, and requires nothing. An on-value is a positive
    `int` or `float`; anything else — zero, a negative, a bool (YAML 1.1 reads `off` and `on` as
    booleans), a string, a list — raises `CallsDrift` naming the key and its value. An on key
    whose `## Calls` lacks the line for a type its rule can plan raises `CallsDrift` naming the
    missing type. The code both map to is `config.EXIT_SEED_DRIFT`, beside `ReadsDrift`.
    """
    for node, key in TRIGGER_KEYS.items():
        folder = folders.get(NodeName(node))
        if folder is None:
            continue
        value = folder.weights.get(key)
        if value is None:
            continue
        if not trigger_is_on(value):
            raise CallsDrift(node, key=key, value=value)
        lines = parse_calls(folder.node_md)
        missing = tuple(
            str(call_type)
            for call_type in RULE_CALL_TYPES[node]
            if not _has_line(lines, call_type)
        )
        if missing:
            raise CallsDrift(node, missing=missing)
