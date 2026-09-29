"""`SeatCallRecord` — S2's field list, the keyed append, the version refusal, the spend rule.

`the build specification (not in this mirror)` § Deliverable 2 (seam contract S2), § Resolutions S-8 and
S-19, **as build A.1 amends them** (`the build specification (not in this mirror)` § Scaffold clause
item 2, § Deliverable 4's journal/receipt table, § Deliverable 6). DoD row **W3**'s record half —
the boundary half is `tests/runtime/test_seat_calls_boundary.py`; builder row **K3**'s round trip
lives here.

**A.1 amends S2 in five named ways and in no others**: the record gains `node`, `call#`,
`member#` and `kind`; its key widens to `(task, tick, node, call#, member#, outcome)`; `request`
is **removed**, the payload living in the journal alone; its write rule becomes one line per
journalled call; and `ref` stays optional and is `None` for think, escalate and delegate.

`SeatCallRecord` is deliberately **not** in `protean.state.MODELS` (order W3's writable set does
not carry `src/protean/state/__init__.py`; see the dispatch ledger), so it gets none of M7's
parametrized conformance coverage. The three properties that parametrization would have supplied
— the minimal payload validates, a missing required field fails, an unknown field is refused —
are asserted directly below instead of assumed.

**No live call, and no `SeatCallFacts` from a real adapter.** Every case is driven from a
hand-built facts object, which is what makes this module a contract test rather than a seat test.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from protean import config
from protean.runtime.seat import SEAT_CALL_OUTCOMES, SeatCallFacts
from protean.state.enums import CallType, NodeName, Tier
from protean.state.errors import SchemaVersionMismatch
from protean.state.seat_calls import (
    ARTIFACT,
    SPEND_KEYS,
    SeatCallRecord,
    append_seat_call,
    cache_reads,
    dedupe_key,
    load_seat_calls,
    spend_tokens,
)
from tests.state.samples import off_roster_case

#: Every field seam contract S2's table names, so "the field list is binding" is a check rather
#: than a reading of the model someone wrote.
S2_FIELDS = (
    "schema_version",
    "task",
    "tick",
    "tier",
    "ref",
    "session_handle",
    "model",
    "effort",
    "permission_mode",
    "cli_version",
    "usage",
    "model_usage",
    "wall_seconds",
    "outcome",
)

#: A.1's four new columns, beside S2's own list (§ Scaffold clause item 2).
A1_FIELDS = ("node", "call_number", "member_number", "kind")

#: **A.1.i's four**, under the one bump 2 → 3 (`the build specification (not in this mirror)`
#: § Scaffold clause item 2, § Deliverable 6): the two effective caps `SPAWN_RECEIPT_FIELDS` has
#: named since A.1 and **no column carried until this build**, plus the two witness fields that are
#: the amendment itself.
A1I_FIELDS = ("max_call_usd", "timeout_seconds", "permission_denials", "audit")

REQUEST = {"tick": 3, "workspace": {"goals": []}}


def facts(**overrides) -> SeatCallFacts:
    """One invocation's facts, as an adapter hands them to the boundary."""
    payload = {
        "tier": str(Tier.MANAGER),
        "argv": ("--output-format", "json", "--effort", "high"),
        "cli_version": "9.9.9 (Test)",
        "session_handle": "handle-planner",
        "model": "model-under-test",
        "effort": "high",
        "permission_mode": None,
        "request": REQUEST,
        "wall_seconds": 1.25,
        "outcome": "ok",
        "usage": {"cache_read_input_tokens": 7, "input_tokens": 2, "output_tokens": 5},
        "model_usage": {"model-under-test": {"inputTokens": 2}},
        "num_turns": 2,
        "error": "",
    }
    payload.update(overrides)
    return SeatCallFacts(**payload)


def record(**overrides) -> SeatCallRecord:
    """One journalled call's receipt, composed the way the boundary composes it."""
    key = {name: overrides.pop(name) for name in list(overrides) if name in KEY_ARGUMENTS}
    return SeatCallRecord.from_call(
        facts(**overrides),
        task="task-1",
        tick=3,
        node=key.get("node", NodeName.CORTEX),
        call_number=key.get("call_number", 1),
        member_number=key.get("member_number"),
        kind=key.get("kind", ""),
        ref="r1",
    )


#: What `record()` routes to the key rather than to the facts.
KEY_ARGUMENTS = ("node", "call_number", "member_number", "kind")


# --------------------------------------------------------------------------------------
# S2's field list, and the three fields the DoD asks of the record rather than the facts
# --------------------------------------------------------------------------------------


