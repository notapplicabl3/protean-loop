"""A valid payload for any exported contract, derived from the model rather than written out.

`the build specification (not in this mirror)` § Deliverable 7 → *Contract conformance*: "One test per
contract in Deliverable 2's tables: a missing or wrong-typed field fails, and an extra field
fails for every model except `SeatEnvelope`, where it must pass."

**Why derived and not hand-written.** Sixty-three hand-written payloads would be sixty-three
places to forget when a contract gains a field, and the roster gate would still pass — the
model would have a test that no longer exercises its new field. `minimal_payload()` walks
`model_fields`, so a field added to a contract is covered by the missing-field, wrong-type and
unknown-field cases the moment it exists, with nothing to update here.

**Three models need an override, and each override is a validator this file cannot satisfy by
type alone** — which is the point: they are the contracts carrying a rule beyond their shape.
`TraceRecord` refuses a `prediction`-kind record with no prediction; `SeatEnvelope` requires a
`result` that parses as JSON and a `usage` carrying the cache receipt. The overrides are
listed with the rule each one answers.

The wrong-type substitution is deliberately blunt: a list where anything but a list is
expected, a string where a list is. Pydantic coerces between scalars in lax mode — `"1"` is a
valid `int` — so a subtler substitution would produce a test that passes for the wrong reason.
"""

from __future__ import annotations

import types
import typing
from enum import Enum

import pytest
from pydantic import BaseModel, JsonValue, ValidationError

#: Substituted for a field of any non-list type. A list is what nothing else coerces from.
WRONG_TYPE_FOR_SCALAR: list[str] = ["__wrong_type__"]

#: Substituted for a list-typed field, where a list would of course be accepted.
WRONG_TYPE_FOR_LIST = "__wrong_type__"

#: The key added to prove `extra="forbid"`, and preserved to prove `SeatEnvelope`'s tolerance.
UNKNOWN_FIELD = "a_field_this_model_has_never_seen"

#: model name → the fields whose *validator* (not whose type) a derived value cannot satisfy.
OVERRIDES: dict[str, dict[str, object]] = {
    # A prediction-kind record with no prediction is refused: a node that records no
    # prediction cannot learn (binding contract 3).
    "TraceRecord": {
        "prediction": {
            "signal": "homeostasis_cost",
            "next_tick_tokens": 1,
            "next_tick_wall_seconds": 1.0,
        }
    },
    # Fact 2: `result` is a JSON string that must parse before validation.
    # Fact 4: `usage.cache_read_input_tokens` is present, so a cache receipt exists.
    "SeatEnvelope": {
        "result": "{}",
        "usage": {"cache_read_input_tokens": 0},
    },
}


def _unwrap_optional(annotation: object) -> object:
    """`X | None` → `X`. A union of real members keeps its first member."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        members = [a for a in typing.get_args(annotation) if a is not type(None)]
        return members[0] if members else str
    return annotation


def value_for(annotation: object) -> object:
    """One valid value for a field annotation, built from the annotation alone."""
    annotation = _unwrap_optional(annotation)

    if annotation is JsonValue:
        return "x"

    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return typing.get_args(annotation)[0]
    if origin in (list, set, frozenset, tuple):
        args = typing.get_args(annotation)
        return [value_for(args[0])] if args else []
    if origin is dict:
        args = typing.get_args(annotation)
        return {"k": value_for(args[1])} if len(args) == 2 else {}

    if isinstance(annotation, type):
        if issubclass(annotation, Enum):
            return next(iter(annotation)).value
        if issubclass(annotation, BaseModel):
            return minimal_payload(annotation)
        if issubclass(annotation, bool):
            return True
        if issubclass(annotation, int):
            return 1
        if issubclass(annotation, float):
            return 1.0
        if issubclass(annotation, str):
            return "x"
    return "x"


def minimal_payload(model: type[BaseModel]) -> dict[str, object]:
    """Every **required** field of the model, plus every discriminator, with a valid value.

    A `Literal` field carries a default and is therefore not required — but a discriminated
    union will not accept a member payload that omits the key it discriminates on, so the
    `emitter` and `signal` tags are always written out.
    """
    payload: dict[str, object] = {}
    for name, field in model.model_fields.items():
        if field.is_required() or typing.get_origin(field.annotation) is typing.Literal:
            payload[name] = value_for(field.annotation)
    payload.update(OVERRIDES.get(model.__name__, {}))
    return payload


def required_fields(model: type[BaseModel]) -> tuple[str, ...]:
    """The fields a payload cannot omit."""
    return tuple(name for name, f in model.model_fields.items() if f.is_required())


def wrong_value_for(model: type[BaseModel], name: str) -> object:
    """A value of a type the field cannot be coerced from."""
    annotation = _unwrap_optional(model.model_fields[name].annotation)
    if typing.get_origin(annotation) in (list, set, frozenset, tuple):
        return WRONG_TYPE_FOR_LIST
    return WRONG_TYPE_FOR_SCALAR


def wrong_typed_payload(model: type[BaseModel], name: str) -> dict[str, object]:
    """A minimal payload with exactly one field replaced by a value of the wrong type.

    Built on the minimal payload rather than on a fully populated one so that the *only*
    reason it can fail is the substitution: several contracts carry cross-field validators
    (`TraceRecord`'s two kinds, `EpisodeRecord`'s event naming) that a payload with every
    optional slot filled would trip for an unrelated reason.
    """
    payload = minimal_payload(model)
    payload[name] = wrong_value_for(model, name)
    return payload


def off_roster_case(
    model: type[BaseModel],
    payload: dict[str, object],
    *,
    drop: str | None = None,
    add: tuple[str, object] | None = None,
):
    """One of the three conformance properties `protean.state.MODELS` would have parametrized,
    for the two contracts that are deliberately off the roster.

    Both hand-written batteries state the same argument for why the coverage exists here at all,
    and both are kept verbatim on their modules:

    * `tests/state/test_habit_hits.py` — "`HabitHit` is deliberately **not** in
      `protean.state.MODELS` (order W7's writable set does not carry
      `src/protean/state/__init__.py`), exactly as `SeatCallRecord` is not, so it gets none of
      M7's parametrized conformance coverage. The three properties that parametrization would
      have supplied — the minimal payload validates, a missing required field fails, an unknown
      field is refused — are asserted directly below instead of assumed."
    * `tests/state/test_seat_calls.py` — "`SeatCallRecord` is deliberately **not** in
      `protean.state.MODELS` (order W3's writable set does not carry
      `src/protean/state/__init__.py`; see the dispatch ledger), so it gets none of M7's
      parametrized conformance coverage. The three properties that parametrization would have
      supplied — the minimal payload validates, a missing required field fails, an unknown field
      is refused — are asserted directly below instead of assumed."

    So what is shared is the *mechanics* of the three properties and nothing else: each module
    still names its own payload, its own required fields and its own unknown key, and each keeps
    its own extra assertions at the call site on the instance this returns.

    With neither keyword the payload must validate, and the validated instance comes back. With
    `drop` the named field is removed and the validation must be refused; with `add` the named
    key is added and the validation must be refused. `drop` is asserted present first, so a
    parametrization that drifted off the contract fails as itself rather than as a `KeyError`.
    """
    if drop is not None:
        assert drop in payload, f"{drop} is not on the payload this case claims to drop it from"
        payload = {k: v for k, v in payload.items() if k != drop}
    elif add is not None:
        payload = {**payload, add[0]: add[1]}
    else:
        return model.model_validate(payload)

    with pytest.raises(ValidationError):
        model.model_validate(payload)
    return None
