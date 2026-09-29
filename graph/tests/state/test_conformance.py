"""M7: every contract fails on a missing or wrong-typed field, and refuses an unknown one.

`the build specification (not in this mirror)` § Deliverable 7 → *Contract conformance*, and § Deliverable 2
→ "Every model sets `extra="forbid"`, with exactly one exception, `SeatEnvelope`."

Every case here is parametrized over `protean.state.MODELS`, which
`tests/state/test_roster.py` proves is the whole exported contract set — so "every contract has
a conformance test" is a property of the parametrization rather than a claim about a list
someone kept up to date.

The asymmetry `SeatEnvelope` is the one exception to gets its own module,
`test_seat_envelope.py`, because it is four positive facts rather than one negative rule.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from protean.state import EXTRA_TOLERANT_MODELS, MODELS
from tests.state.samples import (
    UNKNOWN_FIELD,
    minimal_payload,
    required_fields,
    wrong_typed_payload,
)

MISSING_CASES = [(m, f) for m in MODELS for f in required_fields(m)]
WRONG_TYPE_CASES = [(m, f) for m in MODELS for f in m.model_fields]


def _id(case: tuple[type, str]) -> str:
    return f"{case[0].__name__}.{case[1]}"


@pytest.mark.parametrize("case", MISSING_CASES, ids=_id)
def test_a_missing_required_field_fails(case: tuple[type, str]) -> None:
    model, field = case
    payload = minimal_payload(model)
    payload.pop(field)
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("case", WRONG_TYPE_CASES, ids=_id)
def test_a_wrong_typed_field_fails(case: tuple[type, str]) -> None:
    model, field = case
    with pytest.raises(ValidationError):
        model.model_validate(wrong_typed_payload(model, field))


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_an_unknown_field_is_refused_except_by_the_one_tolerant_model(model: type) -> None:
    """`extra="forbid"` everywhere but `SeatEnvelope`, which accepts **and preserves**."""
    payload = minimal_payload(model)
    payload[UNKNOWN_FIELD] = {"nested": ["and", "preserved"]}
    if model in EXTRA_TOLERANT_MODELS:
        # Acceptance only. The accept-and-preserve literal is asserted once, on the one tolerant
        # model: `test_seat_envelope.py::test_an_unknown_field_is_accepted_and_preserved`.
        model.model_validate(payload)
    else:
        with pytest.raises(ValidationError):
            model.model_validate(payload)


def test_exactly_one_model_tolerates_an_unknown_field() -> None:
    """The exception is one model, named, not a property some models drifted into."""
    tolerant = [m for m in MODELS if m.model_config.get("extra") == "allow"]
    assert tolerant == list(EXTRA_TOLERANT_MODELS)
    assert [m.__name__ for m in tolerant] == ["SeatEnvelope"]


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_every_contract_round_trips_through_json(model: type) -> None:
    """A contract that cannot survive `model_dump(mode="json")` cannot be persisted.

    Its **first line** is the minimal-payload validity claim, folded in whole: the baseline
    every negative case in this module is a one-field departure from is
    `model_validate(minimal_payload(model))`, so a generator or a contract that stopped
    producing a valid minimal payload fails here, on that line, before the round trip.
    """
    instance = model.model_validate(minimal_payload(model))
    assert model.model_validate(instance.model_dump(mode="json")) == instance