def test_every_field_seam_contract_s2_names_is_on_the_record() -> None:
    missing = [name for name in S2_FIELDS if name not in SeatCallRecord.model_fields]
    assert missing == [], "S2's field list is binding"


def test_the_three_extra_fields_are_the_ones_the_dod_reads_off_the_record() -> None:
    """Row K1 reads `argv` and `num_turns` off a `SeatCallRecord`; `error` carries a refusal."""
    extra = sorted(
        set(SeatCallRecord.model_fields)
        - set(S2_FIELDS)
        - set(A1_FIELDS)
        - set(A1I_FIELDS)
    )
    assert extra == ["argv", "dispatch_id", "error", "num_turns"]


def test_build_a1i_added_exactly_its_four_columns_under_one_bump() -> None:
    """§ Scaffold clause item 2's **A.1.i** amendment of S2, as a check rather than as a reading.

    The receipt's field set gains `permission_denials` and `audit` — the amendment — beside the two
    caps `SPAWN_RECEIPT_FIELDS` has named since A.1 and that **no column carried until this build**,
    the landed gap A.1.i lands. **Four columns, one bump**, and the column set is exactly S2's plus
    A.1's four plus these four plus the three the DoD asks of the record.
    """
    missing = [name for name in A1I_FIELDS if name not in SeatCallRecord.model_fields]
    assert missing == []
    assert len(A1I_FIELDS) == 4, "four columns, not two"
    assert set(SeatCallRecord.model_fields) == set(S2_FIELDS) | set(A1_FIELDS) | set(
        A1I_FIELDS
    ) | {"argv", "dispatch_id", "error", "num_turns"}


def test_build_a1_added_exactly_its_four_columns_and_removed_request() -> None:
    """§ Scaffold clause item 2's amendment of S2, as a check rather than as a reading.

    `request` is **removed, not deprecated** (folded: S-A73): the journal entry for the same
    call carries the payload in full, and a fact with two homes is a fact with two versions.
    """
    missing = [name for name in A1_FIELDS if name not in SeatCallRecord.model_fields]
    assert missing == []
    assert "request" not in SeatCallRecord.model_fields, "the payload has one home: the journal"
    assert "dispatch_id" in SeatCallRecord.model_fields, "receipt-only (folded: S-A14)"


def test_the_schema_version_is_the_literal_order_w2_authored() -> None:
    assert record().schema_version == config.SEAT_CALL_SCHEMA_VERSION


def test_the_outcome_set_is_the_seams_own_set() -> None:
    """The literal restates `runtime.seat`'s tuple; this is what stops the copy drifting."""
    annotation = SeatCallRecord.model_fields["outcome"].annotation
    assert set(annotation.__args__) == set(SEAT_CALL_OUTCOMES)


# --------------------------------------------------------------------------------------
# Composition at the boundary: the adapter's facts plus the runtime's three
# --------------------------------------------------------------------------------------


def test_from_call_carries_every_fact_and_the_journals_key() -> None:
    source = facts()
    built = SeatCallRecord.from_call(
        source,
        task="task-1",
        tick=3,
        node=NodeName.CORTEX,
        call_number=1,
        ref="task-1:3:cortex:manager:prediction",
    )

    assert (built.task, built.tick, built.ref) == (
        "task-1",
        3,
        "task-1:3:cortex:manager:prediction",
    )
    assert built.tier is Tier.MANAGER
    assert (built.node, built.call_number, built.member_number) == (NodeName.CORTEX, 1, None)
    assert built.argv == list(source.argv)
    assert (built.cli_version, built.session_handle) == (source.cli_version, source.session_handle)
    assert (built.model, built.effort, built.permission_mode) == (
        source.model,
        source.effort,
        source.permission_mode,
    )
    assert (built.usage, built.model_usage) == (source.usage, source.model_usage)
    assert (built.wall_seconds, built.outcome, built.num_turns) == (1.25, "ok", 2)


def test_the_ref_is_optional_because_a_refusal_names_no_prediction() -> None:
    refused = SeatCallRecord.from_call(
        facts(outcome="unavailable", error="exit: boom"),
        task="task-1",
        tick=3,
        node=NodeName.CORTEX,
        call_number=1,
    )
    assert refused.ref is None
    assert refused.error == "exit: boom"


