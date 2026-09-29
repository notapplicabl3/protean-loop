"""The narrowed schema, and the offline compile probe row K1 closes on.

`the build specification (not in this mirror)` § Deliverable 1 → *The narrowed schema*, § Directional
decisions 10 (folded: A1-14, folded: S-36). Order W2's DoD row **K1**, its offline half:

* the property set handed to a seat equals its result model's **minus exactly `tick` and
  `emitter`**, per tier;
* the adapter — through `decode_seat_result()` — fills both back before validation, so a live
  answer that carries neither and a scripted envelope that carries both decode identically;
* the compile probe passes for all three tiers, offline, with no model call and no money.

**K1's fourth clause is not here**: S-38 restated it off `num_turns == 1` — the wire says a
structured call is a forced tool call and never one turn (measured 2 and 3, dispatch-5 ledger
D5-10) — and onto the mechanism, the recorded argv carrying `--tools ""` and no `--add-dir`,
with `num_turns` recorded rather than bounded. It is asserted in `test_live_invoke.py`, over
the real capture in `captures/tools-flag-probe.json` and over the stand-in's recorded argv.
"""

from __future__ import annotations

import json

import pytest

from protean.cortex.live.schema import (
    RUNTIME_OWNED_FIELDS,
    compile_probe,
    narrowed_schema,
    schema_argument,
    strict_types_violations,
)
from protean.runtime.seat import decode_seat_result, result_model
from protean.state.enums import CallType, Tier
from tests.runtime import stubs

TIERS = [str(tier) for tier in Tier]


@pytest.mark.parametrize("tier", TIERS)
def test_the_narrowed_property_set_is_the_models_minus_exactly_two(tier: str) -> None:
    """Row **K1**'s offline half, per tier: four readings of one narrowed schema.

    1. "omits `tick` and `emitter` and no other field";
    2. a schema that still *required* `tick` would ask the seat for the number it removed, so the
       two leave `required` too;
    3. everything except the two deletions is byte-identical to the model's own schema — derived
       from pydantic, never hand-written;
    4. "a schema-compile probe over all three tiers' narrowed schemas passes offline", and the
       flag's own argument carries that very schema.
    """
    full = result_model(tier).model_json_schema()
    narrowed = narrowed_schema(tier)

    # 1. the property set is the model's, minus exactly the two runtime-owned fields
    assert set(full["properties"]) - set(narrowed["properties"]) == set(RUNTIME_OWNED_FIELDS)
    assert set(narrowed["properties"]) - set(full["properties"]) == set()

    # 2. and they leave `required` with it
    assert "tick" not in narrowed.get("required", [])
    assert "emitter" not in narrowed.get("required", [])

    # 3. derived from the model, not transcribed from it
    assert narrowed["$defs"] == full["$defs"]
    for name, body in narrowed["properties"].items():
        assert body == full["properties"][name], name

    # 4. it compiles offline, and `--schema` carries it
    assert strict_types_violations(narrowed) == []
    assert json.loads(schema_argument(tier)) == narrowed


def test_the_probe_covers_all_three_tiers_in_one_call() -> None:
    probed = compile_probe()
    assert sorted(probed) == sorted(TIERS)
    assert all(violations == [] for violations in probed.values())


def test_the_probe_is_not_vacuous() -> None:
    """A hand-written overlay is the case that fails an ajv strict-types compile."""
    overlay = {
        "type": "object",
        "properties": {"narrative": {"minLength": 1}},
    }
    violations = strict_types_violations(overlay)
    assert violations, "a constraint keyword with no sibling `type` has to be caught"
    assert "minLength" in violations[0]


def test_a_ref_outside_defs_is_caught() -> None:
    violations = strict_types_violations({"type": "object", "$ref": "https://example/x.json"})
    assert any("$ref" in item for item in violations)


# --------------------------------------------------------------------------------------
# The other half of decision 10: the decoder fills what the schema removed
# --------------------------------------------------------------------------------------


def test_a_live_answer_carrying_neither_field_decodes_once_the_tick_is_passed() -> None:
    """What a seat handed the narrowed schema actually returns: no `tick`, no `emitter`."""
    envelope = stubs.envelope({"unit_id": "u1", "narrative": "did it"})
    decoded = decode_seat_result(CallType.DISPATCH, envelope, 7)
    assert decoded.tick == 7
    assert str(decoded.emitter) == "dispatch"


def test_a_scripted_envelope_and_a_live_one_decode_to_the_same_model() -> None:
    """folded: S-17 — one decode path, and the two shapes meet inside it."""
    live = stubs.envelope({"unit_id": "u1", "narrative": "did it"})
    scripted = stubs.envelope(
        {"unit_id": "u1", "narrative": "did it", "tick": 7, "emitter": "dispatch"}
    )
    assert decode_seat_result(CallType.DISPATCH, live, 7) == decode_seat_result(
        CallType.DISPATCH, scripted, 7
    )


def test_without_a_tick_the_build_one_contract_is_unchanged() -> None:
    """`tick=None` is build 1's call: nothing is filled, and a missing `tick` is a decode error."""
    from protean.runtime.seat import SeatDecodeError

    envelope = stubs.envelope({"unit_id": "u1", "narrative": "did it"})
    with pytest.raises(SeatDecodeError):
        decode_seat_result(CallType.DISPATCH, envelope)
