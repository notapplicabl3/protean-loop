"""M7's asymmetry: the four required facts, and the one model that tolerates an extra.

`the build specification (not in this mirror)` § Deliverable 6 → *The wire shape is the real one*, and
§ Deliverable 2's `SeatEnvelope` row: "The one extra-tolerant model: the four measured facts
are required, unknown fields are accepted and preserved, so build 2 *diffs* a captured
envelope instead of rejecting it."

The four negative cases are file-backed. `fixtures/envelopes/` is hand-authored **to the
model**, not captured — the first diff of a real envelope is build 2's first wet row — and
each `missing_*.json` is the success fixture with exactly one fact removed, so a case that
started passing would mean the model stopped requiring that fact rather than that the fixture
drifted.

`unknown_field.json` is the other half: it carries a key this model has never seen, at the top
level, and the assertion is that it survives a round trip. Preservation is the property build 2
needs; acceptance alone would silently drop the field the diff exists to find.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from protean.state import CACHE_READ_KEY, STRUCTURED_SUCCESS_STOP_REASON, SeatEnvelope

#: Fact 3's overhead prefix. It is a literal HERE and not in `src/protean/state/`: M21 forbids
#: any module outside `src/protean/cortex/` from naming the CLI's model ids, and the battery's
#: harness is outside that grep by construction, exactly as ruling S-16 puts policy citations
#: outside M24. The seat adapters hold the production copy.
OVERHEAD_MODEL_PREFIX = "claude-haiku"

SUCCESS_FIXTURES = ("director_success.json", "planner_success.json", "executor_success.json")

#: The four measured facts, and the fixture that removes each one.
MISSING_FACT_FIXTURES = {
    "stop_reason": "missing_stop_reason.json",
    "result": "missing_result.json",
    "modelUsage": "missing_model_usage.json",
    f"usage.{CACHE_READ_KEY}": "missing_cache_read.json",
}


@pytest.mark.parametrize("name", SUCCESS_FIXTURES)
def test_a_hand_authored_success_envelope_validates(load_envelope, name: str) -> None:
    envelope = SeatEnvelope.model_validate(load_envelope(name))
    assert envelope.stop_reason == STRUCTURED_SUCCESS_STOP_REASON
    assert envelope.is_structured_success()


@pytest.mark.parametrize("fact", sorted(MISSING_FACT_FIXTURES), ids=lambda f: f)
def test_an_envelope_missing_a_required_fact_is_refused(load_envelope, fact: str) -> None:
    """The asymmetry's other half: tolerant of extras, never of a missing fact."""
    with pytest.raises(ValidationError):
        SeatEnvelope.model_validate(load_envelope(MISSING_FACT_FIXTURES[fact]))


def test_an_unknown_field_is_accepted_and_preserved(load_envelope) -> None:
    payload = load_envelope("unknown_field.json")
    envelope = SeatEnvelope.model_validate(payload)
    assert envelope.model_extra["a_field_this_model_has_never_seen"] == {
        "nested": ["and", "preserved"]
    }
    assert envelope.model_dump()["a_field_this_model_has_never_seen"] == {
        "nested": ["and", "preserved"]
    }


def test_the_success_fixtures_already_carry_fields_the_model_never_declared(
    load_envelope,
) -> None:
    """The tolerance is exercised by the ordinary fixtures, not only by the special one."""
    envelope = SeatEnvelope.model_validate(load_envelope("executor_success.json"))
    assert set(envelope.model_extra) >= {"type", "subtype", "is_error", "session_id"}


def test_a_result_that_is_not_a_json_string_is_refused(load_envelope) -> None:
    """Fact 2: `result` is a JSON **string** that must parse before validation."""
    with pytest.raises(ValidationError) as raised:
        SeatEnvelope.model_validate(load_envelope("result_not_json.json"))
    assert "parses before validation" in str(raised.value)


def test_result_stays_a_string_and_is_parsed_on_demand(load_envelope) -> None:
    envelope = SeatEnvelope.model_validate(load_envelope("executor_success.json"))
    assert isinstance(envelope.result, str)
    parsed = envelope.parsed_result()
    assert parsed["emitter"] == "executor"
    assert parsed["observations"][0]["content_hash"] == "c1a1"


def test_a_parsed_result_object_is_refused(load_envelope) -> None:
    """A seam that accepted a parsed object would let a mock skip the parse a real seat needs."""
    payload = load_envelope("executor_success.json")
    payload["result"] = {"emitter": "dispatch"}
    with pytest.raises(ValidationError):
        SeatEnvelope.model_validate(payload)


def test_the_overhead_call_is_excluded_from_the_first_party_tally(load_envelope) -> None:
    """Fact 3: assertions read "no first-party model *beyond* the haiku overhead call"."""
    envelope = SeatEnvelope.model_validate(load_envelope("executor_success.json"))
    assert any(m.startswith(OVERHEAD_MODEL_PREFIX) for m in envelope.modelUsage)
    assert envelope.first_party_models(OVERHEAD_MODEL_PREFIX) == ("protean-executor-model",)


def test_a_stop_reason_other_than_tool_use_still_validates(load_envelope) -> None:
    """`end_turn` and `max_tokens` are real; only `tool_use` is *structured success*."""
    payload = load_envelope("executor_success.json")
    payload["stop_reason"] = "max_tokens"
    envelope = SeatEnvelope.model_validate(payload)
    assert envelope.is_structured_success() is False


def test_the_cache_receipt_key_is_the_one_the_spec_names() -> None:
    assert CACHE_READ_KEY == "cache_read_input_tokens"