def test_a_restored_call_gets_a_line_with_the_key_and_no_adapter_columns() -> None:
    """§ Deliverable 6 — one line per journalled call of the committing pass, **restored or live**.

    A restored call made no invocation, so there are no adapter facts at all: the journal's key
    is the whole of what the line can say, and `outcome` is the caller's — `ok` for a call whose
    entry carried an envelope, `unavailable` for one that recorded a refusal.
    """
    restored = SeatCallRecord.from_call(
        None,
        task="task-1",
        tick=3,
        node=NodeName.HOMEOSTASIS,
        call_number=1,
        tier=CallType.THINK,
        outcome="ok",
    )
    assert (restored.node, restored.call_number, restored.tier) == (
        NodeName.HOMEOSTASIS,
        1,
        CallType.THINK,
    )
    assert (restored.argv, restored.usage, restored.cli_version) == ([], {}, "")
    assert restored.outcome == "ok"
    assert restored.ref is None, "think, escalate and delegate mint no prediction (S-A9)"


def test_a_record_round_trips_through_its_json_line() -> None:
    """Builder row K3's round trip: dump, re-read, and every field is what it was."""
    original = record()
    restored = SeatCallRecord.model_validate(json.loads(original.model_dump_json()))
    assert restored == original


# --------------------------------------------------------------------------------------
# Conformance — the coverage `protean.state.MODELS` would have supplied
# --------------------------------------------------------------------------------------


def test_the_minimal_payload_is_valid() -> None:
    minimal = {"schema_version": 1, "task": "t", "tick": 0, "tier": "director"}
    assert off_roster_case(SeatCallRecord, minimal).tier is Tier.DIRECTOR


def test_the_addressee_column_is_optional_for_the_journals_own_reason() -> None:
    """§ Deliverable 6 — a think call has no tier, so both columns moved together."""
    payload = {"schema_version": 1, "task": "t", "tick": 0}
    assert SeatCallRecord.model_validate(payload).tier is None
    assert SeatCallRecord.model_validate({**payload, "tier": "think"}).tier is CallType.THINK


@pytest.mark.parametrize("field", ["schema_version", "task", "tick"])
def test_a_missing_required_field_fails(field: str) -> None:
    payload = {"schema_version": 1, "task": "t", "tick": 0, "tier": "director"}
    off_roster_case(SeatCallRecord, payload, drop=field)


def test_an_unknown_field_is_refused() -> None:
    payload = {"schema_version": 1, "task": "t", "tick": 0, "tier": "director"}
    off_roster_case(SeatCallRecord, payload, add=("nope", 1))


def test_an_outcome_outside_the_closed_set_is_refused() -> None:
    with pytest.raises(ValidationError):
        SeatCallRecord.model_validate(
            {"schema_version": 1, "task": "t", "tick": 0, "tier": "director", "outcome": "fine"}
        )


# --------------------------------------------------------------------------------------
# The dedupe key: one line per invocation, and a retry is its own line
# --------------------------------------------------------------------------------------


def test_the_key_is_task_tick_node_call_member_and_outcome() -> None:
    """§ Deliverable 4 — widened with the journal's, so N calls per node cannot collide."""
    assert record().dedupe_key() == ("task-1", 3, "cortex", 1, None, "ok")


def test_two_calls_by_one_node_in_one_tick_do_not_collide() -> None:
    """The whole reason the key widened: build 2's `(task, tick, tier, outcome)` could not.

    Two think calls by one node in one tick have the same addressee and the same outcome, so
    under the landed key they were one line — a silent no-op on the second append.
    """
    first = record(node=NodeName.HOMEOSTASIS, call_number=1, tier=str(CallType.THINK))
    second = record(node=NodeName.HOMEOSTASIS, call_number=2, tier=str(CallType.THINK))
    assert first.dedupe_key() != second.dedupe_key()
    assert first.dedupe_key()[:3] == second.dedupe_key()[:3], "same task, tick and node"


def test_a_waves_members_do_not_collide_under_one_call_number() -> None:
    """The `member#` sub-key's shape (§ Deliverable 6). **The wave itself is order W8's.**"""
    first = record(call_number=1, member_number=1)
    second = record(call_number=1, member_number=2)
    assert first.dedupe_key() != second.dedupe_key()
    assert first.member_number == 1 and second.member_number == 2


def test_the_key_function_reads_the_payload_the_same_way() -> None:
    built = record()
    assert dedupe_key(built.model_dump(mode="json")) == built.dedupe_key()


def test_a_retry_and_its_second_invocation_do_not_collide() -> None:
    """folded: S-8 — the first of a retried pair is `decode_retry`, so the keys differ."""
    first = record(outcome="decode_retry")
    second = record(outcome="ok")
    assert first.dedupe_key() != second.dedupe_key()


