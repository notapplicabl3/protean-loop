"""`HabitHit` — P3's field list, the keyed append, the version refusal, the tolerant reader.

`the build specification (not in this mirror)` § Deliverable 4 (seam contract P3), § Directional decisions
14, § Resolutions S-1, S-5, D16-7. DoD row **L7**'s record half — the boundary half is
`tests/runtime/test_habit_hits_boundary.py`.

`HabitHit` is deliberately **not** in `protean.state.MODELS` (order W7's writable set does not
carry `src/protean/state/__init__.py`), exactly as `SeatCallRecord` is not, so it gets none of
M7's parametrized conformance coverage. The three properties that parametrization would have
supplied — the minimal payload validates, a missing required field fails, an unknown field is
refused — are asserted directly below instead of assumed.

**The file it does not widen is checked here too.** S2 fixes `seat_calls.jsonl` at one line per
live invocation and build 2's row W3 is landed; the last section asserts the two records stay
two records, with neither field list reaching into the other.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from protean import config
from protean.brain.jsonl import read_lines
from protean.runtime.paths import HABIT_HITS_FILENAME, BrainPaths
from protean.runtime.seat import HabitFacts
from protean.sleep.habits import read_habit_hits
from protean.state.enums import Tier
from protean.state.errors import SchemaVersionMismatch
from protean.state.habit_hits import (
    ARTIFACT,
    HabitHit,
    append_habit_hit,
    dedupe_key,
    load_habit_hits,
)
from protean.state.seat_calls import SeatCallRecord
from protean.state.seats import CACHE_READ_KEY, SeatEnvelope
from tests.state.samples import off_roster_case

#: Every field § Deliverable 4's P3 paragraph names, so "the field list is binding" is a check
#: rather than a reading of the model someone wrote.
P3_FIELDS = (
    "schema_version",
    "task",
    "tick",
    "tier",
    "ref",
    "procedure_id",
    "matched_condition",
    "avoided_model",
)

#: The four the withdrawal reader joins on (ledger `D16-7`) — required, not merely present.
WITHDRAWAL_JOINS = ("procedure_id", "task", "tick", "ref")

DIGEST = "0123456789abcdef"


def envelope(payload: dict | None = None) -> SeatEnvelope:
    return SeatEnvelope(
        stop_reason="tool_use",
        result=json.dumps(payload or {"emitter": "manager", "tick": 3}),
        modelUsage={"model-planner": {"inputTokens": 0}},
        usage={CACHE_READ_KEY: 0},
    )


def facts(**overrides) -> HabitFacts:
    """One habit match's facts, as the matcher hands them to the boundary."""
    payload = {
        "tier": str(Tier.MANAGER),
        "envelope": envelope(),
        "procedure_id": f"habit-manager-{DIGEST}",
        "matched_condition": {"goal_digest": DIGEST},
        "avoided_model": "a-model",
    }
    payload.update(overrides)
    return HabitFacts(**payload)


def record(**overrides) -> HabitHit:
    return HabitHit.from_facts(
        facts(**overrides), task="task-1", tick=3, ref="task-1:3:cortex:planner:prediction"
    )


# --------------------------------------------------------------------------------------
# P3's field list
# --------------------------------------------------------------------------------------


def test_the_record_carries_nothing_the_spec_does_not_name() -> None:
    """Eight fields, and P3 is a seam contract: an extra one is a widening, not a detail."""
    assert tuple(HabitHit.model_fields) == P3_FIELDS


def test_the_schema_version_is_the_literal_order_w2_authored() -> None:
    assert record().schema_version == config.HABIT_HIT_SCHEMA_VERSION
    assert config.BUILD3_ARTIFACT_SCHEMA_VERSIONS["habit_hit"] == (
        config.HABIT_HIT_SCHEMA_VERSION
    )


def test_the_artifact_name_is_the_one_a_refusal_quotes() -> None:
    assert ARTIFACT == HABIT_HITS_FILENAME.removesuffix(".jsonl")


def test_from_facts_carries_every_fact_and_the_runtimes_three() -> None:
    hit = record()
    assert hit.task == "task-1" and hit.tick == 3
    assert hit.ref == "task-1:3:cortex:planner:prediction"
    assert hit.tier is Tier.MANAGER
    assert hit.procedure_id == f"habit-manager-{DIGEST}"
    assert hit.matched_condition == {"goal_digest": DIGEST}
    assert hit.avoided_model == "a-model"


def test_the_matched_condition_is_copied_rather_than_aliased() -> None:
    source = facts()
    hit = HabitHit.from_facts(source, task="t", tick=1, ref="r")
    hit.matched_condition["goal_digest"] = "moved"
    assert source.matched_condition == {"goal_digest": DIGEST}


# --------------------------------------------------------------------------------------
# The contract properties `MODELS` would have supplied
# --------------------------------------------------------------------------------------


def test_a_record_round_trips_through_its_json_line() -> None:
    hit = record()
    assert HabitHit.model_validate(json.loads(json.dumps(hit.model_dump(mode="json")))) == hit


def test_the_minimal_payload_is_valid() -> None:
    hit = off_roster_case(
        HabitHit,
        {
            "schema_version": config.HABIT_HIT_SCHEMA_VERSION,
            "task": "t",
            "tick": 1,
            "tier": Tier.DIRECTOR,
            "ref": "r",
            "procedure_id": "p",
        },
    )
    assert hit.matched_condition == {} and hit.avoided_model == ""


@pytest.mark.parametrize("field", WITHDRAWAL_JOINS + ("tier",))
def test_a_missing_required_field_fails(field: str) -> None:
    off_roster_case(HabitHit, record().model_dump(mode="json"), drop=field)


def test_an_unknown_field_is_refused() -> None:
    off_roster_case(HabitHit, record().model_dump(mode="json"), add=("spent", 12))


def test_the_ref_is_required_because_a_habit_always_names_a_prediction() -> None:
    """Unlike `SeatCallRecord.ref`: a refused *call* mints no record, a habit always does."""
    payload = record().model_dump(mode="json")
    payload["ref"] = None
    with pytest.raises(ValidationError):
        HabitHit.model_validate(payload)


# --------------------------------------------------------------------------------------
# The key, and the append
# --------------------------------------------------------------------------------------


def test_the_key_is_task_tick_and_tier() -> None:
    assert record().dedupe_key() == ("task-1", 3, str(Tier.MANAGER))


def test_the_key_function_reads_the_payload_the_same_way() -> None:
    hit = record()
    assert dedupe_key(hit.model_dump(mode="json")) == hit.dedupe_key()


def test_there_is_no_outcome_component_because_a_habit_never_retries() -> None:
    """`SeatCallRecord`'s fourth component keeps a decode retry's two lines apart; a tick takes
    at most one procedure per tier, so there is nothing here for a fourth to separate."""
    assert len(record().dedupe_key()) == 3
    assert len(SeatCallRecord.model_fields["outcome"].annotation.__args__) == 3


def test_two_appends_of_one_record_leave_one_line(tmp_path: Path) -> None:
    path = tmp_path / HABIT_HITS_FILENAME
    assert append_habit_hit(path, record()) is not None
    assert append_habit_hit(path, record()) is None
    assert len(read_lines(path)) == 1


def test_two_tiers_on_one_tick_are_two_lines(tmp_path: Path) -> None:
    path = tmp_path / HABIT_HITS_FILENAME
    append_habit_hit(path, record())
    append_habit_hit(path, record(tier=str(Tier.DIRECTOR)))
    assert len(read_lines(path)) == 2


def test_the_append_is_physically_append_only(tmp_path: Path) -> None:
    path = tmp_path / HABIT_HITS_FILENAME
    append_habit_hit(path, record())
    before = path.read_bytes()
    append_habit_hit(path, HabitHit.from_facts(facts(), task="task-1", tick=4, ref="r2"))
    assert path.read_bytes().startswith(before)


def test_the_file_is_byte_identical_when_nothing_new_is_appended(tmp_path: Path) -> None:
    path = tmp_path / HABIT_HITS_FILENAME
    append_habit_hit(path, record())
    before = path.read_bytes()
    assert append_habit_hit(path, record()) is None
    assert path.read_bytes() == before


# --------------------------------------------------------------------------------------
# The loader
# --------------------------------------------------------------------------------------


def test_the_loader_reads_a_missing_file_as_no_records(tmp_path: Path) -> None:
    assert load_habit_hits(tmp_path / HABIT_HITS_FILENAME) == []


def test_the_loader_reads_back_what_the_writer_wrote(tmp_path: Path) -> None:
    path = tmp_path / HABIT_HITS_FILENAME
    append_habit_hit(path, record())
    assert load_habit_hits(path) == [record()]


def test_the_loader_refuses_a_schema_version_it_does_not_write(tmp_path: Path) -> None:
    path = tmp_path / HABIT_HITS_FILENAME
    append_habit_hit(path, record())
    payload = {**record().model_dump(mode="json"), "schema_version": 99, "tick": 4}
    path.write_text(
        path.read_text(encoding="utf-8")
        + json.dumps(payload, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaVersionMismatch) as raised:
        load_habit_hits(path)
    assert ARTIFACT in str(raised.value)


# --------------------------------------------------------------------------------------
# The shape order W6's withdrawal reader already joins on (ledger `D16-7`)
# --------------------------------------------------------------------------------------


def test_the_written_line_is_one_the_withdrawal_reader_reads(tmp_path: Path) -> None:
    brain = BrainPaths(root=tmp_path / "brain")
    path = brain.task("task-1").habit_hits
    path.parent.mkdir(parents=True, exist_ok=True)
    append_habit_hit(path, record())
    append_habit_hit(path, HabitHit.from_facts(facts(), task="task-1", tick=5, ref="r5"))

    hits = read_habit_hits(brain)
    assert [(hit.task, hit.tick, hit.procedure_id) for hit in hits] == [
        ("task-1", 3, f"habit-manager-{DIGEST}"),
        ("task-1", 5, f"habit-manager-{DIGEST}"),
    ]
    assert {hit.tier for hit in hits} == {str(Tier.MANAGER)}
    assert hits[0].ref == "task-1:3:cortex:planner:prediction"


# --------------------------------------------------------------------------------------
# The file this one exists in order not to widen (S2, build 2's landed row W3)
# --------------------------------------------------------------------------------------


def test_the_two_records_share_no_field_beyond_the_five_the_join_needs() -> None:
    shared = set(HabitHit.model_fields) & set(SeatCallRecord.model_fields)
    assert shared == {"schema_version", "task", "tick", "tier", "ref"}


def test_neither_record_carries_the_others_defining_field() -> None:
    assert "request" not in HabitHit.model_fields, "a habit records no request bytes"
    assert "procedure_id" not in SeatCallRecord.model_fields, "S2 is not widened"