def test_two_appends_of_one_record_leave_one_line(tmp_path: Path) -> None:
    path = tmp_path / "seat_calls.jsonl"
    assert append_seat_call(path, record()) is not None
    assert append_seat_call(path, record()) is None, "a key collision is a silent no-op"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_a_retry_writes_two_lines(tmp_path: Path) -> None:
    path = tmp_path / "seat_calls.jsonl"
    append_seat_call(path, record(outcome="decode_retry"))
    append_seat_call(path, record(outcome="ok"))
    outcomes = [line.outcome for line in load_seat_calls(path)]
    assert outcomes == ["decode_retry", "ok"]


def test_the_append_is_physically_append_only(tmp_path: Path) -> None:
    path = tmp_path / "seat_calls.jsonl"
    append_seat_call(path, record(outcome="decode_retry"))
    before = path.read_bytes()
    append_seat_call(path, record(outcome="ok"))
    assert path.read_bytes().startswith(before)


# --------------------------------------------------------------------------------------
# The loader, and the refusal that quotes both numbers
# --------------------------------------------------------------------------------------


def test_the_loader_reads_a_missing_file_as_no_records(tmp_path: Path) -> None:
    assert load_seat_calls(tmp_path / "absent.jsonl") == []


def test_the_loader_refuses_a_schema_version_it_does_not_write(tmp_path: Path) -> None:
    path = tmp_path / "seat_calls.jsonl"
    payload = record().model_dump(mode="json")
    payload["schema_version"] = config.SEAT_CALL_SCHEMA_VERSION + 41
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(SchemaVersionMismatch) as raised:
        load_seat_calls(path)

    message = str(raised.value)
    print(f"refusal: {message}")
    assert ARTIFACT in message
    assert str(config.SEAT_CALL_SCHEMA_VERSION + 41) in message, "the number on disk"
    assert str(config.SEAT_CALL_SCHEMA_VERSION) in message, "the number in the running code"
    assert "refuses rather than migrating" in message


def test_the_file_is_byte_identical_when_nothing_new_is_appended(tmp_path: Path) -> None:
    path = tmp_path / "seat_calls.jsonl"
    append_seat_call(path, record())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    append_seat_call(path, record())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


# --------------------------------------------------------------------------------------
# S-19: the per-iteration spend rule, and the cache read that is never spend
# --------------------------------------------------------------------------------------


def test_the_spend_keys_leave_the_cache_read_out() -> None:
    assert "cache_read_input_tokens" not in SPEND_KEYS
    assert set(SPEND_KEYS) == {"input_tokens", "cache_creation_input_tokens", "output_tokens"}


def test_the_spend_is_the_per_iteration_sum_not_the_aggregate() -> None:
    usage = {
        "input_tokens": 999,
        "cache_creation_input_tokens": 999,
        "cache_read_input_tokens": 40940,
        "output_tokens": 999,
        "iterations": [
            {
                "input_tokens": 2,
                "output_tokens": 718,
                "cache_read_input_tokens": 40940,
                "cache_creation_input_tokens": 1365,
            },
            {
                "input_tokens": 1,
                "output_tokens": 10,
                "cache_read_input_tokens": 40940,
                "cache_creation_input_tokens": 4,
            },
        ],
    }
    assert spend_tokens(usage) == 2 + 718 + 1365 + 1 + 10 + 4
    assert cache_reads(usage) == 40940, "recorded, and not in the sum above"


def test_an_envelope_with_no_iterations_is_read_as_one(tmp_path: Path) -> None:
    """Every build-1 scripted envelope, and the at-cap shape whose list is empty."""
    flat = {"cache_read_input_tokens": 5, "input_tokens": 10, "output_tokens": 3}
    assert spend_tokens(flat) == 13
    assert spend_tokens({**flat, "iterations": []}) == 13


def test_the_first_live_envelope_spends_its_own_iteration(repo_root: Path) -> None:
    """The captured wire shape, not a hand-authored one: 2 + 22170 + 53."""
    usage = json.loads(
        (repo_root / "fixtures" / "envelopes" / "live-first.json").read_text(encoding="utf-8")
    )["usage"]
    assert spend_tokens(usage) == 22225
    assert cache_reads(usage) == 0


def test_the_record_reports_its_own_spend_and_receipt() -> None:
    built = record()
    assert built.spend_tokens() == 7, "2 input + 5 output; the 7 cache reads are not spend"
    assert built.cache_reads() == 7
